"""Reconstruct exported results without business writes or private employee names."""
from collections import defaultdict
from . import finite_schedule,crew_schedule,joint_schedule,wip_trial
from .finite_schedule_schema import DATASETS as RESOURCE
from .crew_schedule_schema import DATASETS as CREW
from .joint_schedule_schema import DATASETS as JOINT


def context(doc):
    if doc.get('format')!='motor-wip-remainder-trial-v1':raise ValueError('导出格式无效')
    refs=defaultdict(dict,{ds:{r['id']:r.copy() for r in rows} for ds,rows in doc['references'].items()})
    for ds in ('employees','materials'):
        for r in refs[ds].values():r['name']=r['id']
    for r in refs['production_resources'].values():r['station']=r['id']
    refs['wip_trial_studies']={r['id']:r for r in doc['version_history']}
    p=doc['parent_inputs'];policy=doc['result']['policy']
    rt={ds:p[ds] for ds in RESOURCE[1:]};base=dict(result=finite_schedule.analyze(p[RESOURCE[0]][0],rt,refs,policy),tables=rt)
    ct={ds:p[ds] for ds in CREW[1:]};parent=dict(result=crew_schedule.analyze(p[CREW[0]][0],ct,base,refs),tables=ct,base=base)
    jt={ds:p[ds] for ds in JOINT[1:]};joint=dict(result=joint_schedule.analyze(p[JOINT[0]][0],jt,parent,refs),tables=jt,parent=parent)
    study=doc['inputs']['study'];tables={ds:rows for ds,rows in doc['inputs'].items() if ds!='study'}
    result=wip_trial.analyze(study,tables,joint,refs,doc['as_of'])
    return dict(result=result,joint_context=joint,tables=tables,references=doc['references'],version_history=doc['version_history'])


def replay(doc):
    return context(doc)['result']


def replay_decision(doc):
    from .wip_trial_decision import build
    current=context(doc)
    if current['result']!=doc['result']:raise ValueError('导出结果与完整输入重算不一致')
    return build(current,doc['task_id'],doc['as_of'])


def replay_selection(doc):
    from .wip_trial_selection import select
    current=context(doc)
    if current['result']!=doc['result']:raise ValueError('导出结果与完整输入重算不一致')
    chosen=select(current['result'],current['tables']['wip_trial_jobs'],doc['selection']['filters'])
    if chosen!=doc['selection']:raise ValueError('筛选清单、定义或摘要与完整输入重算不一致')
    return chosen
