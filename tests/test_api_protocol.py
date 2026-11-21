import csv,json,time,asyncio,os,pty
from pathlib import Path
import pytest
from backend.app.protocol import parse_line
from backend.app import main
from scripts.probe_fixture import generate
from research.collector import ProbeService
from research.detectors import ProbeConfig
from research.evaluate import load_records

def probe():return dict(v=1,type='probe',node='sniffer',boot_id='test',ts_us=1,seq=1,source_mac='AA:BB:CC:DD:EE:FF',rssi=-50,channel=6,frame_seq=0)

def test_parser_normalizes_mac():assert parse_line(json.dumps(probe()))['source_mac']=='aa:bb:cc:dd:ee:ff'
@pytest.mark.parametrize('change',[{'node':'rx'},{'type':'csi'},{'rssi':-128},{'frame_seq':4096},{'channel':14},{'ts_us':1.2},{'source_mac':'garbage'},{'boot_id':' '}])
def test_parser_rejects_invalid(change):
    with pytest.raises(ValueError):parse_line(json.dumps({**probe(),**change}))
@pytest.mark.parametrize('line',['boot log','{','x'*16001])
def test_parser_rejects_logs(line):
    with pytest.raises(ValueError):parse_line(line)

def test_api_ready_and_unknown(client):
    assert client.get('/api/health').json()['scope']=='probe-only'
    r=client.get('/api/probe/state').json();assert r['result'] is None and not r['valid']
    assert client.get('/api/ports').status_code==200

def test_config_validations(client):
    assert client.put('/api/probe/config',json={'slot_s':0}).status_code==422
    assert client.put('/api/probe/config',json={'excluded_macs':['invalid']}).status_code==422
    assert client.put('/api/probe/config',json={'confirm_window_s':300,'timeout_s':10}).status_code==422
    cfg=client.get('/api/probe/config').json();cfg['slot_s']=5
    assert client.put('/api/probe/config',json=cfg).status_code==200
    assert client.get('/api/probe/config').json()['slot_s']==5

def test_api_guards(client):
    assert client.post('/api/probe/connect',json={'port':'/missing'}).status_code==400
    assert client.post('/api/probe/sessions/start',json={'device_count':1,'devices':'phone','layout':'room'}).status_code==409
    assert client.post('/api/probe/truth',json={'device_count':1}).status_code==409
    assert client.post('/api/probe/replay',json={'name':'../etc/passwd'}).status_code==400
    assert client.get('/api/probe/sessions/bad/files/raw').status_code==400

def test_replay_source_guard(client):
    config_path=Path(os.environ['WIFI_PROBE_CONFIG'])
    original=config_path.read_bytes()
    demo_dir=main.svc.store.root/'synthetic-probe-demo'
    assert not demo_dir.exists()
    assert client.post('/api/probe/replay',json={'name':'synthetic-probe-demo','speed':100}).status_code==200
    time.sleep(.1)
    r=client.get('/api/probe/state').json();assert r['mode']=='synthetic' and r['valid']
    assert r['config']['slot_s']==5
    assert (demo_dir/'raw.jsonl').is_file()
    assert client.get('/api/probe/sessions').json()==[]
    assert client.put('/api/probe/config',json={'slot_s':5}).status_code==409
    assert client.post('/api/probe/disconnect').status_code==200
    state=client.get('/api/probe/state').json()
    assert state['result'] is None and state['config']==json.loads(original)
    assert config_path.read_bytes()==original

def test_saved_replay_uses_recorded_config_like_evaluation(client):
    folder=main.svc.store.root/'experiments'/'saved'
    generate(folder)
    metadata=folder/'metadata.json'
    meta=json.loads(metadata.read_text())
    meta.update(id='saved',synthetic=False)
    meta['config']['rssi_min']=-49
    metadata.write_text(json.dumps(meta))

    live_cfg=client.get('/api/probe/config').json()
    live_cfg['rssi_min']=-30
    assert client.put('/api/probe/config',json=live_cfg).status_code==200
    response=client.post('/api/probe/sessions/saved/evaluate')
    assert response.status_code==200
    report=response.json()
    assert report['config']==meta['config']
    timeline=client.get('/api/probe/sessions/saved/files/timeline')
    assert timeline.status_code==200
    expected_peak=max(int(row['sherlock']) for row in csv.DictReader(timeline.text.splitlines()) if row['sherlock'])
    assert client.post('/api/probe/replay',json={'name':'saved','speed':100}).status_code==200

    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        state=client.get('/api/probe/state').json()
        if state['connection'] in ('finished','error'):break
        time.sleep(.01)
    assert state['connection']=='finished' and state['mode']=='replay'
    assert state['config']==report['config']
    assert max(row['sherlock'] for row in state['history'])==expected_peak==1
    assert client.get('/api/probe/config').json()==live_cfg
    assert client.post('/api/probe/disconnect').status_code==200
    assert client.get('/api/probe/state').json()['config']==live_cfg

def test_real_style_session_api_evaluation_download(client,tmp_path):
    # Virtual transport injected into the service, never a physical-board accuracy claim.
    fixture=tmp_path/'fixture';generate(fixture)
    s=main.svc;s.mode='serial';s.connection='connected'
    status=list(load_records(fixture/'raw.jsonl'))[0][1]
    s.ingest(json.dumps(status))
    r=client.post('/api/probe/sessions/start',json={'device_count':1,'devices':'virtual test fixture','layout':'PTY test only'})
    assert r.status_code==200;sid=r.json()['id']
    assert client.post('/api/probe/replay',json={'name':'synthetic-probe-demo'}).status_code==409
    assert client.get(f'/api/probe/sessions/{sid}/files/raw').status_code==409
    assert client.post('/api/probe/truth',json={'device_count':0,'notes':'removed'}).status_code==200
    assert client.post('/api/probe/sessions/stop').status_code==200
    r=client.post(f'/api/probe/sessions/{sid}/evaluate');assert r.status_code==200 and r.json()['valid_rows']==1
    assert client.get(f'/api/probe/sessions/{sid}/files/report').status_code==200
    assert client.get(f'/api/probe/sessions/{sid}/files/timeline').status_code==200
    assert client.get(f'/api/probe/sessions/{sid}/files/unknown').status_code==400
    assert len(client.get('/api/probe/sessions').json())==1

def test_inactive_radio_is_not_valid(tmp_path):
    fixture=tmp_path/'fixture';generate(fixture);p=ProbeService(tmp_path/'runtime',ProbeConfig())
    status=list(load_records(fixture/'raw.jsonl'))[0][1]
    p.mode='synthetic';p.connection='connected';p.ingest(json.dumps({**status,'capture_active':False}),0)
    assert not p.snapshot()['valid'];p.store.close()

def test_reboot_clears_confirmation(tmp_path):
    fixture=tmp_path/'fixture';generate(fixture);p=ProbeService(tmp_path/'runtime',ProbeConfig(slot_s=1,arrival_slots=1))
    status=list(load_records(fixture/'raw.jsonl'))[0][1];p.mode='synthetic';p.connection='connected'
    q={**probe(),'boot_id':status['boot_id']}
    p.ingest(json.dumps(status),0);p.ingest(json.dumps(q),0);p.ingest(json.dumps(q),1)
    p.clock=2;assert p.snapshot()['result']['sherlock']['count']==1
    p.ingest(json.dumps({**status,'boot_id':'new'}),2.5)
    assert p.snapshot()['result']['sherlock']['count']==0;p.store.close()

def test_inspection_exports(client,tmp_path):
    fixture=main.svc.store.root/'experiments/demo';generate(fixture)
    assert client.post('/api/probe/sessions/synthetic-probe-demo/inspect').status_code==400
    # Registry key is folder name; metadata ID is informational.
    r=client.post('/api/probe/sessions/demo/inspect');assert r.status_code==200 and r.json()['synthetic']
    assert client.get('/api/probe/sessions/demo/files/heatmap').status_code==200
    assert client.get('/api/probe/sessions/demo/files/slots').status_code==200

def test_json_list_and_bad_lines_skipped(tmp_path):
    p=tmp_path/'bad.jsonl';p.write_text('[]\n{\n'+json.dumps(probe())+'\n')
    assert len(list(load_records(p)))==1

def test_no_radio_pause_holds_old_count(tmp_path):
    fixture=tmp_path/'fixture';generate(fixture);p=ProbeService(tmp_path/'runtime',ProbeConfig(slot_s=1,arrival_slots=1))
    status=list(load_records(fixture/'raw.jsonl'))[0][1];q={**probe(),'boot_id':status['boot_id']}
    p.mode='synthetic';p.connection='connected'
    p.ingest(json.dumps(status),0);p.ingest(json.dumps(q),0);p.ingest(json.dumps(q),1);p.clock=2
    assert p.snapshot()['result']['sherlock']['count']==1
    p.ingest(json.dumps({**status,'capture_active':False}),2)
    assert p.snapshot()['result'] is None
    p.ingest(json.dumps(status),3)
    assert p.snapshot()['result']['sherlock']['count']==0;p.store.close()


def live_source(client,tmp_path):
    fixture=tmp_path/'rssi-fixture';generate(fixture)
    service=main.svc
    service.mode='serial';service.connection='connected'
    status=next(load_records(fixture/'raw.jsonl'))[1]
    service.ingest(json.dumps(status))
    return service,status


def test_live_rssi_applies_to_inference_and_persists(client,tmp_path):
    service,status=live_source(client,tmp_path)
    original=service.probe_cfg.model_dump()
    service.ingest(json.dumps({**probe(),'boot_id':status['boot_id'],'rssi':-85}))
    assert service.engine.accepted==1
    response=client.put('/api/probe/rssi',json={'rssi_min':-65})
    assert response.status_code==200
    assert client.get('/api/probe/state').json()['valid']
    assert service.connection=='connected' and service.engine.accepted==0
    expected={**original,'rssi_min':-65}
    assert service.probe_cfg.model_dump()==expected
    assert json.loads(Path(os.environ['WIFI_PROBE_CONFIG']).read_text())==expected
    for rssi in [-66,-65,-45]:
        service.ingest(json.dumps({**probe(),'boot_id':status['boot_id'],'rssi':rssi}))
    assert service.engine.accepted==2
    assert service.engine.filter_counts['weak_rssi']==1
    assert service.stream.events[-1]['kind']=='rssi_filter_changed'
    assert client.put('/api/probe/rssi',json={'rssi_min':-127}).status_code==200
    service.ingest(json.dumps({**probe(),'boot_id':status['boot_id'],'rssi':-100}))
    assert service.engine.accepted==1 and service.engine.filter_counts['weak_rssi']==0


def test_rssi_session_split_keeps_old_config_and_latest_truth(client,tmp_path):
    service,status=live_source(client,tmp_path)
    old=client.post('/api/probe/sessions/start',json={'device_count':1,'devices':'test phone','layout':'test room','notes':'original'}).json()
    client.post('/api/probe/truth',json={'device_count':3,'notes':'three phones'})
    assert client.put('/api/probe/rssi',json={'rssi_min':-65}).status_code==409
    assert service.session['id']==old['id'] and service.probe_cfg.rssi_min==-127
    response=client.put('/api/probe/rssi',json={'rssi_min':-65,'split_session':True})
    assert response.status_code==200
    data=response.json();new=data['session']
    assert data['previous_session']['id']==old['id'] and data['previous_session']['ended_at']
    assert data['previous_session']['config']['rssi_min']==-127
    assert new['id']!=old['id'] and new['config']['rssi_min']==-65
    assert new['device_count']==3 and new['devices']=='test phone' and new['layout']=='test room'
    assert service.snapshot()['valid']
    assert client.get(f"/api/probe/sessions/{old['id']}/files/raw").status_code==200
    assert client.post(f"/api/probe/sessions/{old['id']}/evaluate").status_code==200
    client.post('/api/probe/sessions/stop')
    assert client.post(f"/api/probe/sessions/{new['id']}/evaluate").status_code==200


def test_rssi_validation_and_replay_guard(client):
    for value in [-128,1,-65.5,'-65']:
        assert client.put('/api/probe/rssi',json={'rssi_min':value}).status_code==422
    assert client.put('/api/probe/rssi',json={}).status_code==422
    assert client.put('/api/probe/rssi',json={'rssi_min':-80}).status_code==200
    main.svc.mode='replay'
    assert client.put('/api/probe/rssi',json={'rssi_min':-70}).status_code==409
    assert main.svc.probe_cfg.rssi_min==-80
