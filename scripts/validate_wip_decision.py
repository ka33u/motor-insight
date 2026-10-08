"""Read-only dispatch evidence check against normally imported simulated Excel."""
import argparse,json,os,sys,hashlib
from pathlib import Path
from datetime import datetime,timedelta
from decimal import Decimal,ROUND_CEILING
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import wip_trial_data,wip_trial_decision,wip_trial_views,wip_trial_replay,analytics
from app.models import Record


def first_slot(pair,process_minutes,carried):
    if pair['earliest'] is None:return None
    dt=datetime.fromisoformat;early=dt(pair['earliest'])
    duration=timedelta(seconds=int((Decimal(str(process_minutes))*60).to_integral_value(rounding=ROUND_CEILING))+round(pair['setup_minutes']*60))
    options=[]
    for w in pair['windows']:
        left=max(early,dt(w['started']));right=dt(w['finished'])
        points={left}|{dt(b['finished']) for b in pair['blocks'] if left<=dt(b['finished'])<right}
        for start in sorted(points):
            end=start+duration
            if end>right:continue
            if any(max(start,dt(b['started']))<min(end,dt(b['finished'])) for b in pair['blocks']):continue
            if not carried or start==early:options.append((start,end))
    return min(options) if options else None


def validate(write_fixtures=False):
    count=dict(tasks=0,pairs=0,selected=0,blocked=0,historical=0,replays=0);cases=[];fixtures={}
    for n in range(1,9):
        for policy in ('due','priority'):
            context=wip_trial_data.load(f'WR-261001-{n:03}',policy);r=context['result'];seen=set()
            cases.append(dict(id=r['study']['id'],policy=policy,state=r['state'],result_hash=hashlib.sha256(json.dumps(r,sort_keys=True,ensure_ascii=False).encode()).hexdigest()))
            for task in r['tasks']:
                d=wip_trial_decision.build(context,task['id'],analytics.AS_OF);count['tasks']+=1
                assert d['state'] in ('explained','historical'),d['issues']
                if task['state']=='completed':
                    count['historical']+=1;assert d['state']=='historical' and not d['pairs']
                else:
                    assert len(d['pairs'])==d['pair_count']
                    selected=[]
                    for p in d['pairs']:
                        count['pairs']+=1
                        if p['selected']:selected.append(p);count['selected']+=1
                        calculated=first_slot(p,task['process_minutes'],task['state']=='carried')
                        assert (p['started'] is not None)==(calculated is not None),(task['id'],p['option_id'],p['candidate_id'])
                        if calculated:assert tuple(x.isoformat(timespec='seconds') for x in calculated)==(p['started'],p['finished'])
                        for field in ('resource','worker'):
                            for ident in p[field+'_tail_tasks']:
                                tail=next(x for x in r['tasks'] if x['id']==ident)
                                assert tail['state'] in ('scheduled','carried') and tail['finished']==p[field+'_tail']
                    if task['state']=='blocked':assert not selected;count['blocked']+=1
                    else:
                        assert len(selected)==1
                        assert (selected[0]['resource_id'],selected[0]['employee_id'],selected[0]['started'],selected[0]['finished'])==(task['resource_id'],task['employee_id'],task['started'],task['finished'])
                if n==1 and policy=='due' and any(p['resource_tail_tasks'] or p['worker_tail_tasks'] for p in d['pairs']):fixtures.setdefault('tail',d)
                kind=task['state'] if task['input_state']!='中断待续' else 'recovery'
                if kind not in seen:
                    doc=wip_trial_views.document(context)|dict(task_id=task['id'],decision=d)
                    assert wip_trial_replay.replay_decision(doc)==d;seen.add(kind);count['replays']+=1
                    if n in (1,2) and policy=='due':fixtures.setdefault(kind,d)
    if write_fixtures:(ROOT/'tests/fixtures/wip_decision.json').write_text(json.dumps(fixtures,ensure_ascii=False,indent=2)+'\n')
    proof=dict(success=True,definition=wip_trial_decision.VERSION,records=Record.objects.count(),**count,cases=cases,browser_acceptance=False)
    (ROOT/'data/wip_decision_validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in proof.items() if k!='cases'},ensure_ascii=False))
    return proof


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--write-fixtures',action='store_true');validate(p.parse_args().write_fixtures)
