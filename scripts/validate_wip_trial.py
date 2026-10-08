"""Validate normally imported WIP cases, conservation and complete export replay."""
import os,sys,json,hashlib
from pathlib import Path
from collections import defaultdict
from decimal import Decimal,ROUND_CEILING
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import wip_trial_data,wip_trial_views,wip_trial_replay
from app.models import Record,ImportBatch


def validate():
    cases=[];tasks_checked=reservations_checked=sources_checked=0
    expected={1:(2,1,49,0,2),2:(2,1,9,40,0),3:(2,1,23,26,1),6:(2,1,49,0,2)}
    for n in range(1,9):
        for policy in ('due','priority'):
            d=wip_trial_data.load(f'WR-261001-{n:03d}',policy);r=d['result'];doc=wip_trial_views.document(d)
            assert wip_trial_replay.replay(doc)==r,(n,policy,'export replay')
            assert r['state']==('trial' if n in expected else 'paused'),(n,r['issues'])
            assert all(not s.get('missing') and s.get('row',0)>=2 and s.get('file_hash') for s in d['sources'])
            for source in d['sources']:
                rec=Record.objects.get(dataset=source['dataset'],business_key=source['key']);assert rec.source_row.row_number==source['row'] and rec.record_hash==source['record_hash']
            sources_checked+=len(d['sources'])
            if n not in expected:
                assert r['summary'] is None and not r['tasks'] and not r['reservations'];cases.append(dict(id=r['study']['id'],policy=policy,state=r['state'],issues=r['issues']));continue
            s=r['summary'];assert tuple(s[k] for k in ('historical_completed_tasks','carried_tasks','scheduled_tasks','blocked_tasks','covered_jobs'))==expected[n]
            tasks={t['id']:t for t in r['tasks']};progress={t['task_id']:t for t in d['tables']['wip_trial_tasks']}
            running=next(t for t in r['tasks'] if t['state']=='carried');assert running['started']=='2026-10-01T18:00:00' and running['finished']==f'2026-10-01T18:{18 if n==6 else 12}:00' and running['setup_minutes']==0
            for field in ('resource_id','employee_id'):
                grouped=defaultdict(list)
                for t in r['tasks']:
                    if t['state'] in ('carried','scheduled'):grouped[t[field]].append((t['started'],t['finished']))
                for ident,spans in grouped.items():
                    spans.sort();assert all(a[1]<=b[0] for a,b in zip(spans,spans[1:])),(field,ident)
            for t in r['tasks']:
                tasks_checked+=1;p=progress[t['id']];assert t['completed_qty']+t['remaining_qty']==t['original_qty']
                if t['state']=='completed':assert t['remaining_qty']==0 and t['started'] is None and t['resource_id'] is None;continue
                if t['state']=='blocked':assert t['finished'] is None;continue
                assert datetime.fromisoformat(t['finished'])-datetime.fromisoformat(t['process_started'])==timedelta(seconds=int((Decimal(str(p['remaining_minutes']))*60).to_integral_value(rounding=ROUND_CEILING)))
                assert (datetime.fromisoformat(t['process_started'])-datetime.fromisoformat(t['started'])).total_seconds()==t['setup_minutes']*60
                for ds,field in [('schedule_windows','resource_id'),('crew_windows','employee_id')]:
                    assert any(x[field]==t[field] and x['started']<=t['started'] and x['finished']>=t['finished'] for x in d['parent_inputs'][ds])
                for ds,field in [('schedule_blocks','resource_id'),('crew_blocks','employee_id')]:
                    assert not any(x[field]==t[field] and max(x['started'],t['started'])<min(x['finished'],t['finished']) for x in d['parent_inputs'][ds])
                for edge in d['parent_inputs']['schedule_edges']:
                    if edge['to_task_id']==t['id']:
                        pred=tasks[edge['from_task_id']];assert pred['state']!='blocked'
                        assert datetime.fromisoformat(t['started'])>=datetime.fromisoformat(pred['finished'])+timedelta(minutes=edge['lag_minutes'])
            lots={l['id']:l for l in r['lots']};need={x['id']:x for x in r['demands']};used=defaultdict(Decimal);got=defaultdict(Decimal)
            for a in r['reservations']:
                reservations_checked+=1;lot=lots[a['supply_id']];task=tasks[a['task_id']];q=Decimal(a['qty']);assert q>0 and a['reserved_at']==task['started'] and lot['available_from']<=a['reserved_at']
                assert lot.get('owner_job_id') in (None,'',task['job_id']);used[lot['id']]+=q;got[a['demand_id']]+=q
            for lot in lots.values():assert Decimal(lot['usable_qty'])==used[lot['id']]+Decimal(lot['remaining_qty']) and used[lot['id']]==Decimal(lot['reserved_qty'])
            bom={x['id']:x for x in d['references']['bom']};bindings={x['id']:x for x in d['parent_inputs']['joint_bindings']}
            for x in need.values():
                b=bindings[x['binding_id']];line=bom[b['bom_id']];q=Decimal(tasks[x['task_id']]['remaining_qty']);quantum=Decimal(str(b['quantum']))
                gross=(q*Decimal(str(line['qty']))*(1+Decimal(str(line['scrap_allowance'])))/quantum).to_integral_value(rounding=ROUND_CEILING)*quantum
                assert gross==Decimal(x['gross_remaining_qty']) and gross-Decimal(x['embedded_qty'])==Decimal(x['required_qty'])
                assert got[x['id']]==Decimal(x['reserved_qty'])
                assert got[x['id']]==(Decimal(x['required_qty']) if tasks[x['task_id']]['state']!='blocked' else 0)
            cases.append(dict(id=r['study']['id'],policy=policy,state=r['state'],summary=s))
    batch=ImportBatch.objects.get(filename='48_在制剩余试排_模拟.xlsx',status='committed')
    assert batch.summary==dict(committed=1577,total=1577,unknown_sheets=[])
    proof=dict(success=True,version='0.36.0',records=Record.objects.count(),new_excel_rows=1577,cases=cases,tasks_checked=tasks_checked,reservations_checked=reservations_checked,sources_checked=sources_checked,export_replay=True,browser_acceptance=False)
    (ROOT/'data/wip_trial_validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    return proof


if __name__=='__main__':print(json.dumps(validate(),ensure_ascii=False))
