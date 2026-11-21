"""Offline replay of observation-based presence for inferred device clusters."""

import argparse
from collections import Counter, deque
from dataclasses import dataclass, field
import json
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research.device_clustering import ClusteringConfig, cluster_devices
from research.evaluate import load_records
from research.stream import RecentProbeRecords


class PresenceConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    observation_window_s: float = Field(default=30, gt=0)
    min_observation_spacing_s: float = Field(default=5, gt=0)
    confirmation_threshold: int = Field(default=3, ge=2, le=100)
    stale_timeout_s: float = Field(default=20, gt=0)
    departure_timeout_s: float = Field(default=60, gt=0)
    heartbeat_timeout_s: float = Field(default=5, gt=0)
    late_tolerance_s: float = Field(default=.25, ge=0)
    absent_retention_s: float = Field(default=120, gt=0)
    max_clusters: int = Field(default=2000, ge=1)
    max_recent_events: int = Field(default=512, ge=1)

    @model_validator(mode='after')
    def check_thresholds(self):
        if self.departure_timeout_s <= self.stale_timeout_s:
            raise ValueError('departure_timeout_s must exceed stale_timeout_s')
        if self.min_observation_spacing_s * (self.confirmation_threshold - 1) >= self.observation_window_s:
            raise ValueError('observation_window_s is too short for the confirmation threshold and spacing')
        return self


@dataclass
class PresenceTrack:
    state: str | None
    state_since: float
    last_seen: float
    last_capture_us: int | None = None
    evidence: deque = field(default_factory=deque)


class PresenceTracker:
    """State machine whose clock advances only during usable observation time."""

    def __init__(self, config, event_sink=None):
        self.config = config
        self.tracks: dict[str, PresenceTrack] = {}
        self.clock = 0.
        self.events = deque(maxlen=config.max_recent_events)
        self.event_sink = event_sink
        self.capacity_drops = 0
        self.cleaned_up = 0
        self.late_observations = 0

    def _transition(self, cluster_id, track, state, when, reason):
        previous = track.state
        track.state, track.state_since = state, when
        event = dict(cluster_id=cluster_id, observation_t_s=when, from_state=previous,
                     to_state=state, reason=reason)
        self.events.append(event)
        if self.event_sink is not None:
            self.event_sink(event)

    def advance(self, t):
        if not math.isfinite(t) or t < self.clock:
            raise ValueError('invalid observation clock')
        cfg = self.config
        deadlines = []
        for cluster_id, track in self.tracks.items():
            if track.state == 'CANDIDATE':
                while track.evidence and t - track.evidence[0][0] > cfg.observation_window_s:
                    track.evidence.popleft()
                absent_at = track.last_seen + cfg.observation_window_s
                absent_reason = 'candidate_window_expired'
            elif track.state in ('CONFIRMED', 'STALE'):
                stale_at = track.last_seen + cfg.stale_timeout_s
                if track.state == 'CONFIRMED' and stale_at <= t:
                    deadlines.append((stale_at, cluster_id, 'STALE', 'no_recent_probe'))
                absent_at = track.last_seen + cfg.departure_timeout_s
                absent_reason = 'observation_timeout'
            else:
                absent_at = track.state_since
                absent_reason = None
            if absent_reason is not None and absent_at <= t:
                deadlines.append((absent_at, cluster_id, 'ABSENT', absent_reason))
            if absent_at + cfg.absent_retention_s <= t:
                deadlines.append((absent_at + cfg.absent_retention_s, cluster_id, None, 'retention_expired'))

        for when, cluster_id, state, reason in sorted(deadlines):
            track = self.tracks[cluster_id]
            self._transition(cluster_id, track, state, when, reason)
            if state is None:
                del self.tracks[cluster_id]
                self.cleaned_up += 1
            elif state == 'ABSENT':
                track.evidence.clear()
        self.clock = t

    def interrupt(self, reason, *, reset_capture_clock=False):
        """An outage invalidates fresh evidence without asserting physical departure."""
        for cluster_id, track in sorted(self.tracks.items()):
            track.evidence.clear()
            if reset_capture_clock:
                track.last_capture_us = None
            if track.state == 'CONFIRMED':
                self._transition(cluster_id, track, 'STALE', self.clock, reason)

    def observe(self, cluster_id, t, capture_us):
        self.advance(t)
        track = self.tracks.get(cluster_id)
        if track is not None and track.last_capture_us is not None and capture_us <= track.last_capture_us:
            self.late_observations += 1
            return False
        if track is None:
            if len(self.tracks) >= self.config.max_clusters:
                self.capacity_drops += 1
                return False
            track = self.tracks[cluster_id] = PresenceTrack(None, t, t)
            self._transition(cluster_id, track, 'CANDIDATE', t, 'first_probe')
        elif track.state == 'ABSENT':
            self._transition(cluster_id, track, 'CANDIDATE', t, 'observed_after_timeout')
        elif track.state == 'STALE':
            self._transition(cluster_id, track, 'CONFIRMED', t, 'observed_again')

        track.last_seen = t
        track.last_capture_us = capture_us
        if track.state != 'CANDIDATE':
            return True

        cfg = self.config
        if track.evidence:
            observed_at, captured_at = track.evidence[-1]
            if min(t - observed_at, (capture_us - captured_at) / 1_000_000) < cfg.min_observation_spacing_s:
                return True
        track.evidence.append((t, capture_us))
        if len(track.evidence) >= cfg.confirmation_threshold:
            self._transition(cluster_id, track, 'CONFIRMED', t, 'independent_observations_reached')
            track.evidence.clear()
        return True

    def snapshot(self):
        counts = Counter(track.state for track in self.tracks.values())
        return dict(**{f'{state.lower()}_count': counts[state]
                       for state in ('CANDIDATE', 'CONFIRMED', 'STALE', 'ABSENT')},
                    capacity_drops=self.capacity_drops, cleaned_up_count=self.cleaned_up,
                    late_observation_count=self.late_observations,
                    clusters=[dict(cluster_id=cluster_id, state=track.state,
                                   state_since_observation_s=track.state_since,
                                   last_seen_observation_s=track.last_seen,
                                   independent_observations_pending=len(track.evidence))
                              for cluster_id, track in sorted(self.tracks.items())])


class PresenceReplay:
    """Map host replay time and sniffer coverage onto the presence clock."""

    def __init__(self, config, alias_map, rssi_min):
        self.config = config
        self.alias_map = alias_map
        self.rssi_min = rssi_min
        self.events = []
        self.offset = 0.
        self.tracker = PresenceTracker(config, self._record_event)
        self.t = 0.
        self.covered_until = None
        self.boot = None
        self.own_mac = None
        self.capture_watermark = None
        self.seen = RecentProbeRecords()
        self.probes_without_coverage = 0

    def _record_event(self, event):
        self.events.append(dict(**event, t_s=self.offset + event['observation_t_s']))

    def _interrupt(self, host_t, reason, *, reset_capture_clock=False):
        self.offset = host_t - self.tracker.clock
        self.tracker.interrupt(reason, reset_capture_clock=reset_capture_clock)
        self.covered_until = None

    def advance(self, t):
        if not math.isfinite(t) or t < self.t:
            raise ValueError('invalid replay clock')
        if self.covered_until is not None:
            end = min(t, self.covered_until)
            self.offset = self.t - self.tracker.clock
            self.tracker.advance(self.tracker.clock + (end - self.t))
            if t > self.covered_until:
                self._interrupt(end, 'heartbeat_gap')
        self.t = t
        self.offset = t - self.tracker.clock

    def feed(self, t, packet):
        """Return the cluster ID when this Probe contributes a valid observation."""
        self.advance(t)
        kind = packet['type']
        if kind == 'control':
            self._interrupt(t, packet['kind'], reset_capture_clock=True)
            self.boot = self.capture_watermark = None
            return
        if kind == 'probe' and not self.seen.remember(packet):
            return
        if self.boot != packet['boot_id']:
            if self.boot is not None:
                self._interrupt(t, 'board_reboot', reset_capture_clock=True)
            self.boot = packet['boot_id']
            self.capture_watermark = None
            self.own_mac = None
        stamp = packet['ts_us']
        watermark = stamp if self.capture_watermark is None else max(stamp, self.capture_watermark)
        self.capture_watermark = watermark
        if kind == 'status':
            self.own_mac = packet['own_mac']
            if packet['capture_active'] and packet['sniffer_enabled']:
                self.covered_until = t + self.config.heartbeat_timeout_s
            else:
                self._interrupt(t, 'radio_inactive')
        elif kind == 'probe':
            mac = packet['source_mac'].lower()
            cluster = self.alias_map.get(mac)
            if cluster is None or mac == self.own_mac or packet['rssi'] < self.rssi_min:
                return
            if self.covered_until is None:
                self.probes_without_coverage += 1
                return
            if (watermark - stamp) / 1_000_000 > self.config.late_tolerance_s:
                self.tracker.late_observations += 1
                return
            if self.tracker.observe(cluster, self.tracker.clock, stamp):
                return cluster

    def report(self):
        return dict(t_s=self.t, observation_t_s=self.tracker.clock,
                    observation_valid=self.covered_until is not None,
                    probes_without_coverage=self.probes_without_coverage,
                    events=self.events, **self.tracker.snapshot())


def replay_presence(records, clustering, config, *, until=None):
    if until is not None and (not math.isfinite(until) or until < 0):
        raise ValueError('until must be a nonnegative finite replay time')
    alias_map = {mac: cluster['cluster_id'] for cluster in clustering['clusters']
                 for mac in cluster['mac_aliases']}
    replay = PresenceReplay(config, alias_map, clustering['config']['rssi_min'])
    for t, packet in records:
        if until is not None and t > until:
            replay.advance(until)
            break
        replay.feed(t, packet)
    return dict(version='cluster-presence-v1', config=config.model_dump(),
                clustering_mode=clustering['mode'], clustering_config=clustering['config'],
                observation_semantics='ABSENT means observation timeout, not physical departure',
                **replay.report())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw', type=Path, help='raw.jsonl của phiên thu')
    parser.add_argument('--config', type=Path, help='cấu hình presence JSON')
    parser.add_argument('--clustering-config', type=Path, help='cấu hình clustering JSON')
    parser.add_argument('--mac-only', action='store_true', help='phát lại với mỗi MAC là một cụm')
    parser.add_argument('--until', type=float, help='dừng replay tại mốc giây từ đầu phiên')
    parser.add_argument('--output', type=Path, help='ghi báo cáo JSON')
    args = parser.parse_args()
    cfg = PresenceConfig.model_validate_json(args.config.read_text()) if args.config else PresenceConfig()
    clustering_cfg = (ClusteringConfig.model_validate_json(args.clustering_config.read_text())
                      if args.clustering_config else ClusteringConfig())
    if args.mac_only:
        clustering_cfg = clustering_cfg.model_copy(update={'enabled': False})
    clustering = cluster_devices(load_records(args.raw), clustering_cfg)
    report = replay_presence(load_records(args.raw), clustering, cfg, until=args.until)
    output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(output + '\n')
    else:
        print(output)


if __name__ == '__main__':
    main()
