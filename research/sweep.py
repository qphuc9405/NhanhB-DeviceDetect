"""Choose parameters on development sessions ONLY. Held-out test is separate."""
import argparse,json,itertools
from pathlib import Path
from research.evaluate import evaluate
from research.detectors import ProbeConfig

def sweep(root,manifest,output):
    m=json.loads(Path(manifest).read_text());dev=m['development'];test=m['test']
    if not dev or not test or set(dev)&set(test):raise ValueError('Need nonempty disjoint development/test session IDs')
    root=Path(root).resolve();out=Path(output);out.mkdir(parents=True,exist_ok=True)
    def folder(s):
        p=(root/s).resolve()
        if p.parent!=root:raise ValueError('Invalid session ID')
        return p
    configs=[ProbeConfig(slot_s=s,arrival_slots=a,withdrawal_slots=w,departure_slots=d)
             for s,a,w,d in itertools.product([15,30,60],[2,4,6],[1,2],[2,4,6])]
    ranking=[]
    for i,cfg in enumerate(configs):
        total=0.;n=0
        for sid in dev:
            r=evaluate(folder(sid),cfg,out/'development'/f'config-{i}'/sid)
            score=r['algorithms']['sherlock'];n+=score['n'];total+=score.get('mae',0)*score['n']
        if n:ranking.append((total/n,i,cfg))
    if not ranking:raise ValueError('No valid development intervals')
    ranking.sort(key=lambda x:(x[0],x[1]));score,index,best=ranking[0]
    (out/'selected-config.json').write_text(best.model_dump_json(indent=2))
    reports={sid:evaluate(folder(sid),best,out/'test'/sid) for sid in test}
    result=dict(selection_metric='development MAE, weighted by valid seconds',development_mae=score,
                development_sessions=dev,test_sessions=test,selected=best.model_dump(),test=reports)
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--split',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();sweep(a.root,a.split,a.output)
