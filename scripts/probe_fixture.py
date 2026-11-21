"""Explicitly synthetic fixture; validates plumbing, never detection accuracy."""
import json
from pathlib import Path

def generate(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    from research.detectors import ProbeConfig
    cfg_path=Path(__file__).resolve().parents[1]/'configs/demo.json'
    cfg=ProbeConfig.model_validate_json(cfg_path.read_text())
    status=dict(v=1,type='status',node='sniffer',boot_id='synthetic',ts_us=0,seq=0,capture_active=True,
                source_mac=None,own_mac='02:00:00:00:00:ff',channel=6,
                probe_seen=0,probe_dropped=0,invalid=0,serial_errors=0,bytes_written=0,serial_baud=460800,
                sniffer_enabled=True,scan_mode='fixed',dwell_ms=3000)
    rows=[];seq=0
    for t in range(90):
        p={**status,'ts_us':t*1000000,'seq':seq};seq+=1
        rows.append(dict(packet=p,host_elapsed_s=t,source='synthetic'))
        for i,(start,end) in enumerate([(5,45),(20,60)]):
            if start<=t<end and t%2==0:
                p=dict(v=1,type='probe',node='sniffer',boot_id='synthetic',ts_us=t*1000000+10000,
                       seq=seq,source_mac=f'02:00:00:00:00:0{i+1}',rssi=-45-i*5,channel=6,frame_seq=seq%4096)
                seq+=1;rows.append(dict(packet=p,host_elapsed_s=t+.01,source='synthetic'))
    (folder/'raw.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    (folder/'truth.jsonl').write_text(''.join(json.dumps(dict(t_s=t,device_count=n))+'\n' for t,n in [(0,0),(5,1),(20,2),(45,1),(60,0)]))
    (folder/'metadata.json').write_text(json.dumps(dict(id='synthetic-probe-demo',synthetic=True,
        started_at='SYNTHETIC',ended_at='SYNTHETIC',config=cfg.model_dump(),notes='Fixture, not hardware measurements'),indent=2))
if __name__=='__main__':generate(Path(__file__).resolve().parents[1]/'data/synthetic-probe-demo')
