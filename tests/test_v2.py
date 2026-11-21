import json,random
from pathlib import Path
import pytest
from research.detectors import ProbeConfig,Sherlock,Comparison,ALGORITHM_VERSION
from research.stream import Stream
from research.collector import ProbeService
from research.evaluate import load_records,timeline,evaluate
from scripts.probe_fixture import generate
from backend.app import main

MAC='02:00:00:00:00:01'
def probe(mac=MAC,rssi=-40,seq=1,retry=False):
    return dict(v=1,type='probe',node='sniffer',boot_id='test',ts_us=1,seq=seq,source_mac=mac,rssi=rssi,channel=6,frame_seq=seq,retry=retry)
def status(channel=6,boot='test',active=True,dropped=0):
    return dict(v=1,type='status',node='sniffer',boot_id=boot,ts_us=0,seq=0,capture_active=active,
        own_mac='02:00:00:00:00:ff',channel=channel,probe_seen=0,probe_dropped=dropped,invalid=0,
        serial_errors=0,bytes_written=0,serial_baud=460800,sniffer_enabled=True,scan_mode='hopping',dwell_ms=3000)

def test_first_positive_and_first_empty_count():
    d=Sherlock(ProbeConfig(slot_s=1,arrival_slots=1,departure_slots=1));d.observe(probe(),.2)
    assert d.snapshot(.99)['count']==0
    assert d.snapshot(1)['count']==1
    assert d.snapshot(2)['count']==0

def test_current_truth_tracks_label_changes_without_rewriting_initial_count(tmp_path):
    service=ProbeService(tmp_path/'runtime',ProbeConfig())
    try:
        service.mode='serial';service.connection='connected'
        service.ingest(json.dumps(status()))
        assert service.snapshot()['current_truth'] is None
        service.start_session(dict(device_count=1,devices='Test phone',layout='Classroom',notes=''))
        assert service.snapshot()['current_truth']['device_count']==1
        service.add_truth(3,notes='Two more phones entered')
        state=service.snapshot()
        assert state['current_truth']['device_count']==3
        assert state['session']['device_count']==1
        meta=service.stop_session()
        assert service.snapshot()['current_truth'] is None
        labels=[json.loads(line) for line in (service.folder/'truth.jsonl').read_text().splitlines()]
        assert [label['device_count'] for label in labels]==[1,3]
        assert meta['device_count']==1
    finally:
        if service.session:service.stop_session()
        service.store.close()

def test_confirmation_event_not_backdated():
    d=Sherlock(ProbeConfig(slot_s=1,arrival_slots=3))
    for t in [.2,1.2,2.2]:d.observe(probe(),t)
    assert d.snapshot(2.9)['count']==0
    assert d.snapshot(3)['count']==1
    e=next(x for x in d.events if x['kind']=='source_confirmed')
    assert e['t_s']==3 and e['first_seen_s']==.2

def test_upstream_php_counter_convention_randomized():
    # Independent slot-level oracle of upstream quantifyPeopleBySlots.php's increments.
    rng=random.Random(4)
    for at,wt,dt in [(1,1,1),(2,2,3),(7,4,7),(6,2,6)]:
        d=Sherlock(ProbeConfig(slot_s=1,arrival_slots=at,withdrawal_slots=wt,departure_slots=dt))
        phase=None;arrivals=absence=departure=0
        for i in range(250):
            hit=rng.random()<.6
            if hit:
                d.observe(probe(seq=i),i+.1)
                if phase is None:phase='candidate';arrivals=0
                if phase=='candidate':
                    arrivals+=1;absence=0
                    if arrivals==at:phase='present'
                departure=0
            elif phase=='candidate':
                absence+=1
                if absence==wt:phase=None
            elif phase=='present':
                departure+=1
                if departure==dt:phase=None
            assert d.snapshot(i+1)['count']==int(phase=='present')

def test_new_mac_never_inherits_old_confirmation():
    d=Sherlock(ProbeConfig(slot_s=1,arrival_slots=2))
    d.observe(probe(),.2);d.observe(probe(),1.2);assert d.snapshot(2)['count']==1
    other='06:00:00:00:00:02';d.observe(probe(mac=other),2.1)
    rows=d.snapshot(3)['sources'];new=next(r for r in rows if r['mac']==other)
    assert new['state']=='candidate' and new['positive_slots']==1

def test_real_new_probe_same_sequence_is_not_retry():
    d=Comparison(ProbeConfig());d.observe(probe(),0);d.observe(probe(),.01)
    assert d.accepted==2
    d.observe(probe(retry=True),.02);assert d.duplicates==1

def test_diagnostics_distinguish_raw_filtered_and_unseen():
    s=Stream(ProbeConfig(rssi_min=-60));s.feed(status(),0)
    s.feed(probe(rssi=-80),.1);r=s.diagnostics(MAC,.2)
    assert r['received']==1 and r['accepted']==0 and r['last_reason']=='weak_rssi'
    s.feed(probe(rssi=-40,seq=2),.3)
    assert s.diagnostics(MAC,.4)['accepted']==1
    assert s.diagnostics('aa:bb:cc:dd:ee:ff',.4)['observed'] is False

def test_mac_expiry_reclaims_diagnostic_capacity_before_admitting_a_probe():
    stream = Stream(ProbeConfig(max_sources=2, mac_expiry_s=3, rssi_min=-60,
                                slot_s=1, arrival_slots=1))
    other = '02:00:00:00:00:ab'
    newcomer = '02:00:00:00:00:03'
    stream.feed(status(), 0)
    stream.feed(probe(), 0)
    stream.feed(probe(mac=other), 1)
    stream.feed(probe(mac=MAC, rssi=-80), 2)
    stream.feed(probe(mac=newcomer, rssi=-80), 4)
    snapshot = stream.snapshot(4)
    assert [row['mac'] for row in snapshot['recent_sources']] == [MAC, other]
    assert snapshot['quality']['audit_capacity_drops'] == 1
    assert snapshot['quality']['audit_expired'] == 0

    stream.feed(probe(mac=newcomer, rssi=-80, seq=2), 4.5)
    snapshot = stream.snapshot(4.5)
    assert [row['mac'] for row in snapshot['recent_sources']] == [newcomer, MAC]
    assert snapshot['quality']['audit_expired'] == 1
    assert snapshot['result']['unique_count'] == 2
    assert snapshot['result']['sherlock']['count'] == 2
    assert stream.diagnostics(other, 4.5)['observed'] is False
    assert stream.diagnostics(MAC, 4.5)['received'] == 2

def test_mac_expiry_during_heartbeat_gap_and_reappearance():
    stream = Stream(ProbeConfig(mac_expiry_s=3, heartbeat_s=2))
    mac = '02:00:00:00:00:ab'
    stream.feed(status(), 0)
    stream.feed(probe(mac=mac.upper()), 0.5)
    snapshot = stream.snapshot(3.5)
    assert snapshot['result'] is None
    assert [row['mac'] for row in snapshot['recent_sources']] == [mac]
    assert stream.diagnostics(mac, 3.75)['observed'] is False
    assert stream.snapshot(3.75)['quality']['audit_expired'] == 1

    stream.feed(status(), 4)
    stream.feed(probe(mac=mac, seq=2), 4.5)
    result = stream.diagnostics(mac, 4.5)
    assert result['first_seen_s'] == 4.5
    assert result['received'] == result['accepted'] == 1

def test_heartbeat_gap_is_unknown_not_physical_departure():
    s=Stream(ProbeConfig(slot_s=1,arrival_slots=1,departure_slots=1))
    s.feed(status(),0);s.feed(probe(),.1);assert s.snapshot(1)['result']['sherlock']['count']==1
    assert s.snapshot(6)['result'] is None
    s.feed(status(),7);assert s.snapshot(7)['result']['sherlock']['count']==0
    assert any(e.get('reason')=='heartbeat_gap' for e in s.events)
    assert not any(e['kind']=='source_expired_no_observation' for e in s.events)

def test_channel_seconds_are_tuned_time_not_distance():
    s=Stream(ProbeConfig());s.feed(status(6),0)
    s.feed(dict(v=1,type='channel',node='sniffer',boot_id='test',ts_us=1000000,seq=1,channel=11,dwell_ms=3000),1)
    r=s.snapshot(2);assert r['channel_observation_s']=={'6':1.,'11':1.}
    r=s.snapshot(9);assert r['channel_observation_s']=={'6':1.,'11':4.}

def test_reconnect_same_boot_invalidates_tracks():
    s=Stream(ProbeConfig(slot_s=1,arrival_slots=1));s.feed(status(),0);s.feed(probe(),.1)
    assert s.snapshot(1)['result']['sherlock']['count']==1
    s.feed(dict(type='control',kind='serial_disconnected'),1.1)
    assert not s.snapshot(1.2)['valid']
    s.feed(dict(type='control',kind='serial_connected'),1.3);s.feed(status(),1.4)
    assert s.snapshot(1.4)['result']['sherlock']['count']==0

def test_offline_replay_handles_control_and_legacy_version(tmp_path):
    generate(tmp_path)
    path=tmp_path/'raw.jsonl';rows=[json.loads(l) for l in path.read_text().splitlines()]
    rows.append(dict(control=dict(kind='serial_disconnected'),host_elapsed_s=21.5))
    rows.append(dict(control=dict(kind='serial_connected'),host_elapsed_s=22.5))
    rows.sort(key=lambda r:r['host_elapsed_s']);path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    assert any(p['type']=='control' for _,p in load_records(path))
    r=evaluate(tmp_path)
    assert r['algorithm_version']==ALGORITHM_VERSION and r['recorded_algorithm_version']=='legacy-v1'
    events=[json.loads(l) for l in (tmp_path/'evaluation/algorithm-events.jsonl').read_text().splitlines()]
    assert any(e.get('reason')=='serial_connected' for e in events)
    assert json.loads((tmp_path/'metadata.json').read_text()).get('algorithm_version') is None

def test_api_mac_diagnostic_and_marker(client):
    assert client.get('/api/probe/diagnostics',params={'mac':'bad'}).status_code==422
    s=main.svc;s.mode='serial';s.connection='connected';s.ingest(json.dumps(status()))
    assert client.post('/api/probe/sessions/start',json=dict(device_count=1,layout='TEST ONLY',devices='virtual')).status_code==200
    s.ingest(json.dumps(probe()))
    r=client.get('/api/probe/diagnostics',params={'mac':MAC}).json();assert r['received']==1
    r=client.post('/api/probe/markers',json=dict(kind='ap_disconnect',mac=MAC,notes='Manual marker only'))
    assert r.status_code==200 and s.snapshot()['result']['unique_count']==1
    meta=client.post('/api/probe/sessions/stop').json()
    folder=s.store.root/'experiments'/meta['id']
    assert (folder/'markers.jsonl').exists() and (folder/'algorithm-events.jsonl').exists()
    assert meta['algorithm_version']==ALGORITHM_VERSION

def test_live_offline_status_and_control_match(tmp_path):
    cfg=ProbeConfig(slot_s=1,arrival_slots=1,departure_slots=2)
    events=[(0,status()),(.1,probe()),(1,status()),(1.1,dict(type='control',kind='serial_disconnected')),
            (2.1,dict(type='control',kind='serial_connected')),(2.2,status()),(2.3,probe()),(3,status()),(4,status())]
    path=tmp_path/'raw.jsonl'
    path.write_text(''.join(json.dumps(dict(host_elapsed_s=t,**({'control':{'kind':p['kind']}} if p['type']=='control' else {'packet':p})))+'\n' for t,p in events))
    offline=list(timeline(path,cfg));s=Stream(cfg);i=0
    for row in offline:
        while i<len(events) and events[i][0]<=row['t_s']:s.feed(events[i][1],events[i][0]);i+=1
        live=s.snapshot(row['t_s']);assert live['valid']==row['valid']
        assert (live['result']['sherlock']['count'] if live['result'] else None)==row['sherlock']

def test_diagnosis_reports_observations_not_device_departure(tmp_path):
    from research.diagnose import diagnose
    generate(tmp_path);mac='02:00:00:00:00:01'
    (tmp_path/'markers.jsonl').write_text(json.dumps(dict(t_s=44,kind='ap_disconnect',mac=mac,notes='User action'))+'\n')
    r=diagnose(tmp_path,mac)
    assert r['received']>0 and r['markers'][0]['received_before']>0
    assert r['markers'][0]['received_after']==1 and r['markers'][0]['seconds_available_after']==45
    assert (tmp_path/'diagnosis/probe-trace.csv').is_file()
    with pytest.raises(ValueError):diagnose(tmp_path,'invalid')
