"""Independent original-root memberships from normally imported simulated trials."""
import argparse,json,os,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import wip_trial_data


def expected(result,links):
    if result['state']!='trial':return dict(state='paused',summary=None,rows=[])
    tasks={t['id']:t for t in result['tasks']};jobs={j['id']:j for j in result['jobs']};works={r['job_id']:r['work_order_id'] for r in links}
    root={key:t for key,t in tasks.items() if t['root_tasks']==[key]};members=defaultdict(set)
    # Walk downstream from each original blocking node; a successful task cannot
    # be its blocked descendant. This differs from the JS predecessor-union walk.
    children=defaultdict(list)
    for t in tasks.values():
        for p in t['predecessors']:children[p].append(t['id'])
    for key in root:
        queue=[key]
        for task in queue:
            if task in members[key]:continue
            assert tasks[task]['state']=='blocked';members[key].add(task);queue.extend(children[task])
    for key,t in tasks.items():assert set(t['root_tasks'])=={r for r,m in members.items() if key in m}
    blocked=[t for t in tasks.values() if t['state']=='blocked'];affected={t['job_id'] for t in blocked};rows=[]
    for key,ids in members.items():
        t=tasks[key];jids=sorted({tasks[i]['job_id'] for i in ids})
        rows.append(dict(id=key,job_id=t['job_id'],work_order_id=works[t['job_id']],process=t['process'],branch=t['branch'],reason=t['reason'],task_ids=sorted(ids),job_ids=jids,
            work_order_ids=[works[i] for i in jids],tasks=len(ids),jobs=len(jids),whole_job_qty=sum(jobs[i]['qty'] for i in jids),earliest_due=min(jobs[i]['due'] for i in jids),overlapping_tasks=sum(len(tasks[i]['root_tasks'])>1 for i in ids)))
    rows.sort(key=lambda r:(r['earliest_due'],-r['jobs'],-r['tasks'],r['id']))
    return dict(state='blocked' if rows else 'clear',summary=dict(roots=len(rows),tasks=len(blocked),jobs=len(affected),whole_job_qty=sum(jobs[i]['qty'] for i in affected),overlapping_tasks=sum(len(t['root_tasks'])>1 for t in blocked)),rows=rows)


def main(write=False):
    docs=[];summary=[]
    for n in range(1,9):
        for policy in ('due','priority'):
            c=wip_trial_data.load(f'WR-261001-{n:03}',policy);r=c['result'];links=c['tables']['wip_trial_jobs'];oracle=expected(r,links)
            board={k:r[k] for k in ('state','study','rule_version','policy','summary','tasks','jobs')};board.update(work_orders=links,synthetic=True,receipt='test-only-placeholder')
            docs.append(dict(board=board,expected=oracle));summary.append(dict(study=r['study']['id'],policy=policy,**{k:oracle[k] for k in ('state','summary')}))
    if write:(ROOT/'tests/fixtures/wip_blockers.json').write_text(json.dumps(docs,ensure_ascii=False,indent=2)+'\n')
    proof=dict(success=True,cases=len(docs),independent_method='downstream traversal from original roots; exact task/root membership equality',results=summary,browser_acceptance=False)
    (ROOT/'data/wip_blockers_validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--write-fixtures',action='store_true');main(p.parse_args().write_fixtures)
