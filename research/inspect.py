"""Observed-source statistics, not physical device fingerprints or identities."""
import json,csv,math,argparse
from collections import defaultdict,Counter
from pathlib import Path
import numpy as np
from research.evaluate import load_records
from research.stream import RecentProbeRecords

def inspect_session(folder,slot_s=60):
    folder=Path(folder);meta=json.loads((folder/'metadata.json').read_text());sources=defaultdict(list)
    channels=Counter();last=0.;recent=RecentProbeRecords()
    for t,p in load_records(folder/'raw.jsonl'):
        last=max(last,t)
        if p['type']=='probe' and recent.remember(p):
            sources[p['source_mac']].append((t,p['rssi'],p['channel']));channels[p['channel']]+=1
    slots=max(1,math.floor(last/slot_s)+1);matrix=[];summary=[]
    for index,(mac,rows) in enumerate(sorted(sources.items()),1):
        times=[x[0] for x in rows];gaps=np.diff(times);counts=Counter(math.floor(t/slot_s) for t in times)
        # Masking is for this report only; raw retains observed MACs.
        display=f'src-{index:03d} {mac[:8]}:…:{mac[-2:]}'
        summary.append(dict(source=display,probes=len(rows),first_seen_s=times[0],last_seen_s=times[-1],
                            observed_span_s=times[-1]-times[0],positive_slots=len(counts),
                            max_observed_gap_s=float(max(gaps)) if len(gaps) else None,
                            median_rssi=float(np.median([x[1] for x in rows]))))
        matrix.append((display,[counts[i] for i in range(slots)]))
    out=folder/'inspection';out.mkdir(exist_ok=True)
    result=dict(synthetic=bool(meta.get('synthetic')),scope='Observed MAC sources, not physical devices',
                duration_s=last,slot_s=slot_s,channel_probe_counts=dict(channels),sources=summary)
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    with (out/'probe-slots.csv').open('w') as f:
        w=csv.writer(f);w.writerow(['source']+[f'slot_{i}' for i in range(slots)])
        for row,counts in matrix:w.writerow([row]+counts)
    # Self-contained SVG heatmap; no external plotting dependency.
    width=240+max(1,slots)*24;height=100+len(matrix)*28
    items=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           '<text x="12" y="24" font-family="sans-serif" font-size="16">Probe requests per observed MAC / slot</text>']
    for j in range(slots):items.append(f'<text x="{220+j*24}" y="52" font-family="sans-serif" font-size="10">{j}</text>')
    for i,(row,counts) in enumerate(matrix):
        y=65+i*28;items.append(f'<text x="12" y="{y+16}" font-family="monospace" font-size="12">{row}</text>')
        for j,n in enumerate(counts):
            color='#eef2f6' if not n else '#0d9488';opacity=1 if not n else min(1,.3+math.log1p(n)/5)
            items.append(f'<rect x="{216+j*24}" y="{y}" width="22" height="23" fill="{color}" fill-opacity="{opacity}"><title>{n} probes</title></rect>')
    items.append('</svg>');(out/'probe-heatmap.svg').write_text(''.join(items))
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--session',required=True);p.add_argument('--slot',type=float,default=60)
    a=p.parse_args()
    if a.slot<=0:p.error('slot must be positive')
    print(json.dumps(inspect_session(a.session,a.slot),ensure_ascii=False,indent=2))
