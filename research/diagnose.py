"""Reconstruct evidence around manual AP/scan markers; never infer MAC identity."""
import argparse,csv,json
from pathlib import Path
from backend.app.protocol import mac_valid
from research.detectors import ProbeConfig,ALGORITHM_VERSION
from research.stream import Stream
from research.evaluate import load_records

def diagnose(folder,mac):
    if not mac_valid(mac):raise ValueError('Invalid full MAC')
    mac=mac.lower();folder=Path(folder);meta=json.loads((folder/'metadata.json').read_text())
    stream=Stream(ProbeConfig(**meta['config']));trace=[];last=0.
    for t,p in load_records(folder/'raw.jsonl'):
        result=stream.feed(p,t);last=t
        if p['type']=='probe' and p['source_mac']==mac and result!='duplicate_record':
            trace.append(dict(t_s=t,rssi=p['rssi'],channel=p['channel'],frame_seq=p['frame_seq'],
                              result=result))
    markers=[];path=folder/'markers.jsonl'
    if path.exists():
        for line in path.read_text().splitlines():
            m=json.loads(line)
            if m.get('mac') not in (None,mac):continue
            t=m['t_s'];before=[r for r in trace if t-60<=r['t_s']<t];after=[r for r in trace if t<=r['t_s']<t+60]
            markers.append(dict(**m,window_s=60,received_before=len(before),received_after=len(after),
                accepted_before=sum(r['result']=='accepted' for r in before),accepted_after=sum(r['result']=='accepted' for r in after),
                seconds_available_after=max(0,min(60,last-t))))
    report=dict(mac=mac,algorithm_version=ALGORITHM_VERSION,synthetic=bool(meta.get('synthetic')),
                observed=bool(trace),received=len(trace),accepted=sum(r['result']=='accepted' for r in trace),markers=markers,
                conclusion='Evidence for this MAC only. Zero after a marker cannot distinguish MAC change, passive scan, silence, channel miss or out-of-range. No automatic linking to another MAC.')
    out=folder/'diagnosis';out.mkdir(exist_ok=True)
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    with (out/'probe-trace.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=['t_s','rssi','channel','frame_seq','result']);w.writeheader();w.writerows(trace)
    return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--session',required=True);p.add_argument('--mac',required=True);a=p.parse_args()
    print(json.dumps(diagnose(a.session,a.mac),ensure_ascii=False,indent=2))
