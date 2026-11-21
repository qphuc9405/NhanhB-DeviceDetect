import asyncio,json,os,pty
from pathlib import Path
import pytest
from research.detectors import ProbeConfig,Sherlock,Comparison
from research.collector import ProbeService
from research.evaluate import evaluate,load_records,timeline,scores
from scripts.probe_fixture import generate

def packet(mac='02:00:00:00:00:01',seq=1,rssi=-40):
    return dict(v=1,type='probe',node='sniffer',boot_id='a',ts_us=100,seq=seq,source_mac=mac,rssi=rssi,channel=6,frame_seq=seq)

def test_slot_convention_and_departure():
    cfg=ProbeConfig(slot_s=10,arrival_slots=2,withdrawal_slots=2,departure_slots=2);d=Sherlock(cfg)
    d.observe(packet(),1);assert d.snapshot(10)['count']==0
    d.observe(packet(seq=2),11);assert d.snapshot(20)['count']==1
    d.observe(packet(seq=3),21);assert d.snapshot(30)['count']==1
    assert d.snapshot(40)['sources'][0]['state']=='departing'
    assert d.snapshot(50)['count']==0
    assert d.snapshot(60)['count']==0

def test_withdrawal_and_resume():
    d=Sherlock(ProbeConfig(slot_s=10,arrival_slots=3,withdrawal_slots=2))
    d.observe(packet(),0);d.snapshot(20);assert len(d.tracks)==1
    d.observe(packet(),21);d.snapshot(30);assert d.tracks[packet()['source_mac']].positive==2
    assert not d.snapshot(50)['sources']

def test_probe_burst_does_not_count_as_multiple_positive_slots():
    d=Sherlock(ProbeConfig(slot_s=10,arrival_slots=2))
    for i in range(100):d.observe(packet(seq=i),1+i*.01)
    assert d.snapshot(10)['count']==0

def test_open_slot_source_count_is_distinct_and_resets_at_boundary():
    d=Comparison(ProbeConfig(slot_s=10,rssi_min=-75,excluded_macs=['02:00:00:00:00:02']))
    d.observe(packet(),1)
    d.observe(packet(seq=2),2)
    d.observe(packet(mac='02:00:00:00:00:02'),3)
    d.observe(packet(mac='02:00:00:00:00:03',rssi=-90),4)
    assert d.snapshot(4)['sherlock']['n_sources_seen']==1
    boundary=d.snapshot(10)
    assert boundary['sherlock']['n_sources_seen']==0
    assert boundary['unique_count']==1

def test_return_before_departure():
    d=Sherlock(ProbeConfig(slot_s=1,arrival_slots=1,departure_slots=3))
    d.observe(packet(),0);d.observe(packet(),1);assert d.snapshot(2)['count']==1
    d.snapshot(3);d.observe(packet(),3.1);assert d.snapshot(4)['sources'][0]['state']=='present'

def test_filter_and_retry():
    d=Comparison(ProbeConfig(rssi_min=-75,excluded_macs=['02:00:00:00:00:02']))
    d.observe(packet(rssi=-100),0);d.observe(packet(mac='02:00:00:00:00:02'),1)
    assert d.snapshot(1)['unique_count']==0
    d.observe(packet(),2);d.observe({**packet(),'retry':True},2.01);assert d.duplicates==1
    d.observe(packet(seq=2),3);assert d.snapshot(3)['timeout_count']==1
    with pytest.raises(ValueError):d.snapshot(1)

def test_capacity_and_large_silence():
    d=Sherlock(ProbeConfig(max_sources=1,slot_s=1))
    d.observe(packet(),0);d.observe(packet(mac='02:00:00:00:00:02'),0)
    d.snapshot(1);assert len(d.tracks)==1
    assert d.snapshot(10**9)['count']==0

def test_evaluation_and_undefined_pcc(tmp_path):
    generate(tmp_path);r=evaluate(tmp_path)
    assert r['synthetic'] and r['coverage']==1 and r['algorithms']['sherlock']['n']>0
    assert len(r['events']['sherlock'])==4
    assert all('censored' in x for x in r['events']['sherlock'])
    assert scores([0,0],[0,1])['pcc'] is None
    assert scores([0,0],[0,1])['mre_nonzero'] is None
    assert scores([0,0],[0,1])['zero_truth_mae']==.5

def test_heartbeat_gap_excluded_and_reboot(tmp_path):
    generate(tmp_path);path=tmp_path/'raw.jsonl';rows=[json.loads(l) for l in path.read_text().splitlines()]
    rows=[r for r in rows if not (15<r['host_elapsed_s']<30)]
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    frames=list(timeline(path,ProbeConfig(slot_s=5)))
    assert any(not r['valid'] for r in frames if 22<=r['t_s']<=29)

def test_sniffer_virtual_uart_record_and_replay(tmp_path):
    async def run():
        master,slave=pty.openpty();port=os.ttyname(slave)
        p=ProbeService(tmp_path/'runtime',ProbeConfig(slot_s=1,arrival_slots=1))
        await p.connect(port,460800)
        for _ in range(50):
            if p.connection=='connected':break
            await asyncio.sleep(.01)
        fixture=tmp_path/'fixture';generate(fixture)
        rows=list(load_records(fixture/'raw.jsonl'));status=rows[0][1]
        os.write(master,(json.dumps(status)+'\n').encode());await asyncio.sleep(.2)
        assert p.snapshot()['valid']
        p.start_session(dict(device_count=1,people_count=1,devices='TEST ONLY',layout='virtual UART',notes='test'))
        os.write(master,(json.dumps(packet())+'\n').encode());await asyncio.sleep(.2)
        p.add_truth(0);meta=p.stop_session();assert meta['records']>=1
        await p.stop();p.store.close();os.close(master);os.close(slave)
        r=evaluate(tmp_path/'runtime/experiments'/meta['id']);assert r['valid_rows']>=1
    asyncio.run(run())

def test_sweep_refuses_leakage(tmp_path):
    from research.sweep import sweep
    p=tmp_path/'split.json';p.write_text(json.dumps(dict(development=['a'],test=['a'])))
    with pytest.raises(ValueError,match='disjoint'):sweep(tmp_path,p,tmp_path/'results')

def test_replay_clock_and_online_features_agree(tmp_path):
    generate(tmp_path);meta=json.loads((tmp_path/'metadata.json').read_text());cfg=ProbeConfig(**meta['config'])
    offline=list(timeline(tmp_path/'raw.jsonl',cfg))
    d=Comparison(cfg);records=list(load_records(tmp_path/'raw.jsonl'));i=0
    for row in offline:
        while i<len(records) and records[i][0]<=row['t_s']:
            t,p=records[i]
            if p['type']=='probe':d.observe(p,t)
            i+=1
        snap=d.snapshot(row['t_s'])
        assert snap['sherlock']['count']==row['sherlock']
        assert snap['unique_count']==row['unique']
        assert snap['timeout_count']==row['timeout']

def test_paper_sized_thresholds():
    d=Sherlock(ProbeConfig(slot_s=60,arrival_slots=6,withdrawal_slots=2,departure_slots=6))
    for minute in range(6):d.observe(packet(seq=minute),minute*60+1)
    assert d.snapshot(359)['count']==0
    assert d.snapshot(360)['count']==1
    assert d.snapshot(719)['count']==1
    assert d.snapshot(720)['count']==0

def test_source_absence_does_not_mean_zero(tmp_path):
    p=ProbeService(tmp_path,ProbeConfig());p.mode='synthetic';p.connection='connected';p.clock=100
    assert p.snapshot()['valid'] is False and p.snapshot()['result'] is None
    p.store.close()
