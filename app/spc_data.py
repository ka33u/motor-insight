"""Read a fixed study and every referenced fact in one database snapshot."""
from collections import defaultdict
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from . import access,analytics,spc
from .models import Record,AccountAccessState
from .ingestion import fingerprint

TABLES=('spc_studies','spc_observations','spc_events')

def account(user):
    fresh=get_user_model().objects.get(pk=user.pk)
    role=access.role(fresh)
    if role is None:raise PermissionDenied('账号或岗位权限已变化，请重新登录')
    state=AccountAccessState.objects.filter(user=fresh).first()
    return dict(id=fresh.pk,username=fresh.username,role=role,
                groups=sorted(fresh.groups.values_list('name',flat=True)),
                revision=state.revision if state else 0,
                session_epoch=state.session_epoch if state else 0)

def source(record):
    row=record.source_row;batch=row.batch
    if record.values.get('id')!=record.business_key or fingerprint(record.values)!=record.record_hash:
        raise ValueError('来源身份或当前事实摘要待核对：'+record.dataset+'/'+record.business_key)
    if row.dataset!=record.dataset or row.business_key!=record.business_key or row.record_hash!=record.record_hash or row.normalized!=record.values:
        raise ValueError('当前事实与导入行待核对：'+record.dataset+'/'+record.business_key)
    return dict(dataset=record.dataset,key=record.business_key,revision=record.revision,
                record_hash=record.record_hash,batch_id=str(batch.pk),filename=batch.filename,
                file_hash=batch.file_hash,sheet=row.sheet,row=row.row_number)

def queryset(dataset):return Record.objects.filter(dataset=dataset).select_related('source_row__batch')

def load(key):
    study_record=queryset('spc_studies').get(business_key=key)
    observations=list(queryset('spc_observations').filter(values__study_id=key).order_by('business_key'))
    events=list(queryset('spc_events').filter(values__study_id=key).order_by('business_key'))
    if len(observations)>spc.MAX_POINTS:raise ValueError('当前试算最多读取10000条观测，请拆分受控试验')
    study=study_record.values;references=defaultdict(set)
    for dataset,field in [('products','product_id'),('test_specs','spec_id'),('equipment','equipment_id'),('employees','owner_id')]:
        if study.get(field):references[dataset].add(study[field])
    for r in observations:
        for dataset,field in [('units','unit_id'),('employees','operator_id')]:
            if r.values.get(field):references[dataset].add(r.values[field])
    for r in events:
        if r.values.get('operator_id'):references['employees'].add(r.values['operator_id'])
    records=[study_record,*observations,*events];index=defaultdict(dict);missing=[]
    for dataset,keys in sorted(references.items()):
        ordered=sorted(keys)
        for offset in range(0,len(ordered),400):
            found=list(queryset(dataset).filter(business_key__in=ordered[offset:offset+400]));records.extend(found)
            index[dataset].update({r.business_key:r.values for r in found})
        missing.extend(dict(dataset=dataset,key=k,missing=True) for k in ordered if k not in index[dataset])
    manifest=sorted([source(r) for r in records]+missing,key=lambda s:(s['dataset'],s['key']))
    facts=sorted([dict(dataset=r.dataset,key=r.business_key,values=r.values) for r in records],key=lambda r:(r['dataset'],r['key']))
    result=spc.analyze(study,[r.values for r in observations],index['test_specs'].get(study.get('spec_id')),
                       index['units'],[r.values for r in events],analytics.AS_OF)
    if any(s['dataset'] in {'products','equipment','employees'} for s in missing):
        result['issues'].append('配置、设备或采样人员引用缺失，控制限暂停');result['limits']=None;result['state']='paused'
        for p in result['points']:p['i_signal']=None;p['mr_signal']=None
        result['signal_counts']={seg:dict(i=0,mr=0) for seg in ('baseline','monitor')}
    return dict(result=result,sources=manifest,source_hash=spc.digest(dict(facts=facts,sources=manifest)),
                rule_hash=spc.rule_hash(),product=index['products'].get(study.get('product_id')),
                equipment=index['equipment'].get(study.get('equipment_id')))

def point_sources(context,point):
    study=context['result']['study']
    refs={('spc_studies',study['id']),('spc_observations',point['id']),('units',point.get('unit_id')),
          ('test_specs',study.get('spec_id')),('products',study.get('product_id')),
          ('equipment',study.get('equipment_id')),('employees',point.get('operator_id')),
          ('employees',study.get('owner_id'))}
    # MR evidence includes the predecessor only when an actual adjacent pair exists.
    if point.get('mr') is not None:
        before=next((p for p in context['result']['points'] if p.get('sequence')==point['sequence']-1),None)
        if before:refs.update({('spc_observations',before['id']),('units',before.get('unit_id'))})
    refs.update(('spc_events',e['id']) for e in context['result']['events'] if e.get('sequence')==point.get('sequence'))
    return [s for s in context['sources'] if (s['dataset'],s['key']) in refs]
