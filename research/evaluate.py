"""Offline comparison; no dependency on wall-clock sleep or dashboard sampling.
Run python -m research.evaluate --session data/probe-runtime/experiments/ID
Truth is a step function in host_elapsed_s, NOT MAC labels or inferred people.
"""
import argparse,csv,json,math
from pathlib import Path
from research.detectors import ProbeConfig,ALGORITHM_VERSION
from research.stream import RecentProbeRecords, Stream
from backend.app.protocol import parse_line

def load_records(path, *, deduplicate_probes=False):
    """Host elapsed avoids joining clocks from different boots. Invalid lines skipped.
    For legacy unwrapped records, derive per-boot offsets from the last observation.
    Keep file order for delayed probes and clamp their processing time to the
    current clock. The original ts_us remains available on the packet.
    Missing duration across boots is unknowable in that fallback.
    """
    last=-1.;offset=0.;boot=None;first=None
    recent = RecentProbeRecords() if deduplicate_probes else None
    with Path(path).open() as f:
        for line in f:
            try:
                row=json.loads(line)
                if not isinstance(row,dict):continue
                if 'control' in row:
                    kind=row['control']['kind']
                    if kind not in ('serial_connected','serial_disconnected','session_stopped'):continue
                    p=dict(type='control',kind=kind)
                else:p=parse_line(json.dumps(row.get('packet',row)))
                if 'host_elapsed_s' in row:
                    host_time = row['host_elapsed_s']
                    if isinstance(host_time, bool):continue
                    t=float(host_time)
                    if not math.isfinite(t) or t<0:continue
                    if p['type']=='probe':t=max(last,t)
                else:
                    if p['type']=='control':continue
                    if p['boot_id']!=boot:
                        offset=max(0,last);first=p['ts_us'];boot=p['boot_id']
                    t=max(last,offset+(p['ts_us']-first)/1e6)
                if not math.isfinite(t) or t<0 or t<last:continue
            except (ValueError,TypeError,KeyError,OverflowError):continue
            last=t
            if recent is not None and p['type']=='probe' and not recent.remember(p):continue
            yield t,p

def timeline(path,cfg,step=1.,event_sink=None):
    records=iter(load_records(path));pending=next(records,None)
    if pending is None:raise ValueError('No valid sniffer records')
    stream=Stream(cfg);t=0.;last_event=pending[0];event_seq=0
    def collect_events():
        nonlocal event_seq
        for ev in stream.events:
            if ev['event_seq']>event_seq:
                if event_sink is not None:event_sink.append(ev.copy())
                event_seq=ev['event_seq']
    while pending is not None or t<=last_event:
        while pending is not None and pending[0]<=t:
            stamp,p=pending;last_event=stamp;stream.feed(p,stamp);collect_events();pending=next(records,None)
        if pending is None and t>last_event:break
        state=stream.snapshot(t);collect_events();r=state['result']
        yield dict(t_s=t,valid=state['valid'],unique=None if r is None else r['unique_count'],
                   timeout=None if r is None else r['timeout_count'],sherlock=None if r is None else r['sherlock']['count'])
        t+=step

def scores(actual,pred):
    import numpy as np
    a=np.array(actual,float);p=np.array(pred,float);e=p-a
    if not len(a):return dict(n=0)
    nz=a>0
    corr=float(np.corrcoef(a,p)[0,1]) if len(a)>1 and a.std()>0 and p.std()>0 else None
    return dict(n=len(a),mae=float(abs(e).mean()),bias=float(e.mean()),exact_rate=float((e==0).mean()),
                pcc=corr,mre_nonzero=float((abs(e[nz])/a[nz]).mean()) if nz.any() else None,
                zero_truth_mae=float(abs(e[~nz]).mean()) if (~nz).any() else None)

def event_delays(rows,truth,key):
    """Time to cross changed ground-truth count before next event (sampled grid).
    An unresolved event is censored, never silently removed from denominator.
    """
    events=[]
    for i,event in enumerate(truth[1:],1):
        old=truth[i-1]['device_count'];new=event['device_count']
        if old==new:continue
        end=truth[i+1]['t_s'] if i+1<len(truth) else float('inf')
        hit=None
        for row in rows:
            if event['t_s']<=row['t_s']<end and row['valid']:
                value=row[key]
                if (new>old and value>=new) or (new<old and value<=new):hit=row['t_s']-event['t_s'];break
        events.append(dict(t_s=event['t_s'],direction='arrival' if new>old else 'departure',delay_s=hit,censored=hit is None))
    return events

def evaluate(folder,cfg=None,output=None):
    folder=Path(folder);meta=json.loads((folder/'metadata.json').read_text())
    cfg=cfg or ProbeConfig(**meta['config'])
    cfg=cfg.model_copy(update={'excluded_macs':sorted(set(cfg.excluded_macs+meta['config'].get('excluded_macs',[])))})
    truth=[json.loads(l) for l in (folder/'truth.jsonl').read_text().splitlines() if l.strip()]
    if not truth or any(truth[i]['t_s']<truth[i-1]['t_s'] for i in range(1,len(truth))):raise ValueError('Missing/unordered ground truth')
    journal=[];rows=list(timeline(folder/'raw.jsonl',cfg,event_sink=journal));idx=0
    for r in rows:
        while idx+1<len(truth) and truth[idx+1]['t_s']<=r['t_s']:idx+=1
        r['truth']=truth[idx]['device_count'] if truth[idx]['t_s']<=r['t_s'] else None
    valid=[r for r in rows if r['valid'] and r['truth'] is not None]
    raw_path=folder/'raw.jsonl'
    total_lines=sum(1 for _ in raw_path.open())
    parsed_records=sum(1 for _ in load_records(raw_path))
    report=dict(algorithm_version=ALGORITHM_VERSION,recorded_algorithm_version=meta.get('algorithm_version','legacy-v1'),time_semantics='causal confirmation; no backdating',raw_lines=total_lines,parsed_records=parsed_records,skipped_lines=total_lines-parsed_records,session=meta['id'],synthetic=bool(meta.get('synthetic')),config=cfg.model_dump(),
                semantics='counts of MAC sources compared against physical-device ground truth; not identity recovery',
                rows=len(rows),valid_rows=len(valid),coverage=len(valid)/len(rows) if rows else 0,
                algorithms={k:scores([r['truth'] for r in valid],[r[k] for r in valid]) for k in ('unique','timeout','sherlock')},
                events={k:event_delays(rows,truth,k) for k in ('unique','timeout','sherlock')},
                event_definition='First crossing of new count before next truth event; not device-specific arrival/departure; preexisting bias may give zero delay')
    out=Path(output) if output else folder/'evaluation';out.mkdir(parents=True,exist_ok=True)
    (out/'algorithm-events.jsonl').write_text(''.join(json.dumps(ev,ensure_ascii=False)+'\n' for ev in journal))
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    with (out/'timeline.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=['t_s','valid','unique','timeout','sherlock','truth']);w.writeheader();w.writerows(rows)
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--session',required=True);ap.add_argument('--config');ap.add_argument('--output')
    a=ap.parse_args();cfg=ProbeConfig(**json.loads(Path(a.config).read_text())) if a.config else None
    print(json.dumps(evaluate(a.session,cfg,a.output),ensure_ascii=False,indent=2))
