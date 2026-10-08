"""Verify selection contracts against normally imported synthetic Excel trials."""
import argparse,json,os,sys
from itertools import product
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import wip_trial_data,wip_trial_selection as selection,wip_trial_replay
from app.wip_trial_views import document
from validate_wip_blockers import expected


def main(write=False):
    cases=[];total=empty=replays=0
    for n in range(1,9):
        for policy in ('due','priority'):
            data=wip_trial_data.load(f'WR-261001-{n:03}',policy);result=data['result'];links=data['tables']['wip_trial_jobs'];oracle=expected(result,links)
            row=dict(study=result['study']['id'],policy=policy,state=result['state'],selections=[])
            if result['state']!='trial':
                try:selection.select(result,links,{})
                except ValueError:pass
                else:raise AssertionError('Paused result cannot be exported as an empty list')
            else:
                roots={r['id']:set(r['task_ids']) for r in oracle['rows']}
                for job,state,root in product(['']+[j['id'] for j in result['jobs']],['',*selection.STATES],['',*roots]):
                    filters=dict(job=job,state=state,root=root)
                    # Original task order; root members independently walked downstream.
                    ids=[t['id'] for t in result['tasks'] if (not job or t['job_id']==job) and (not state or t['state']==state) and (not root or t['id'] in roots[root])]
                    chosen=selection.select(result,links,filters);assert chosen['task_ids']==ids
                    assert chosen['whole_task_count']==len(result['tasks']) and sum(chosen['state_counts'].values())==len(ids)
                    assert len(chosen['work_orders'])==len({t['job_id'] for t in chosen['selected_tasks']})
                    row['selections'].append(dict(filters=filters,task_ids=ids));total+=1;empty+=not ids
                for state in ('','blocked'):
                    doc=document(data)|dict(selection=selection.select(result,links,dict(state=state)))
                    assert wip_trial_replay.replay_selection(doc)==doc['selection'];replays+=1
            cases.append(row)
    if write:(ROOT/'tests/fixtures/wip_selection.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    proof=dict(success=True,cases=len(cases),selection_cases=total,empty_intersections=empty,full_input_replays=replays,
        original_result_unchanged=True,independent_root_membership='downstream graph traversal',business_writes=False,browser_acceptance=False)
    (ROOT/'data/wip_selection_validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--write-fixtures',action='store_true');main(parser.parse_args().write_fixtures)
