"""Offline in-room estimation for confirmed clusters using labeled RSSI windows."""

import argparse
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import json
import math
from pathlib import Path
from statistics import median
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.protocol import mac_valid
from research.device_clustering import ClusteringConfig, cluster_devices
from research.evaluate import load_records
from research.presence import PresenceConfig, PresenceReplay


Zone = Literal['inside_near', 'inside_far', 'inside_boundary', 'hallway', 'outside_boundary']
INSIDE_ZONES = {'inside_near', 'inside_far', 'inside_boundary'}
OUTSIDE_ZONES = {'hallway', 'outside_boundary'}


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class InRoomConfig(Settings):
    window_s: int = Field(default=30, ge=4)
    bin_s: int = Field(default=5, ge=1)
    min_observations: int = Field(default=4, ge=2)
    min_observation_ratio: float = Field(default=.65, gt=0, le=1)
    max_age_s: float = Field(default=7, gt=0)
    max_recent_shift_db: float = Field(default=8, gt=0)
    max_mad_db: float = Field(default=6, gt=0)
    min_reference_windows: int = Field(default=3, ge=1)
    min_reference_sessions: int = Field(default=2, ge=1)
    rssi_scale_db: float = Field(default=8, gt=0)
    mad_scale_db: float = Field(default=4, gt=0)
    ratio_scale: float = Field(default=.25, gt=0, le=1)
    max_reference_distance: float = Field(default=.50, gt=0)
    opposite_guard_distance: float = Field(default=.65, gt=0)
    min_class_margin: float = Field(default=.25, gt=0)

    @model_validator(mode='after')
    def check_window(self):
        if self.window_s % (2 * self.bin_s) or self.window_s // self.bin_s < max(4, self.min_observations):
            raise ValueError('window_s must contain an even number of bins and at least min_observations bins')
        if self.opposite_guard_distance < self.max_reference_distance:
            raise ValueError('opposite_guard_distance must be at least max_reference_distance')
        return self


class SignalVector(Settings):
    median_rssi_dbm: float = Field(ge=-127, le=0)
    rssi_mad_db: float = Field(ge=0, le=127)
    observation_ratio: float = Field(gt=0, le=1)


class ReferenceWindow(Settings):
    session_id: str = Field(min_length=1)
    window_end_s: float = Field(ge=0)
    zone: Zone
    features: SignalVector


class RoomCalibration(Settings):
    version: Literal['in-room-reference-v1'] = 'in-room-reference-v1'
    setup_id: str = Field(min_length=1)
    sniffer_mac: str
    channel: int = Field(ge=1, le=13)
    window_s: int = Field(ge=1)
    bin_s: int = Field(ge=1)
    rssi_min: int = Field(ge=-127, le=0)
    samples: list[ReferenceWindow]

    @model_validator(mode='after')
    def check_samples(self):
        if not mac_valid(self.sniffer_mac):
            raise ValueError('invalid sniffer MAC')
        self.sniffer_mac = self.sniffer_mac.lower()
        keys = {(sample.session_id, sample.window_end_s) for sample in self.samples}
        if len(keys) != len(self.samples):
            raise ValueError('duplicate reference window in the same session')
        return self


@dataclass(frozen=True)
class SignalSample:
    t: float
    cluster_id: str
    rssi: int
    channel: int


def window_features(samples, as_of, config):
    bins = defaultdict(list)
    channels = set()
    last_seen = None
    for sample in samples:
        age = as_of - sample.t
        if 0 <= age < config.window_s:
            bins[int(age // config.bin_s)].append(sample.rssi)
            channels.add(sample.channel)
            last_seen = sample.t if last_seen is None else max(last_seen, sample.t)
    bin_medians = {index: median(values) for index, values in bins.items()}
    half = config.window_s // (2 * config.bin_s)
    recent = [value for index, value in bin_medians.items() if index < half]
    older = [value for index, value in bin_medians.items() if index >= half]
    center = median(bin_medians.values()) if bin_medians else None
    shift = None
    if len(recent) >= 2 and len(older) >= 2:
        baseline = median(older)
        shift = max(abs(median(recent) - baseline), abs(bin_medians[min(bin_medians)] - baseline))
    return dict(median_rssi_dbm=center,
                rssi_mad_db=median(abs(value - center) for value in bin_medians.values()) if bin_medians else None,
                probe_count=sum(len(values) for values in bins.values()),
                observation_count=len(bins), observation_ratio=len(bins) * config.bin_s / config.window_s,
                last_seen_s=last_seen, channels=sorted(channels),
                recent_shift_db=shift)


def assess_window(features, as_of, continuous_since, profile, cfg):
    if continuous_since is None or as_of - continuous_since < cfg.window_s:
        return 'insufficient_continuous_coverage'
    if (features['observation_count'] < cfg.min_observations
            or features['observation_ratio'] < cfg.min_observation_ratio):
        return 'insufficient_observations'
    if as_of - features['last_seen_s'] > cfg.max_age_s:
        return 'last_observation_too_old'
    if features['recent_shift_db'] is None:
        return 'insufficient_temporal_comparison'
    if features['recent_shift_db'] > cfg.max_recent_shift_db or features['rssi_mad_db'] > cfg.max_mad_db:
        return 'unstable_or_changing_rssi'
    if profile is None or profile[1] != 'fixed' or features['channels'] != [profile[2]]:
        return 'unsupported_or_mixed_channels'
    return None


def reference_status(calibration, setup_id, cfg, profile, sniffer_macs, rssi_min):
    if calibration is None:
        return 'missing_calibration'
    expected = calibration.sniffer_mac, 'fixed', calibration.channel
    if (setup_id != calibration.setup_id or profile != expected or sniffer_macs != {calibration.sniffer_mac}
            or (cfg.window_s, cfg.bin_s, rssi_min) != (calibration.window_s, calibration.bin_s, calibration.rssi_min)):
        return 'calibration_setup_mismatch'
    counts = Counter(sample.zone for sample in calibration.samples)
    sessions = defaultdict(set)
    for sample in calibration.samples:
        sessions[sample.zone].add(sample.session_id)
    if any(counts[zone] < cfg.min_reference_windows or len(sessions[zone]) < cfg.min_reference_sessions
           for zone in INSIDE_ZONES | OUTSIDE_ZONES):
        return 'insufficient_calibration'
    return 'ready'


def classify(features, calibration, cfg):
    distances = {}
    support = defaultdict(set)
    for sample in calibration.samples:
        vector = sample.features
        distance = (abs(features['median_rssi_dbm'] - vector.median_rssi_dbm) / cfg.rssi_scale_db
                    + abs(features['rssi_mad_db'] - vector.rssi_mad_db) / cfg.mad_scale_db
                    + abs(features['observation_ratio'] - vector.observation_ratio) / cfg.ratio_scale) / 3
        side = 'inside' if sample.zone in INSIDE_ZONES else 'outside'
        if distance <= cfg.max_reference_distance:
            support[side].add(sample.session_id)
        if side not in distances or distance < distances[side][0]:
            distances[side] = (distance, sample.zone)

    inside, outside = distances['inside'][0], distances['outside'][0]
    best, rival = sorted((inside, outside))
    side = 'inside' if inside < outside else 'outside'
    score = dict(in_room_heuristic_score=1 / (1 + inside), inside_distance=inside, outside_distance=outside,
                 nearest_inside_zone=distances['inside'][1], nearest_outside_zone=distances['outside'][1],
                 inside_support_sessions=len(support['inside']), outside_support_sessions=len(support['outside']))
    if best > cfg.max_reference_distance:
        return 'location_unknown', 'out_of_reference_distribution', score
    if rival <= cfg.opposite_guard_distance or rival - best < cfg.min_class_margin:
        return 'location_unknown', 'overlapping_location_evidence', score
    if len(support[side]) < cfg.min_reference_sessions:
        return 'location_unknown', 'insufficient_nearby_reference_sessions', score
    return ('in_room_confirmed' if side == 'inside' else 'outside_likely'), 'reference_agreement', score


def estimate_room(records, clustering, presence_cfg, cfg, *, setup_id=None, calibration=None, until=None,
                  source_clock=None, include_presence=False):
    if source_clock is not None:
        until = source_clock
    if until is not None and (not math.isfinite(until) or until < 0):
        raise ValueError('until must be a nonnegative finite replay time')
    aliases = {mac: cluster['cluster_id'] for cluster in clustering['clusters'] for mac in cluster['mac_aliases']}
    rssi_min = clustering['config']['rssi_min']
    replay = PresenceReplay(presence_cfg, aliases, rssi_min)
    history = deque()
    sniffer_macs = set()
    profile = None
    continuous_since = None
    previous_counters = None
    for t, packet in records:
        if until is not None and t > until:
            replay.advance(until)
            break
        if until is None and packet['type'] == 'control' and packet['kind'] == 'session_stopped':
            break
        previous_deadline, previous_boot = replay.covered_until, replay.boot
        accepted = replay.feed(t, packet)
        if replay.covered_until is None:
            continuous_since = None
        elif previous_deadline is None or t > previous_deadline or replay.boot != previous_boot:
            continuous_since = t
        if packet['type'] == 'status':
            sniffer_macs.add(packet['own_mac'])
            current = packet['own_mac'], packet['scan_mode'], packet['channel'] if packet['scan_mode'] == 'fixed' else None
            counters = packet['probe_dropped'], packet['serial_errors']
            lost_records = (previous_boot == replay.boot and previous_counters is not None and
                            any(new > old for new, old in zip(counters, previous_counters)))
            if (current != profile or lost_records) and replay.covered_until is not None:
                continuous_since = t
            profile, previous_counters = current, counters
        elif packet['type'] == 'channel' and profile is not None and profile[1] == 'fixed' and packet['channel'] != profile[2]:
            profile, continuous_since = None, None
        if accepted is not None:
            history.append(SignalSample(t, accepted, packet['rssi'], packet['channel']))
        while history and t - history[0].t >= cfg.window_s:
            history.popleft()

    if source_clock is not None:
        replay.advance(source_clock)
    as_of = replay.t
    if replay.covered_until is None:
        continuous_since = None
    by_cluster = defaultdict(list)
    for sample in history:
        if continuous_since is None or sample.t >= continuous_since:
            by_cluster[sample.cluster_id].append(sample)
    calibration_status = reference_status(calibration, setup_id, cfg, profile, sniffer_macs, rssi_min)
    rows = []
    for cluster_id, track in sorted(replay.tracker.tracks.items()):
        if track.state != 'CONFIRMED':
            continue
        features = window_features(by_cluster[cluster_id], as_of, cfg)
        quality_issue = assess_window(features, as_of, continuous_since, profile, cfg)
        reason = quality_issue or (calibration_status if calibration_status != 'ready' else None)
        if reason is None:
            location, reason, evidence = classify(features, calibration, cfg)
        else:
            location, evidence = 'location_unknown', None
        rows.append(dict(cluster_id=cluster_id, presence_state='CONFIRMED', location=location,
                         reason=reason, reference_eligible=quality_issue is None and len(sniffer_macs) == 1,
                         features=features, evidence=evidence))
    counts = Counter(row['location'] for row in rows)
    result = dict(version='in-room-estimation-v1', t_s=as_of, observation_valid=replay.covered_until is not None,
                continuous_coverage_s=as_of - continuous_since if continuous_since is not None else 0,
                setup_id=setup_id, observed_sniffer_count=len(sniffer_macs), sniffer_macs=sorted(sniffer_macs),
                scan_mode=profile[1] if profile else None, fixed_channel=profile[2] if profile else None,
                config=cfg.model_dump(), presence_config=presence_cfg.model_dump(), clustering_config=clustering['config'],
                rssi_min=rssi_min, calibration_status=calibration_status, score_semantics='uncalibrated_heuristic',
                estimated_in_room_count=counts['in_room_confirmed'], outside_likely_count=counts['outside_likely'],
                location_unknown_count=counts['location_unknown'], confirmed_count=len(rows), clusters=rows)
    if include_presence:
        result['presence'] = replay.report()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw', type=Path)
    parser.add_argument('--setup-id', help='mã bố trí phòng và vị trí sniffer')
    parser.add_argument('--config', type=Path, help='ngưỡng ước lượng vị trí JSON')
    parser.add_argument('--presence-config', type=Path)
    parser.add_argument('--clustering-config', type=Path)
    parser.add_argument('--calibration', type=Path, help='các cửa sổ RSSI có nhãn')
    parser.add_argument('--until', type=float, help='mốc đánh giá theo giây trong phiên có dữ liệu')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    cfg = InRoomConfig.model_validate_json(args.config.read_text()) if args.config else InRoomConfig()
    presence = PresenceConfig.model_validate_json(args.presence_config.read_text()) if args.presence_config else PresenceConfig()
    clustering_cfg = (ClusteringConfig.model_validate_json(args.clustering_config.read_text())
                      if args.clustering_config else ClusteringConfig())
    calibration = RoomCalibration.model_validate_json(args.calibration.read_text()) if args.calibration else None
    clustering = cluster_devices(load_records(args.raw), clustering_cfg)
    report = estimate_room(load_records(args.raw), clustering, presence, cfg, setup_id=args.setup_id,
                           calibration=calibration, until=args.until)
    output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(output + '\n')
    else:
        print(output)


if __name__ == '__main__':
    main()
