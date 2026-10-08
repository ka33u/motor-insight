"""Bounded current records plus complete original trial and cutover source manifests."""
from collections import defaultdict
from . import wip_trial as engine,joint_schedule_data,spc_data,finite_schedule
from .wip_trial_schema import DATASETS
from .wip_trial_contract import REFERENCE_FIELDS


def load(key,policy='due'):
    study=spc_data.queryset('wip_trial_studies').get(business_key=key)
    joint=joint_schedule_data.load(study.values['joint_study_id'],policy)
    records={(study.dataset,study.business_key):study};tables={};refs=defaultdict(dict)
    def remember(rows):
        for row in rows:records[row.dataset,row.business_key]=row;refs[row.dataset][row.business_key]=row.values
    def bounded(query,label):
        rows=list(query.order_by('business_key')[:engine.MAX_ROWS+1])
        if len(rows)>engine.MAX_ROWS:raise ValueError(label+'超过受控规模，未截断试算')
        remember(rows);return rows
    for ds in DATASETS[1:]:
        tables[ds]=[r.values for r in bounded(spc_data.queryset(ds).filter(values__study_id=key),ds)]
    wanted=defaultdict(set)
    for source in joint['sources']:
        if source['dataset'] in REFERENCE_FIELDS:wanted[source['dataset']].add(source['key'])
    wanted['work_orders'].update(r['work_order_id'] for r in tables['wip_trial_jobs'])
    wanted['operations'].update(r['operation_id'] for r in tables['wip_trial_tasks'] if r.get('operation_id'))
    wanted['production_resources'].update(r['resource_id'] for r in tables['wip_trial_tasks'] if r.get('resource_id'))
    wanted['employees'].update(r['employee_id'] for r in tables['wip_trial_tasks'] if r.get('employee_id'))
    wanted['materials'].update(r['material_id'] for r in tables['wip_trial_supplies']);wanted['employees'].add(study.values['owner_id'])
    if study.values.get('supersedes_id'):wanted['wip_trial_studies'].add(study.values['supersedes_id'])
    bounded(spc_data.queryset('wip_trial_studies').filter(values__series=study.values['series']),'版本历史')
    works=sorted(wanted['work_orders'])
    for ds in ('operations','batches','units'):
        bounded(spc_data.queryset(ds).filter(values__work_order_id__in=works),ds)
    for op in refs['operations'].values():
        for ds,field in [('production_resources','resource_id'),('employees','employee_id')]:
            if op.get(field):wanted[ds].add(op[field])
        if op.get('object_type')=='生产批次':wanted['batches'].add(op['object_id'])
        elif op.get('object_type')=='整机':wanted['units'].add(op['object_id'])
    for ds,keys in sorted(wanted.items()):
        keys=sorted(keys-set(refs[ds]))
        for at in range(0,len(keys),200):remember(spc_data.queryset(ds).filter(business_key__in=keys[at:at+200]))
    manifest={(s['dataset'],s['key']):s for s in joint['sources']}
    for k,r in records.items():manifest[k]=spc_data.source(r)|dict(source_row_id=r.source_row_id)
    for ds,keys in wanted.items():
        for missing in keys-set(refs[ds]):manifest[ds,missing]=dict(dataset=ds,key=missing,missing=True)
    sources=[manifest[k] for k in sorted(manifest)]
    from .analytics import AS_OF
    result=engine.analyze(study.values,tables,joint,refs,AS_OF)
    # No raw prices or employee names/pay rates in the public export.
    safe_refs={ds:[{f:r.get(f) for f in fields} for _,r in sorted(refs[ds].items())] for ds,fields in REFERENCE_FIELDS.items()}
    return dict(result=result,version_history=[r for _,r in sorted(refs['wip_trial_studies'].items())],tables=tables,parent_inputs=engine.parent_tables(joint),references=safe_refs,sources=sources,
        source_hash=finite_schedule.digest(dict(parent=joint['source_hash'],sources=sources,
            facts=[dict(dataset=ds,key=k,hash=r.record_hash) for (ds,k),r in sorted(records.items())])),rule_hash=engine.rule_hash(),
        parent_reference=dict(id=joint['result']['study']['id'],summary=joint['result']['summary'],
            notice='原整批假设参考使用原供给及整批取整；本次独立余料与逐任务取整，不提供因果差值。'))
