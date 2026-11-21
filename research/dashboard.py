"""Bounded dashboard snapshots derived from the collector's Probe records."""

import asyncio
from collections import defaultdict, deque
from hashlib import sha256
import hmac
from secrets import token_bytes
from statistics import median
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from research.device_clustering import ClusteringConfig, cluster_devices
from research.in_room import InRoomConfig, RoomCalibration, estimate_room
from research.presence import PresenceConfig


METRICS = ('raw_mac_count', 'active_mac_count', 'inferred_cluster_count', 'candidate_count',
           'confirmed_count', 'stale_count', 'absent_count', 'estimated_in_room_count',
           'outside_likely_count', 'location_unknown_count')
RETENTION_S = 300
MAX_RECORDS = 12_000
MAX_CLUSTER_ALIASES = 128
SOURCE = {'serial': 'LIVE', 'replay': 'REPLAY', 'synthetic': 'DEMO'}


class DashboardConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    setup_id: str | None = None
    calibration: RoomCalibration | None = None
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    presence: PresenceConfig = Field(default_factory=PresenceConfig)
    location: InRoomConfig = Field(default_factory=InRoomConfig)


class DashboardBuffer:
    def __init__(self, config):
        self.config = config
        self.setup_id = config.setup_id
        self.source_id = uuid4().hex
        self.secret = token_bytes(32)
        self.records = deque(maxlen=MAX_RECORDS)
        self.history = deque(maxlen=301)
        self.dropped_at = None
        self.lock = asyncio.Lock()
        self.cached = None
        self.cache_key = None

    def add(self, t, packet):
        if len(self.records) == MAX_RECORDS:
            self.dropped_at = self.records[0][0]
        self.records.append((t, packet))

    def capture(self, t, state):
        while self.records and self.records[0][0] < t - RETENTION_S:
            self.records.popleft()
        return (tuple(self.records), t, state, self.dropped_at is not None and self.dropped_at >= t - RETENTION_S)

    async def snapshot(self, capture):
        records, t, state, truncated = capture
        key = (int(t), state['mode'], state['connection'], state['valid'], truncated)
        async with self.lock:
            if key == self.cache_key:
                return self.cached
            result = await asyncio.to_thread(self.analyze, records, t, state, truncated)
            if not self.history or t >= self.history[-1]['t_s']:
                if self.history and int(t) == int(self.history[-1]['t_s']):
                    self.history.pop()
                self.history.append(dict(t_s=t, **result['metrics']))
                while self.history and self.history[0]['t_s'] < t - RETENTION_S:
                    self.history.popleft()
                self.cache_key = key
                self.cached = dict(**result, history=list(self.history))
                return self.cached
            return dict(**result, history=[sample for sample in self.history if sample['t_s'] <= t])

    def analyze(self, records, t, state, truncated):
        source = SOURCE.get(state['mode'])
        connection = state['connection']
        finished = connection == 'finished'
        usable = state['valid'] or (finished and source in ('REPLAY', 'DEMO'))
        status = 'error' if connection == 'error' else 'disconnected'
        if source and connection in ('connecting', 'connected'):
            status = 'waiting'
        cfg = self.config
        result = dict(version='probe-dashboard-v1', source_id=self.source_id, source=source,
                      connection=connection, status=status, t_s=t, analysis_window_s=RETENTION_S,
                      truncated=truncated, calibration_status=None,
                      metrics=dict.fromkeys(METRICS), clusters=[])
        if not usable:
            return result

        radio_cfg = state['config']
        excluded = set(radio_cfg['excluded_macs'])
        filtered = tuple((stamp, p) for stamp, p in records if p.get('source_mac') not in excluded)
        cluster_cfg = cfg.clustering.model_copy(update={'rssi_min': radio_cfg['rssi_min']})
        aliases = {p['source_mac'] for _, p in filtered if p['type'] == 'probe' and p['rssi'] >= cluster_cfg.rssi_min}
        if len(aliases) > MAX_CLUSTER_ALIASES:
            result['status'] = 'limited'
            result['metrics'].update(raw_mac_count=state['raw_mac_count'], active_mac_count=state['active_mac_count'])
            return result
        clustering = cluster_devices(filtered, cluster_cfg)
        replay_cfg = cfg.presence.model_copy(update={'heartbeat_timeout_s': radio_cfg['heartbeat_s']})
        # A completed recording's explicit stop marker ends live coverage. Use the
        # final recorded sample before that marker for the completed replay card.
        source_clock = t
        if finished and filtered and filtered[-1][1].get('kind') == 'session_stopped':
            filtered = filtered[:-1]
            source_clock = filtered[-1][0] if filtered else t
        room = estimate_room(filtered, clustering, replay_cfg, cfg.location, setup_id=self.setup_id,
                             calibration=cfg.calibration, source_clock=source_clock, include_presence=True)
        result['calibration_status'] = room['calibration_status']
        if not room['observation_valid']:
            result['status'] = 'finished' if finished else 'waiting'
            return result

        presence = room['presence']
        metrics = {key: presence[key] for key in ('candidate_count', 'confirmed_count', 'stale_count', 'absent_count')}
        metrics.update(raw_mac_count=state['raw_mac_count'], active_mac_count=state['active_mac_count'],
                       inferred_cluster_count=clustering['inferred_cluster_count'],
                       outside_likely_count=room['outside_likely_count'],
                       location_unknown_count=room['location_unknown_count'])
        location_ready = (room['calibration_status'] == 'ready'
                          and room['continuous_coverage_s'] >= cfg.location.window_s)
        if location_ready and not room['location_unknown_count'] and not truncated and source != 'DEMO':
            metrics['estimated_in_room_count'] = room['estimated_in_room_count']
        else:
            metrics['estimated_in_room_count'] = None

        result.update(status='finished' if finished else 'ready' if clustering['clusters'] else 'empty',
                      metrics=metrics, clusters=self.cluster_rows(clustering, presence, room),
                      location_ready=location_ready)
        return result

    def cluster_rows(self, clustering, presence, room):
        # A per-source keyed identifier keeps raw aliases out of dashboard payloads.
        ids = {row['cluster_id']: 'C-' + hmac.new(self.secret, row['mac_aliases'][0].encode(), sha256).hexdigest()[:10]
               for row in clustering['clusters']}
        tracks = {row['cluster_id']: row['state'] for row in presence['clusters']}
        locations = {row['cluster_id']: row for row in room['clusters']}
        events = defaultdict(list)
        for event in presence['events']:
            events[event['cluster_id']].append({key: event[key] for key in ('t_s', 'from_state', 'to_state', 'reason')})

        rows = []
        for row in clustering['clusters']:
            cid = row['cluster_id']
            aliases = row['mac_aliases']
            location = locations.get(cid, {})
            fingerprint = {item['signature'] for item in row['fingerprint_profile'].values() if item}
            channels = defaultdict(list)
            for stats in row['rssi_statistics'].values():
                for channel, sample in stats.items():
                    channels[channel].append(sample)
            rssi = [dict(channel=channel, median_dbm=median(sample['median_dbm'] for sample in samples),
                         max_spread_db=max(sample['spread_db'] for sample in samples),
                         probes=sum(sample['probes'] for sample in samples))
                    for channel, samples in sorted(channels.items())]
            association = [dict(alias_number=index, decision=entry['decision'], reason=entry['reason'],
                                heuristic_score=entry['heuristic_score'],
                                candidates=[dict(cluster_id=ids[cand['candidate_cluster_id']], decision=cand['decision'],
                                                 heuristic_score=cand['heuristic_score'],
                                                 pair_reasons=sorted({pair['reason'] for pair in cand['pairs']}))
                                            for cand in entry['candidates'][:10]])
                           for index, entry in enumerate(row['association_history'][-12:], max(1, len(aliases)-11))]
            rows.append(dict(cluster_id=ids[cid], mac_alias_count=len(aliases), fingerprint_summary=sorted(fingerprint)[:3],
                             first_seen_s=row['first_seen_s'], last_seen_s=row['last_seen_s'], rssi_statistics=rssi,
                             heuristic_score=row['confidence']['score'], presence_state=tracks.get(cid),
                             location_state=location.get('location'), location_reason=location.get('reason'),
                             association_history=association, state_history=events[cid][-12:]))
        return rows
