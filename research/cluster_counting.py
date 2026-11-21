"""Experimental cluster-based counting for offline replay."""

from collections import defaultdict, deque

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research.dashboard import MAX_RECORDS, RETENTION_S
from research.detectors import Sherlock
from research.device_clustering import cluster_devices
from research.experiment import cluster_map
from research.in_room import estimate_room


WINDOWS = (30, 60)
CLUSTER_METHODS = ('sherlock_cluster', *(f'proposed_{width}s' for width in WINDOWS),
                   *(f'proposed_room_{width}s' for width in WINDOWS))


class EvidenceConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    min_spacing_s: float = Field(default=5, gt=0, lt=30)
    probable_hits: int = Field(default=2, ge=2, le=30)
    confirmed_hits: int = Field(default=3, ge=3, le=30)

    @model_validator(mode='after')
    def check_thresholds(self):
        if self.probable_hits >= self.confirmed_hits or (self.confirmed_hits - 1) * self.min_spacing_s >= min(WINDOWS):
            raise ValueError('evidence thresholds must fit both windows and probable must precede confirmed')
        return self


def independent_hits(observations, start, spacing):
    last = None
    hits = 0
    for t, radio_time in observations:
        if t < start:
            continue
        if last is None or min(t - last[0], (radio_time - last[1]) / 1_000_000) >= spacing:
            hits += 1
            last = t, radio_time
    return hits


class ClusterReplay:
    """Rebuild association on each available prefix, within a bounded capture segment."""

    def __init__(self, config, setup_id):
        self.cfg = config
        self.setup_id = setup_id
        self.clustering = config.clustering.model_copy(update={'rssi_min': config.probe.rssi_min})
        self.presence = config.presence.model_copy(update={'heartbeat_timeout_s': config.probe.heartbeat_s})
        self.records = deque()
        self.last_status = None
        self.continuous_since = None
        self.overflow_at = None

    def feed(self, t, packet, reason, *, reset=False):
        kind = packet['type']
        loss = False
        if kind == 'status':
            status = (packet['boot_id'], packet['probe_dropped'], packet['serial_errors'],
                      packet['scan_mode'], packet['own_mac'],
                      packet['channel'] if packet['scan_mode'] == 'fixed' else None)
            if self.last_status is not None:
                boot, dropped, errors, *profile = self.last_status
                loss = (boot != status[0] or status[1] > dropped or status[2] > errors
                        or list(status[3:]) != profile)
            self.last_status = status
        if reset or loss:
            self.records.clear()
            self.continuous_since = self.overflow_at = None
        if kind == 'status':
            if not packet['capture_active'] or not packet['sniffer_enabled']:
                return
            if self.continuous_since is None:
                self.continuous_since = t
        if kind in ('status', 'channel') or reason == 'accepted':
            if len(self.records) == MAX_RECORDS:
                self.overflow_at, _ = self.records.popleft()
            self.records.append((t, packet))

    def snapshot(self, t, valid):
        methods = set(self.cfg.methods) & set(CLUSTER_METHODS)
        result = dict.fromkeys(methods)
        result.update(cluster_capacity_limited=False, cluster_coverage_s=None)
        for width in WINDOWS:
            if {f'proposed_{width}s', f'proposed_room_{width}s'} & methods:
                for state in ('candidate', 'probable', 'confirmed'):
                    result[f'{state}_clusters_{width}s'] = None
        if not valid or self.continuous_since is None:
            return result

        result['cluster_coverage_s'] = t - self.continuous_since
        cutoff = t - RETENTION_S
        while self.records and self.records[0][0] < cutoff:
            self.records.popleft()
        aliases = {packet['source_mac'] for _, packet in self.records if packet['type'] == 'probe'}
        if len(aliases) > self.cfg.max_cluster_aliases or (self.overflow_at is not None and self.overflow_at >= cutoff):
            result['cluster_capacity_limited'] = True
            return result

        clustering = cluster_devices(self.records, self.clustering)
        mapping = cluster_map(clustering)
        evidence = defaultdict(list)
        engine = Sherlock(self.cfg.probe) if 'sherlock_cluster' in methods else None
        for stamp, packet in self.records:
            if packet['type'] != 'probe':
                continue
            cluster_id = mapping[packet['source_mac']]
            evidence[cluster_id].append((stamp, packet['ts_us']))
            if engine is not None:
                engine.observe(dict(source_mac=cluster_id, rssi=packet['rssi']), stamp)
        if engine is not None:
            result['sherlock_cluster'] = engine.snapshot(t)['count']

        location = None
        cfg = self.cfg.evidence
        for width in WINDOWS:
            observed_name, room_name = f'proposed_{width}s', f'proposed_room_{width}s'
            if not ({observed_name, room_name} & methods) or t - self.continuous_since < width:
                continue
            states = {'candidate': set(), 'probable': set(), 'confirmed': set()}
            for cluster, observations in evidence.items():
                hits = independent_hits(observations, t - width, cfg.min_spacing_s)
                if hits:
                    state = ('confirmed' if hits >= cfg.confirmed_hits
                             else 'probable' if hits >= cfg.probable_hits else 'candidate')
                    states[state].add(cluster)
            for state, clusters in states.items():
                result[f'{state}_clusters_{width}s'] = len(clusters)
            selected = states['probable'] | states['confirmed']
            if observed_name in methods:
                result[observed_name] = len(selected)
            if room_name in methods and self.cfg.calibration is not None:
                if location is None:
                    location = self.room_locations(t, clustering)
                if location is not None and selected <= location.keys():
                    result[room_name] = sum(location[cluster] == 'in_room_confirmed' for cluster in selected)
        return result

    def room_locations(self, t, clustering):
        # The production classifier requires evidence of its own. An unclassified
        # PROBABLE cluster keeps the experimental physical count unavailable.
        room = estimate_room(self.records, clustering, self.presence, self.cfg.location,
                             source_clock=t, setup_id=self.setup_id, calibration=self.cfg.calibration)
        if (room['calibration_status'] != 'ready' or not room['observation_valid']
                or room['continuous_coverage_s'] < self.cfg.location.window_s):
            return None
        return {row['cluster_id']: row['location'] for row in room['clusters']
                if row['location'] in ('in_room_confirmed', 'outside_likely')}
