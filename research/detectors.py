"""Causal slot inference. First positive/empty slot counts, as in upstream PHP.
No MAC de-randomization, no retrospective relabelling of real-time counts.
"""
from dataclasses import dataclass
from collections import deque
import math
from pydantic import BaseModel, Field, model_validator

ALGORITHM_VERSION = 'sherlock-repo-slots-v2'

class ProbeConfig(BaseModel):
    slot_s: float = Field(default=60, ge=1, le=300)
    arrival_slots: int = Field(default=6, ge=1, le=30)
    withdrawal_slots: int = Field(default=2, ge=1, le=30)
    departure_slots: int = Field(default=6, ge=1, le=30)
    rssi_min: int = Field(default=-127, ge=-127, le=0)
    unique_window_s: float = Field(default=60, ge=1, le=3600)
    timeout_s: float = Field(default=120, ge=1, le=3600)
    confirm_window_s: float = Field(default=30, ge=1, le=3600)
    confirm_hits: int = Field(default=2, ge=1, le=100)
    heartbeat_s: float = Field(default=5, ge=2, le=60)
    max_sources: int = Field(default=2000, ge=1, le=20000)
    mac_expiry_s: float = Field(default=120, ge=1, le=3600)
    excluded_macs: list[str] = Field(default_factory=list)
    @model_validator(mode='after')
    def check(self):
        from backend.app.protocol import mac_valid
        if self.confirm_window_s > self.timeout_s: raise ValueError('confirm window exceeds timeout')
        if any(not mac_valid(m) for m in self.excluded_macs): raise ValueError('invalid excluded MAC')
        self.excluded_macs=[m.lower() for m in self.excluded_macs]
        return self

@dataclass
class Track:
    state: str = 'candidate'
    positive: int = 0
    missing: int = 0
    departure_missing: int = 0
    first_seen: float = 0
    last_seen: float = 0
    rssi: int = -127
    confirmed_at: float | None = None
    suspect_at: float | None = None

class Sherlock:
    def __init__(self,cfg):
        self.cfg=cfg;self.tracks={};self.slot=None;self.seen={};self.rejected_capacity=0;self.events=deque(maxlen=512)
    def event(self,kind,mac,row,when):
        self.events.append(dict(kind=kind,mac=mac,t_s=when,first_seen_s=row.first_seen,
                                confirmed_at_s=row.confirmed_at,suspect_at_s=row.suspect_at))
    def _close(self):
        end=(self.slot+1)*self.cfg.slot_s
        for mac in sorted(set(self.tracks)|set(self.seen)):
            hit=self.seen.get(mac);row=self.tracks.get(mac)
            if row is None:
                if hit is None:continue
                if len(self.tracks)>=self.cfg.max_sources:self.rejected_capacity+=1;continue
                row=self.tracks[mac]=Track(first_seen=hit[0],last_seen=hit[0],rssi=hit[1])
                self.event('candidate_started',mac,row,end)
            if hit is not None:row.last_seen,row.rssi=hit
            if row.state=='candidate':
                if hit is not None:
                    row.positive+=1;row.missing=0
                    if row.positive>=self.cfg.arrival_slots:
                        row.state='present';row.confirmed_at=end;self.event('source_confirmed',mac,row,end)
                else:
                    row.missing+=1
                    if row.missing>=self.cfg.withdrawal_slots:
                        self.event('candidate_cancelled_no_observation',mac,row,end);del self.tracks[mac]
            elif hit is not None:
                if row.state=='departing':self.event('source_observed_again',mac,row,end)
                row.state='present';row.departure_missing=0;row.suspect_at=None
            else:
                if row.state=='present':
                    row.state='departing';row.suspect_at=self.slot*self.cfg.slot_s
                    self.event('observation_gap_started',mac,row,end)
                row.departure_missing+=1
                if row.departure_missing>=self.cfg.departure_slots:
                    self.event('source_expired_no_observation',mac,row,end);del self.tracks[mac]
        self.seen.clear()
    def advance(self,t):
        if not math.isfinite(t) or t<0:raise ValueError('invalid clock')
        target=math.floor(t/self.cfg.slot_s)
        if self.slot is None:self.slot=target
        if target<self.slot:raise ValueError('nonmonotonic algorithm clock')
        while self.slot<target:
            self._close();self.slot+=1
            if not self.tracks and not self.seen:self.slot=target
    def observe(self,p,t):
        self.advance(t);mac=p['source_mac']
        if mac not in self.seen and len(self.seen)>=self.cfg.max_sources:self.rejected_capacity+=1;return
        self.seen[mac]=(t,p['rssi'])
    def snapshot(self,t):
        self.advance(t);rows=[]
        for m,r in self.tracks.items():
            seen,rssi=self.seen.get(m,(r.last_seen,r.rssi))
            rows.append(dict(mac=m,state=r.state,rssi=rssi,age_s=max(0,t-seen),positive_slots=r.positive,
                missing_slots=r.missing,departure_slots=r.departure_missing,first_seen_s=r.first_seen,
                confirmed_at_s=r.confirmed_at,suspect_at_s=r.suspect_at))
        return dict(count=sum(r.state in ('present','departing') for r in self.tracks.values()),
                    sources=sorted(rows,key=lambda r:r['age_s']),capacity_drops=self.rejected_capacity,
                    n_sources_seen=len(self.seen))

class Comparison:
    def __init__(self,cfg):
        self.cfg=cfg;self.sherlock=Sherlock(cfg);self.rows={};self.excluded=set(cfg.excluded_macs)
        self.last=-1.;self.accepted=0;self.duplicates=0;self.capacity_drops=0;self.filter_counts=dict(excluded=0,weak_rssi=0)
    def advance(self,t):
        if not math.isfinite(t) or t<self.last:raise ValueError('clock rollback')
        self.last=t;self.sherlock.advance(t)
        expiry=max(self.cfg.timeout_s,self.cfg.unique_window_s,self.cfg.confirm_window_s)
        for m in list(self.rows):
            if t-self.rows[m]['last']>expiry:del self.rows[m]
    def observe(self,p,t):
        self.advance(t);m=p['source_mac'].lower()
        if m in self.excluded:self.filter_counts['excluded']+=1;return 'excluded'
        if p['rssi']<self.cfg.rssi_min:self.filter_counts['weak_rssi']+=1;return 'weak_rssi'
        r=self.rows.get(m)
        if r is None:
            if len(self.rows)>=self.cfg.max_sources:self.capacity_drops+=1;return 'capacity'
            r=self.rows[m]=dict(last=t,rssi=p['rssi'],hits=deque(maxlen=self.cfg.confirm_hits),confirmed=False,key=None,key_t=-1.)
        key=(p['channel'],p['frame_seq'])
        if p.get('retry',False) and r['key']==key and t-r['key_t']<.1:self.duplicates+=1;return 'retry'
        if t-r['last']>self.cfg.timeout_s:r['confirmed']=False;r['hits'].clear()
        r.update(last=t,rssi=p['rssi'],key=key,key_t=t);r['hits'].append(t)
        while r['hits'] and t-r['hits'][0]>self.cfg.confirm_window_s:r['hits'].popleft()
        if len(r['hits'])>=self.cfg.confirm_hits:r['confirmed']=True
        self.accepted+=1;self.sherlock.observe({**p,'source_mac':m},t);return 'accepted'
    def snapshot(self,t):
        self.advance(t)
        return dict(unique_count=sum(t-r['last']<=self.cfg.unique_window_s for r in self.rows.values()),
                    timeout_count=sum(r['confirmed'] and t-r['last']<=self.cfg.timeout_s for r in self.rows.values()),
                    sherlock=self.sherlock.snapshot(t),accepted=self.accepted,duplicates=self.duplicates,
                    filter_counts=self.filter_counts.copy(),capacity_drops=self.capacity_drops)
