"""Conservative offline association of WiFi Probe MAC aliases within one capture."""

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from statistics import median

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research.evaluate import load_records
from research.ie_profile import parse_ie, similarity
from research.stream import MacObservation, RecentProbeRecords


class ClusteringConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    enabled: bool = True
    rssi_min: int = Field(default=-127, ge=-127, le=0)
    min_probes: int = Field(default=3, ge=2)
    min_distinct_ie_ids: int = Field(default=3, ge=1, le=24)
    min_profile_fraction: float = Field(default=0.6, gt=0.5, le=1)
    max_gap_s: float = Field(default=30, gt=0)
    overlap_tolerance_s: float = Field(default=0.05, ge=0)
    max_rssi_delta_db: float = Field(default=12, gt=0)
    max_rssi_spread_db: float = Field(default=18, ge=0)
    reject_ie_below: float = Field(default=0.55, ge=0, le=1)
    min_ie_similarity: float = Field(default=0.85, ge=0, le=1)
    match_threshold: float = Field(default=0.82, ge=0, le=1)
    ambiguity_margin: float = Field(default=0.06, gt=0, le=1)

    @model_validator(mode='after')
    def validate_ie_thresholds(self):
        if self.reject_ie_below > self.min_ie_similarity:
            raise ValueError('reject_ie_below must be <= min_ie_similarity')
        return self


@dataclass
class AliasTrack:
    observation: MacObservation
    spans: dict[int, tuple[int, int]] = field(default_factory=dict)
    samples: dict[int, list[int]] = field(default_factory=lambda: defaultdict(list))
    signatures: Counter = field(default_factory=Counter)

    @property
    def mac(self):
        return self.observation.mac

    def observe(self, packet, t, scope, cfg):
        stamp = packet['ts_us']
        start, end = self.spans.get(scope, (stamp, stamp))
        self.spans[scope] = (min(start, stamp), max(end, stamp))
        self.observation.observe(packet, t, 'accepted')
        self.samples[packet['channel']].append(packet['rssi'])
        profile = parse_ie(packet.get('ie'))
        distinct_ids = {element_id for element_id, _ in profile.elements}
        if profile.signature and not profile.possibly_truncated and len(distinct_ids) >= cfg.min_distinct_ie_ids:
            self.signatures[profile.signature] += 1

    def order_key(self):
        scope = min(self.spans)
        return scope, self.spans[scope][0], self.mac


@dataclass(frozen=True)
class PairDecision:
    mac_alias: str
    decision: str
    reason: str
    heuristic_score: float | None = None
    evidence: dict = field(default_factory=dict)


def track_aliases(records, cfg):
    """Reuse tracker normalization and record identity, retaining session-wide spans."""
    tracker = {}
    seen = RecentProbeRecords()
    scope = 0
    boot = None
    for t, packet in records:
        if packet['type'] == 'control':
            scope += 1
            boot = None
            continue
        is_probe = packet['type'] == 'probe'
        if is_probe and not seen.remember(packet):
            continue
        if boot is not None and boot != packet['boot_id']:
            scope += 1
        boot = packet['boot_id']
        if not is_probe or packet['rssi'] < cfg.rssi_min:
            continue
        mac = packet['source_mac'].lower()
        if mac not in tracker:
            tracker[mac] = AliasTrack(MacObservation(mac, t, t))
        tracker[mac].observe(packet, t, scope, cfg)
    return sorted(tracker.values(), key=AliasTrack.order_key)


def dominant_fingerprint(track, cfg):
    if not track.signatures:
        return None
    signature, count = min(track.signatures.items(), key=lambda entry: (-entry[1], entry[0]))
    if count < cfg.min_probes or count / track.observation.probe_count < cfg.min_profile_fraction:
        return None
    return parse_ie(signature)


def channel_statistics(track):
    return {channel: dict(probes=len(samples), median_dbm=median(samples), spread_db=max(samples)-min(samples))
            for channel, samples in sorted(track.samples.items())}


def candidate_in_window(previous, current, cfg):
    for scope in previous.spans.keys() & current.spans.keys():
        a, b = previous.spans[scope], current.spans[scope]
        separation_us = max(a[0], b[0]) - min(a[1], b[1])
        if separation_us <= cfg.max_gap_s * 1_000_000:
            return True
    return False


def associate(previous, current, cfg, profiles, statistics):
    evidence = dict(previous_probe_count=previous.observation.probe_count,
                    current_probe_count=current.observation.probe_count,
                    previous_profile_support=max(previous.signatures.values(), default=0),
                    current_profile_support=max(current.signatures.values(), default=0))

    def decision(verdict, reason, score=None):
        return PairDecision(previous.mac, verdict, reason, score, evidence)

    common_scopes = sorted(previous.spans.keys() & current.spans.keys())
    overlaps = [min(previous.spans[key][1], current.spans[key][1]) -
                max(previous.spans[key][0], current.spans[key][0]) for key in common_scopes]
    overlap_s = max(0, max(overlaps, default=0)) / 1_000_000
    evidence.update(common_capture_scopes=common_scopes, overlap_s=overlap_s)
    if overlap_s > cfg.overlap_tolerance_s:
        return decision('NON_MATCH', 'overlapping_mac_activity')
    if len(common_scopes) != 1 or len(previous.spans) != 1 or len(current.spans) != 1:
        return decision('AMBIGUOUS', 'capture_boundary')

    scope = common_scopes[0]
    gap = (current.spans[scope][0] - previous.spans[scope][1]) / 1_000_000
    evidence['handoff_gap_s'] = gap
    if gap <= 0 or gap > cfg.max_gap_s:
        return decision('AMBIGUOUS', 'no_clean_handoff' if gap <= 0 else 'handoff_gap_too_long')

    left, right = profiles[previous.mac], profiles[current.mac]
    if left is None or right is None:
        return decision('AMBIGUOUS', 'insufficient_stable_ie')
    ie = similarity(left, right)
    evidence['ie_similarity'] = ie
    if ie['score'] < cfg.reject_ie_below:
        return decision('NON_MATCH', 'incompatible_ie')

    a, b = statistics[previous.mac], statistics[current.mac]
    common_channels = sorted(a.keys() & b.keys())
    sampled_channels = [channel for channel in common_channels
                        if min(a[channel]['probes'], b[channel]['probes']) >= 2]
    evidence.update(common_channels=common_channels, compared_channels=sampled_channels)
    if not sampled_channels:
        return decision('AMBIGUOUS', 'no_comparable_channel_rssi')

    rssi_delta = max(abs(a[channel]['median_dbm'] - b[channel]['median_dbm']) for channel in sampled_channels)
    spread = max(max(a[channel]['spread_db'], b[channel]['spread_db']) for channel in sampled_channels)
    temporal_score = 1 - gap / cfg.max_gap_s
    rssi_score = max(0., 1 - rssi_delta / cfg.max_rssi_delta_db)
    channel_score = len(common_channels) / len(a.keys() | b.keys())
    score = (55 * ie['score'] + 20 * temporal_score + 20 * rssi_score + 5 * channel_score) / 100
    evidence.update(rssi_delta_db=rssi_delta, rssi_spread_db=spread, temporal_score=temporal_score,
                    rssi_score=rssi_score, channel_score=channel_score)
    if spread > cfg.max_rssi_spread_db or rssi_delta > cfg.max_rssi_delta_db:
        return decision('AMBIGUOUS', 'unstable_or_different_rssi', score)
    if ie['score'] < cfg.min_ie_similarity or score < cfg.match_threshold:
        return decision('AMBIGUOUS', 'below_match_threshold', score)
    return decision('MATCH', 'ie_time_rssi_channel_agree', score)


@dataclass
class DeviceCluster:
    cluster_id: str
    aliases: list[AliasTrack] = field(default_factory=list)
    confidence: float | None = None
    association_history: list[dict] = field(default_factory=list)

    def describe(self, profiles, statistics):
        return dict(
            cluster_id=self.cluster_id,
            mac_aliases=[alias.mac for alias in self.aliases],
            first_seen_s=min(alias.observation.first_seen_s for alias in self.aliases),
            last_seen_s=max(alias.observation.last_seen_s for alias in self.aliases),
            fingerprint_profile={alias.mac: profiles[alias.mac].describe() if profiles[alias.mac] else None
                                 for alias in self.aliases},
            rssi_statistics={alias.mac: statistics[alias.mac] for alias in self.aliases},
            confidence=dict(kind='uncalibrated_heuristic', score=self.confidence),
            association_history=self.association_history,
        )


def compare_cluster(cluster, track, cfg, profiles, statistics):
    pairs = [associate(alias, track, cfg, profiles, statistics) for alias in cluster.aliases]
    if any(pair.decision == 'NON_MATCH' for pair in pairs):
        decision = 'NON_MATCH'
    elif all(pair.decision == 'MATCH' for pair in pairs):
        decision = 'MATCH'
    else:
        decision = 'AMBIGUOUS'
    scores = [pair.heuristic_score for pair in pairs if pair.heuristic_score is not None]
    return dict(candidate_cluster_id=cluster.cluster_id, decision=decision,
                heuristic_score=min(scores) if len(scores) == len(pairs) else None,
                pairs=[asdict(pair) for pair in pairs])


def competing_successor(cluster, current, tracks, best, cfg, profiles, statistics):
    # A MATCH always has a single capture scope. Check rival successors on both
    # sides of the current alias so input order cannot break an ambiguous tie.
    scope, (start, end) = next(iter(current.spans.items()))
    for other in tracks:
        if other is current or scope not in other.spans:
            continue
        other_start, other_end = other.spans[scope]
        overlap_us = min(end, other_end) - max(start, other_start)
        if overlap_us <= cfg.overlap_tolerance_s * 1_000_000:
            continue
        comparison = compare_cluster(cluster, other, cfg, profiles, statistics)
        score = comparison['heuristic_score']
        if (comparison['decision'] != 'NON_MATCH' and score is not None
                and best['heuristic_score'] - score < cfg.ambiguity_margin):
            return {'mac': other.mac, 'comparison': comparison}
    return None


def cluster_devices(records, cfg):
    tracks = track_aliases(records, cfg)
    profiles = {track.mac: dominant_fingerprint(track, cfg) for track in tracks}
    statistics = {track.mac: channel_statistics(track) for track in tracks}
    clusters = {}
    for track in tracks:
        candidates = [compare_cluster(cluster, track, cfg, profiles, statistics)
                      for cluster in clusters.values()
                      if cfg.enabled and any(candidate_in_window(alias, track, cfg) for alias in cluster.aliases)]
        matches = sorted((row for row in candidates if row['decision'] == 'MATCH'),
                         key=lambda row: (-row['heuristic_score'], row['candidate_cluster_id']))
        best = matches[0] if matches else None
        close_alternative = best is not None and any(
            row is not best and row['decision'] != 'NON_MATCH' and row['heuristic_score'] is not None
            and best['heuristic_score'] - row['heuristic_score'] < cfg.ambiguity_margin for row in candidates)
        rival_successor = competing_successor(clusters[best['candidate_cluster_id']], track, tracks,
                                               best, cfg, profiles, statistics) if best is not None else None
        if best is not None and not close_alternative and rival_successor is None:
            cluster = clusters[best['candidate_cluster_id']]
            verdict, reason = 'MATCH', 'complete_link_match'
            score = best['heuristic_score']
            cluster.confidence = score if cluster.confidence is None else min(cluster.confidence, score)
        else:
            cluster_id = f'cluster-{len(clusters) + 1:05d}'
            cluster = clusters[cluster_id] = DeviceCluster(cluster_id)
            score = None
            if not cfg.enabled:
                verdict, reason = None, 'mac_only'
            elif close_alternative or rival_successor is not None:
                verdict, reason = 'AMBIGUOUS', 'competing_candidates'
            elif candidates and all(row['decision'] == 'NON_MATCH' for row in candidates):
                verdict, reason = 'NON_MATCH', 'all_candidates_conflict'
            else:
                verdict = 'AMBIGUOUS'
                reason = 'insufficient_pair_evidence' if candidates else 'no_candidate_in_handoff_window'
        cluster.aliases.append(track)
        cluster.association_history.append(dict(mac=track.mac, decision=verdict, reason=reason,
                                                heuristic_score=score, candidates=candidates,
                                                competing_successor=rival_successor))

    return dict(version='device-clustering-v1', mode='clustering' if cfg.enabled else 'mac-only',
                config=cfg.model_dump(), raw_mac_count=len(tracks), inferred_cluster_count=len(clusters),
                clusters=[cluster.describe(profiles, statistics) for cluster in clusters.values()])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw', type=Path, help='raw.jsonl hoặc JSONL UART')
    parser.add_argument('--config', type=Path, help='cấu hình clustering JSON')
    parser.add_argument('--mac-only', action='store_true', help='mỗi MAC là một mục baseline')
    parser.add_argument('--output', type=Path, help='ghi báo cáo JSON')
    args = parser.parse_args()
    cfg = ClusteringConfig.model_validate_json(args.config.read_text()) if args.config else ClusteringConfig()
    if args.mac_only:
        cfg = cfg.model_copy(update={'enabled': False})
    report = cluster_devices(load_records(args.raw), cfg)
    output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(output + '\n')
    else:
        print(output)


if __name__ == '__main__':
    main()
