import asyncio,json
from pathlib import Path
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from serial.tools import list_ports
from research.detectors import ProbeConfig
from research.evaluate import evaluate
from scripts.probe_fixture import generate

router=APIRouter(prefix='/api/probe',tags=['Probe research'])
probe=None;config_path=None

def configure(p,config):
    global probe,config_path
    probe=p;config_path=Path(config)

class Connection(BaseModel):
    port:str=Field(min_length=1,max_length=128)
    baud:int=Field(default=460800,ge=9600,le=3000000)
class Experiment(BaseModel):
    device_count:int=Field(ge=0,le=200)
    people_count:int|None=Field(default=None,ge=0,le=200)
    notes:str=Field(default='',max_length=2000)
    layout:str=Field(min_length=1,max_length=1000)
    devices:str=Field(min_length=1,max_length=2000)
class Truth(BaseModel):
    device_count:int=Field(ge=0,le=200)
    people_count:int|None=Field(default=None,ge=0,le=200)
    notes:str=Field(default='',max_length=2000)
class Replay(BaseModel):
    name:str
    speed:float=Field(default=1,ge=.25,le=100)

def session_path(sid):
    p=(probe.store.root/'experiments'/sid).resolve()
    if p.parent!=(probe.store.root/'experiments').resolve() or not (p/'metadata.json').is_file():
        raise HTTPException(400,'Phiên không hợp lệ')
    return p

@router.get('/state')
async def state():return probe.snapshot()
@router.get('/dashboard')
async def dashboard():return await probe.dashboard_snapshot()
@router.get('/config')
async def config():return probe.probe_cfg.model_dump()
@router.put('/config')
async def setconfig(cfg:ProbeConfig):
    if probe.mode!='idle' or probe.session:raise HTTPException(409,'Ngắt sniffer và kết thúc phiên trước khi sửa')
    config_path.write_text(cfg.model_dump_json(indent=2));probe.probe_cfg=cfg;probe.reset_stream();return cfg.model_dump()
@router.post('/connect')
async def connect(c:Connection):
    if c.port not in [p.device for p in list_ports.comports()]:raise HTTPException(400,'Cổng không tồn tại')
    async with probe.control:
        if probe.session:raise HTTPException(409,'Kết thúc phiên trước khi đổi nguồn')
        await probe.connect(c.port,c.baud)
    return {'ok':True}

class RssiFilter(BaseModel):
    rssi_min:int=Field(ge=-127,le=0,strict=True)
    split_session:bool=False

@router.put('/rssi')
async def set_rssi(choice:RssiFilter):
    async with probe.control:
        if probe.mode not in ('idle','serial'):
            raise HTTPException(409,'Ngắt phát lại trước khi đổi bộ lọc RSSI.')
        cfg=probe.probe_cfg.model_copy(update={'rssi_min':choice.rssi_min})
        if cfg.rssi_min==probe.probe_cfg.rssi_min:
            return dict(config=cfg.model_dump(),session=probe.session,previous_session=None)
        meta=None
        if probe.session:
            if not choice.split_session:
                raise HTTPException(409,'Đang ghi phiên. Chọn lưu phiên hiện tại và tiếp tục phiên mới để đổi RSSI.')
            if not probe.snapshot()['valid']:
                raise HTTPException(409,'Chờ heartbeat hợp lệ trước khi tách phiên và đổi RSSI.')
            meta={k:probe.session[k] for k in ('devices','layout','notes')}
            truth=probe.current_truth or probe.session
            meta.update(device_count=truth['device_count'],people_count=truth.get('people_count'))
        # Persist before touching a running session; a failed write leaves collection intact.
        config_path.write_text(cfg.model_dump_json(indent=2))
        previous=probe.stop_session() if meta is not None else None
        probe.apply_rssi(cfg)
        if meta is not None:
            # stop_session invalidates inference, but the same connected radio is still healthy.
            probe.stream.feed(probe.status,probe.alg_now())
            probe.start_session(meta)
        return dict(config=cfg.model_dump(),session=probe.session,previous_session=previous)
@router.post('/disconnect')
async def disconnect():
    async with probe.control:await probe.stop()
    return {'ok':True}
@router.get('/sessions')
async def sessions():
    return [json.loads(p.read_text()) for p in sorted((probe.store.root/'experiments').glob('*/metadata.json'),reverse=True)]
@router.post('/sessions/start')
async def start(m:Experiment):
    try:return probe.start_session(m.model_dump())
    except ValueError as e:raise HTTPException(409,str(e))
@router.post('/sessions/stop')
async def stop():
    try:return probe.stop_session()
    except ValueError as e:raise HTTPException(409,str(e))
@router.post('/truth')
async def truth(m:Truth):
    try:return probe.add_truth(**m.model_dump())
    except ValueError as e:raise HTTPException(409,str(e))
@router.post('/sessions/{sid}/evaluate')
async def run_eval(sid:str):
    p=session_path(sid);meta=json.loads((p/'metadata.json').read_text())
    if not meta.get('ended_at'):raise HTTPException(409,'Kết thúc phiên trước khi đánh giá')
    try:return await asyncio.to_thread(evaluate,p)
    except (ValueError,OSError) as e:raise HTTPException(400,str(e))
@router.get('/replays')
async def replays():
    rows=[dict(name='synthetic-probe-demo',synthetic=True)]
    rows += [dict(name=m['id'],synthetic=bool(m.get('synthetic'))) for m in await sessions() if m.get('ended_at')]
    return rows
@router.post('/replay')
async def replay(r:Replay):
    async with probe.control:
        if probe.session:raise HTTPException(409,'Kết thúc phiên trước khi replay')
        demo=r.name=='synthetic-probe-demo'
        folder=probe.store.root/'synthetic-probe-demo' if demo else session_path(r.name)
        raw=folder/'raw.jsonl'
        metadata=folder/'metadata.json'
        try:
            if demo and not (raw.is_file() and metadata.is_file()):
                generate(folder)
            meta=json.loads(metadata.read_text())
            if not isinstance(meta,dict):raise ValueError('Invalid replay metadata')
            if not meta.get('ended_at'):raise HTTPException(409,'Phiên chưa hoàn tất')
            cfg=ProbeConfig.model_validate(meta.get('config'))
        except (ValueError,OSError) as e:
            raise HTTPException(400,'Không đọc được cấu hình nguồn phát lại') from e
        if not raw.is_file():raise HTTPException(404,'Thiếu file raw.jsonl của phiên')
        await probe.replay(raw,r.speed,demo or bool(meta.get('synthetic')),cfg,meta.get('dashboard_setup_id'))
    return {'ok':True}

@router.get('/sessions/{sid}/files/{kind}')
async def download(sid:str,kind:str):
    from fastapi.responses import FileResponse
    files={'report':'evaluation/report.json','timeline':'evaluation/timeline.csv','raw':'raw.jsonl','truth':'truth.jsonl','metadata':'metadata.json','heatmap':'inspection/probe-heatmap.svg','slots':'inspection/probe-slots.csv','inspection':'inspection/summary.json','events':'evaluation/algorithm-events.jsonl','live-events':'algorithm-events.jsonl','markers':'markers.jsonl','diagnosis':'diagnosis/report.json','probe-trace':'diagnosis/probe-trace.csv'}
    if kind not in files:raise HTTPException(400,'Loại file không hợp lệ')
    p=session_path(sid);meta=json.loads((p/'metadata.json').read_text())
    if not meta.get('ended_at'):raise HTTPException(409,'Kết thúc phiên trước khi xuất')
    target=p/files[kind]
    if not target.is_file():raise HTTPException(404,'Chưa có file; chạy đánh giá nếu cần')
    return FileResponse(target,filename=f'{sid}-{target.name}')

@router.post('/sessions/{sid}/inspect')
async def inspect(sid:str):
    from research.inspect import inspect_session
    p=session_path(sid);meta=json.loads((p/'metadata.json').read_text())
    if not meta.get('ended_at'):raise HTTPException(409,'Kết thúc phiên trước khi phân tích')
    return await asyncio.to_thread(inspect_session,p)

@router.get('/diagnostics')
async def diagnostics(mac:str):
    from backend.app.protocol import mac_valid
    if not mac_valid(mac):raise HTTPException(422,'Nhập đủ MAC dạng aa:bb:cc:dd:ee:ff')
    result=probe.diagnostics(mac.lower());result['source_valid']=probe.snapshot()['valid'];return result

class Marker(BaseModel):
    kind: str = Field(pattern=r'^(ap_disconnect|ap_connect|scan_requested|screen_lock|screen_unlock|note)$')
    mac: str | None = None
    notes: str = Field(default='',max_length=1000)

@router.post('/markers')
async def marker(m:Marker):
    from backend.app.protocol import mac_valid
    if m.mac is not None and not mac_valid(m.mac):raise HTTPException(422,'MAC không hợp lệ')
    try:return probe.marker(m.kind,m.mac.lower() if m.mac else None,m.notes)
    except ValueError as e:raise HTTPException(409,str(e))

class DiagnosticChoice(BaseModel):mac:str

@router.post('/sessions/{sid}/diagnose')
async def diagnose_session(sid:str,choice:DiagnosticChoice):
    from research.diagnose import diagnose
    p=session_path(sid);meta=json.loads((p/'metadata.json').read_text())
    if not meta.get('ended_at'):raise HTTPException(409,'Kết thúc phiên trước khi phân tích')
    try:return await asyncio.to_thread(diagnose,p,choice.mac)
    except ValueError as e:raise HTTPException(422,str(e))
