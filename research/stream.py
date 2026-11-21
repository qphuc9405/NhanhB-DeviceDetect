"""Shared causal quality/clock handling for live collection and offline evaluation."""
from collections import OrderedDict, deque, defaultdict
from dataclasses import dataclass, field
from itertools import islice
from math import isfinite
from research.detectors import Comparison,ALGORITHM_VERSION
from research.ie_profile import fingerprint


class RecentProbeRecords:
    """Bounded record identity cache, independent of the active MAC table."""

    def __init__(self, limit=4096):
        self.limit = limit
        self.records = OrderedDict()

    def remember(self, packet):
        key = (packet['source_mac'].lower(), packet['boot_id'], packet['seq'],
               packet['ts_us'], packet['channel'], packet['rssi'], packet['frame_seq'],
               packet.get('retry', False), packet.get('ie', ''))
        if key in self.records:
            return False
        self.records[key] = None
        if len(self.records) > self.limit:
            self.records.popitem(last=False)
        return True

    def mac_count(self):
        return len({record[0] for record in self.records})


@dataclass
class MacObservation:
    mac: str
    first_seen_s: float
    last_seen_s: float
    probe_count: int = 0
    fingerprint_id: str | None = None
    accepted: int = 0
    filtered: dict = field(default_factory=lambda: defaultdict(int))
    channels: set = field(default_factory=set)
    recent: deque = field(default_factory=lambda: deque(maxlen=16))

    def observe(self, packet, t, reason):
        self.last_seen_s = t
        self.probe_count += 1
        self.channels.add(packet['channel'])
        self.fingerprint_id = fingerprint(packet.get('ie', '')) or self.fingerprint_id
        if reason == 'accepted':
            self.accepted += 1
        else:
            self.filtered[reason] += 1
        self.recent.append(dict(t_s=t, ts_us=packet['ts_us'], channel=packet['channel'],
                                rssi=packet['rssi'], frame_seq=packet['frame_seq'],
                                retry=packet.get('retry', False), reason=reason))

    def summary(self, t):
        latest = self.recent[-1]
        return dict(mac=self.mac, first_seen_s=self.first_seen_s, last_seen_s=self.last_seen_s,
                    age_s=t-self.last_seen_s, channel=latest['channel'], rssi_last=latest['rssi'],
                    rssi=latest['rssi'], rssi_history=[sample['rssi'] for sample in self.recent],
                    probe_count=self.probe_count, fingerprint_id=self.fingerprint_id,
                    last_reason=latest['reason'])

class Stream:
    def __init__(self,cfg):
        self.cfg=cfg;self.engine=Comparison(cfg);self.boot=None;self.heartbeat=None;self.status=None;self.last=0.
        self.events=deque(maxlen=512);self.event_seq=0
        self.audit=OrderedDict();self.audit_capacity_drops=0;self.audit_expired=0
        self.probe_records = RecentProbeRecords()
        self.duplicate_records = 0
        self.channel=None;self.channel_seconds=defaultdict(float);self.last_drop=0;self.drop_increase=0
    def event(self,kind,t,**values):
        self.event_seq+=1;self.events.append(dict(event_seq=self.event_seq,kind=kind,t_s=t,**values))
    def flush_events(self):
        while self.engine.sherlock.events:
            ev=self.engine.sherlock.events.popleft();kind=ev.pop('kind');t=ev.pop('t_s');self.event(kind,t,**ev)
    def valid(self,t):return self.heartbeat is not None and 0<=t-self.heartbeat<=self.cfg.heartbeat_s
    def advance(self,t):
        if not isfinite(t) or t<self.last:raise ValueError('invalid stream clock')
        # Entries are ordered by the time of their latest raw Probe.
        while self.audit:
            oldest = next(iter(self.audit.values()))
            if t - oldest.last_seen_s <= self.cfg.mac_expiry_s:
                break
            self.audit.popitem(last=False)
            self.audit_expired += 1
        if self.channel is not None and self.heartbeat is not None:
            end=min(t,self.heartbeat+self.cfg.heartbeat_s)
            self.channel_seconds[self.channel]+=max(0,end-self.last)
        if self.valid(t):self.engine.advance(t);self.flush_events()
        self.last=t
    def reset_inference(self,t,reason):
        self.engine=Comparison(self.cfg);self.heartbeat=None;self.event('inference_reset',t,reason=reason)
    def feed(self,p,t):
        self.advance(t)
        if p['type']=='control':
            self.reset_inference(t,p['kind']);return
        if p['type']=='probe' and not self.probe_records.remember(p):
            self.duplicate_records += 1
            return 'duplicate_record'
        boot=p['boot_id']
        if self.boot is not None and boot!=self.boot:self.reset_inference(t,'board_reboot')
        self.boot=boot
        if p['type']=='status':
            if self.heartbeat is not None and not self.valid(t):self.reset_inference(t,'heartbeat_gap')
            if not p['capture_active'] or not p['sniffer_enabled']:self.reset_inference(t,'radio_inactive')
            else:self.heartbeat=t
            self.status=p;self.channel=p['channel'];self.engine.excluded.add(p['own_mac'])
            dropped=p['probe_dropped']
            if dropped>self.last_drop:
                self.drop_increase+=dropped-self.last_drop;self.event('queue_drop',t,increase=dropped-self.last_drop)
            self.last_drop=dropped
        elif p['type']=='channel':self.channel=p['channel']
        elif p['type']=='probe':
            reason=self.engine.observe(p,t) if self.valid(t) else 'no_valid_heartbeat'
            self.flush_events()
            m = p['source_mac'].lower()
            row = self.audit.get(m)
            if row is None:
                if len(self.audit) >= self.cfg.max_sources:
                    self.audit_capacity_drops += 1
                    return 'audit_capacity'
                self.audit[m] = row = MacObservation(m, t, t)
            row.observe(p, t, reason)
            self.audit.move_to_end(m)
            return reason
    def snapshot(self,t):
        self.advance(t);result=self.engine.snapshot(t) if self.valid(t) else None;self.flush_events()
        recent_sources = [row.summary(t) for row in islice(reversed(self.audit.values()), 50)]
        return dict(algorithm_version=ALGORITHM_VERSION,valid=self.valid(t),result=result,
                    raw_mac_count=self.probe_records.mac_count(),active_mac_count=len(self.audit),
                    expired_mac_count=self.audit_expired,
                    heartbeat_age_s=None if self.heartbeat is None else max(0,t-self.heartbeat),
                    events=list(self.events),recent_sources=recent_sources,channel_observation_s={str(k):round(v,3) for k,v in self.channel_seconds.items()},
                    quality=dict(queue_drop_increase=self.drop_increase,audit_capacity_drops=self.audit_capacity_drops,
                                 audit_expired=self.audit_expired,duplicate_probe_records=self.duplicate_records),
                    coverage_semantics='Heartbeat-inferred tuned time; not proof that every transmitted probe was received')
    def diagnostics(self,mac,t):
        self.advance(t);m=mac.lower();a=self.audit.get(m)
        if a is None:return dict(mac=m,observed=False,reason='Chưa có Probe từ MAC này trong bộ đệm hiện tại; không chứng minh thiết bị vắng mặt')
        return dict(**a.summary(t),observed=True,received=a.probe_count,accepted=a.accepted,
                    filtered=dict(a.filtered),channels=sorted(a.channels),recent=list(a.recent),
                    locally_administered=bool(int(m[:2],16)&2),identity_note='Bit U/L không chứng minh MAC ngẫu nhiên; không ghép MAC khác thành cùng thiết bị')
