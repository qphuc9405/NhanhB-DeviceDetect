"""One serial owner, independent of HTTP/UI cadence. Bounded line buffering."""
import asyncio,json,time,uuid,os
import serial
from backend.app.storage import Store,utc
from backend.app.protocol import parse_line
from research.dashboard import DashboardBuffer, DashboardConfig
from research.detectors import ALGORITHM_VERSION,Comparison
from research.stream import Stream

class ProbeService:
    def __init__(self,root,cfg,dashboard_config=None):
        self.store=Store(root);self.probe_cfg=cfg;self.control=asyncio.Lock()
        self.dashboard_config = dashboard_config or DashboardConfig()
        self.serial=None;self.task=None;self.mode='idle';self.connection='disconnected'
        self.error=None;self.serial_args=None;self.session=None;self.raw=None;self.truth=None;self.current_truth=None
        self.origin=None;self.replay_file=None;self.event_file=None;self.journal_seq=0
        self.counters=dict(valid=0,invalid=0,bytes=0,reconnects=0)
        self.reset_stream()
    def reset_stream(self):
        self.stream=Stream(self.probe_cfg);self.clock=time.monotonic()
        self.dashboard = DashboardBuffer(self.dashboard_config)
        self.timeline_origin=self.origin if self.session else self.clock
        self.status=None;self.probe_history=[];self.channels=[];self.journal_seq=0
    def apply_rssi(self,cfg):
        """Keep the radio/heartbeat and raw audit, restart inference under one threshold."""
        old=self.probe_cfg.rssi_min
        self.stream.advance(self.alg_now())
        self.probe_cfg=cfg;self.stream.cfg=cfg;self.stream.engine=Comparison(cfg)
        if self.status:self.stream.engine.excluded.add(self.status['own_mac'])
        self.probe_history=[]
        self.stream.event('rssi_filter_changed',self.alg_now(),previous_rssi_min=old,rssi_min=cfg.rssi_min)
        self.dashboard = DashboardBuffer(self.dashboard_config)
        t = self.alg_now()
        if self.status and self.stream.valid(t):
            self.dashboard.add(self.stream.heartbeat, self.status)
    @property
    def engine(self):return self.stream.engine
    def now(self):return self.clock if self.mode in ('replay','synthetic') else time.monotonic()
    def alg_now(self):
        now=self.now();return now-self.timeline_origin if self.mode=='serial' else now
    def _journal(self):
        for ev in self.stream.events:
            if ev['event_seq']<=self.journal_seq:continue
            if self.event_file:self.event_file.write(json.dumps(ev,ensure_ascii=False)+'\n')
            self.journal_seq=ev['event_seq']
    def control_event(self,kind):
        now=self.now();t=now-self.timeline_origin if self.mode=='serial' else now
        packet = dict(type='control',kind=kind)
        self.dashboard.add(t, packet)
        self.stream.feed(packet,t)
        if self.raw:
            self.raw.write(json.dumps(dict(control=dict(kind=kind),host_elapsed_s=now-self.origin,host_time=utc(),source='serial'))+'\n')
        self._journal()
    def ingest(self,line,now=None):
        now=time.monotonic() if now is None else now;self.counters['bytes']+=len(line)
        try:p=parse_line(line)
        except ValueError:self.counters['invalid']+=1;return
        self.counters['valid']+=1;self.clock=now
        t=now-self.timeline_origin if self.mode=='serial' else now
        if self.raw:
            self.raw.write(json.dumps(dict(packet=p,host_time=utc(),host_elapsed_s=now-self.origin,source='serial'))+'\n')
            self.session['records']+=1
        self.dashboard.add(t, p)
        self.stream.feed(p,t);self._journal()
        if p['type']=='status':self.status=p
        if p['type'] in ('status','channel'):
            self.channels.append(dict(t=t,channel=p['channel']));self.channels=self.channels[-100:]
    def snapshot(self):
        t=self.alg_now();state=self.stream.snapshot(t);self._journal()
        valid=self.connection=='connected' and state['valid'];result=state['result'] if valid else None
        if result and (not self.probe_history or t-self.probe_history[-1]['t']>=1):
            self.probe_history.append(dict(t=t,unique=result['unique_count'],timeout=result['timeout_count'],sherlock=result['sherlock']['count']))
            self.probe_history=self.probe_history[-180:]
        return dict(mode=self.mode,connection=self.connection,error=self.error,valid=valid,heartbeat_age_s=state['heartbeat_age_s'],
                    dashboard_source_id=self.dashboard.source_id,
                    result=result,firmware=self.status,counters=self.counters.copy(),history=self.probe_history,
                    config=self.stream.cfg.model_dump(),session=self.session,current_truth=self.current_truth,channels=self.channels[-20:],
                    algorithm_version=ALGORITHM_VERSION,events=state['events'],quality=state['quality'],recent_sources=state['recent_sources'],
                    raw_mac_count=state['raw_mac_count'],active_mac_count=state['active_mac_count'],expired_mac_count=state['expired_mac_count'],
                    channel_observation_s=state['channel_observation_s'],
                    semantics='Số nguồn MAC duy trì xác nhận quan sát; không kết luận thiết bị đã rời')
    async def dashboard_snapshot(self):
        while True:
            dashboard = self.dashboard
            t = self.alg_now()
            cfg = self.stream.cfg
            state = dict(mode=self.mode, connection=self.connection,
                         valid=self.connection == 'connected' and self.stream.valid(t),
                         config=cfg.model_dump(), raw_mac_count=self.stream.probe_records.mac_count(),
                         active_mac_count=sum(t - row.last_seen_s <= cfg.mac_expiry_s for row in self.stream.audit.values()))
            report = await dashboard.snapshot(dashboard.capture(t, state))
            if dashboard is self.dashboard and self.connection == state['connection']:
                return report
    def diagnostics(self,mac):
        result=self.stream.diagnostics(mac,self.alg_now());self._journal();return result
    def marker(self,kind,mac=None,notes=''):
        if not self.session or self.mode!='serial':raise ValueError('Bắt đầu phiên serial trước khi đánh dấu')
        row=dict(t_s=time.monotonic()-self.origin,kind=kind,mac=mac,notes=notes,host_time=utc())
        with (self.folder/'markers.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        self.store.event('experiment_marker',row);return row
    async def connect(self,port,baud):
        await self.stop();self.mode='serial';self.serial_args=(port,baud);self.connection='connecting';self.error=None
        self.task=asyncio.create_task(self.serial_loop())
    async def serial_loop(self):
        port,baud=self.serial_args;fragment=b''
        try:
            while True:
                try:
                    if self.serial is None:
                        self.serial=serial.Serial(port,baud,timeout=.1,write_timeout=.5,exclusive=True if os.name!='nt' else None)
                        self.connection='connected';self.error=None;self.control_event('serial_connected');fragment=b''
                    chunk=await asyncio.to_thread(self.serial.read,4096);fragment+=chunk
                    while b'\n' in fragment:
                        line,fragment=fragment.split(b'\n',1)
                        if line:self.ingest(line)
                    if len(fragment)>16000:fragment=b'';self.counters['invalid']+=1
                except (serial.SerialException,OSError,ValueError) as e:
                    self.error=str(e);self.connection='reconnecting';self.control_event('serial_disconnected')
                    self.counters['reconnects']+=1
                    if self.serial:self.serial.close();self.serial=None
                    await asyncio.sleep(1)
        finally:
            if self.serial:self.serial.close();self.serial=None
    async def stop(self):
        if self.serial:
            try:self.serial.cancel_read()
            except (AttributeError,OSError):pass
        if self.task:
            self.task.cancel()
            try:await self.task
            except asyncio.CancelledError:pass
            self.task=None
        if self.serial:self.serial.close();self.serial=None
        if self.session:self.stop_session()
        self.connection='disconnected';self.mode='idle';self.reset_stream()
    async def replay(self,path,speed,synthetic,cfg,setup_id=None):
        await self.stop();self.mode='synthetic' if synthetic else 'replay';self.connection='connected';self.error=None
        self.stream=Stream(cfg);self.clock=0.
        self.dashboard.setup_id = None if synthetic else setup_id
        self.replay_file=str(path);self.task=asyncio.create_task(self.replay_loop(path,speed))
    async def replay_loop(self,path,speed):
        from research.evaluate import load_records
        prev=0.
        try:
            for t,p in load_records(path):
                # A UI poll may otherwise skip empty slots in a silent replay interval.
                gap=max(0,t-prev)
                while gap>1:
                    await asyncio.sleep(1/speed);prev+=1;gap-=1;self.clock=prev
                await asyncio.sleep(gap/speed);prev=t
                if p['type']=='control':
                    self.clock=t;self.dashboard.add(t,p);self.stream.feed(p,t);self._journal()
                else:self.ingest(json.dumps(p),t)
            self.connection='finished'
        except asyncio.CancelledError:raise
        except Exception as e:self.error=str(e);self.connection='error'
    def start_session(self,meta):
        if self.mode!='serial' or not self.snapshot()['valid']:raise ValueError('Cần sniffer serial và heartbeat hợp lệ')
        if self.session:raise ValueError('Đang có phiên thu')
        self.origin=time.monotonic();self.timeline_origin=self.origin;self.probe_history=[]
        self.stream=Stream(self.probe_cfg);self.journal_seq=0
        self.dashboard = DashboardBuffer(self.dashboard_config)
        if self.status:
            self.stream.feed(self.status,0.)
            self.dashboard.add(0.,self.status)
        sid=uuid.uuid4().hex;self.folder=self.store.root/'experiments'/sid;self.folder.mkdir(parents=True)
        self.session=dict(id=sid,started_at=utc(),ended_at=None,records=0,synthetic=False,algorithm_version=ALGORITHM_VERSION,config=self.probe_cfg.model_dump(),firmware=self.status,**meta)
        if self.dashboard.setup_id is not None:
            self.session['dashboard_setup_id'] = self.dashboard.setup_id
        self.event_file=(self.folder/'algorithm-events.jsonl').open('w',buffering=1)
        self.raw=(self.folder/'raw.jsonl').open('w',buffering=1);self.truth=(self.folder/'truth.jsonl').open('w',buffering=1)
        self.current_truth=dict(t_s=0.,host_time=utc(),device_count=meta['device_count'],people_count=meta.get('people_count'),notes=meta.get('notes',''))
        self.truth.write(json.dumps(self.current_truth,ensure_ascii=False)+'\n')
        if self.status:
            self.raw.write(json.dumps(dict(packet=self.status,host_elapsed_s=0,host_time=utc(),source='serial'))+'\n');self.session['records']+=1
        self._save_meta();return self.session
    def _save_meta(self):
        (self.folder/'metadata.json').write_text(json.dumps(self.session,ensure_ascii=False,indent=2));self.store.save(self.session)
    def add_truth(self,device_count,people_count=None,notes=''):
        if not self.truth:raise ValueError('Chưa bắt đầu phiên')
        row=dict(t_s=time.monotonic()-self.origin,host_time=utc(),device_count=device_count,people_count=people_count,notes=notes)
        self.truth.write(json.dumps(row,ensure_ascii=False)+'\n');self.store.event('ground_truth',row);self.current_truth=row;return row
    def stop_session(self):
        if not self.session:raise ValueError('Không có phiên')
        # Host control record, not a fabricated board heartbeat.
        self.control_event('session_stopped')
        self.raw.close();self.truth.close();self.event_file.close();self.raw=None;self.truth=None;self.event_file=None
        self.session['ended_at']=utc();self.session['duration_s']=time.monotonic()-self.origin
        self._save_meta();out=self.session;self.session=None;self.origin=None;self.current_truth=None;return out
