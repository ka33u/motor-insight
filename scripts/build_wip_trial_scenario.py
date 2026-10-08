"""Author synthetic inputs as a JSON intermediate for the normal Excel importer."""
import json,os,sys
from copy import deepcopy
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app import joint_schedule_data,finite_schedule,crew_schedule,joint_schedule,wip_trial,wip_trial_contract as contract
from app.finite_schedule_schema import DATASETS as RESOURCE
from app.crew_schedule_schema import DATASETS as CREW
from app.joint_schedule_schema import DATASETS as JOINT
from app.wip_trial_schema import DATASETS as WIP

CUT='2026-10-01T18:00:00'
BASIS='合成模拟；供核对输入与规则，不是现场盘点、业务批准或正式派工。'


def main():
    old=joint_schedule_data.load('MP-261002-001');oldtables=wip_trial.parent_tables(old)
    sourcejob=oldtables['schedule_jobs'][0];sourceid=sourcejob['id'];pid=sourcejob['product_id']
    originaltasks=[r for r in oldtables['schedule_tasks'] if r['job_id']==sourceid];tids={r['id'] for r in originaltasks}
    refs=defaultdict(dict)
    for ds in set(contract.REFERENCE_FIELDS)|{'route_dependencies'}:
        if ds in ('work_orders','operations','batches','units'):continue
        rows=Record.objects.filter(dataset=ds)
        if ds in ('products','routes','route_dependencies','bom'):rows=rows.filter(business_key=pid) if ds=='products' else rows.filter(values__product_id=pid)
        refs[ds]={r.business_key:r.values for r in rows}
    product=refs['products'][pid]
    table={ds:[] for ds in ('orders','order_lines','work_orders','allocations','batches','operations','wip_lots','wip_openings',*RESOURCE,*CREW,*JOINT,*WIP)}
    mapping={'SP-261002-001':'SP-261001-W001','CR-261002-001':'CR-261001-W001','MP-261002-001':'MP-261001-W001'}
    def common(row):
        return {k:next((v.replace(a,b,1) for a,b in mapping.items() if isinstance(v,str) and v.startswith(a)),v) for k,v in row.items()}
    for ds in ('schedule_windows','schedule_blocks','crew_credentials','crew_windows','crew_blocks'):
        table[ds]=[common(r) for r in oldtables[ds]]
    for r in table['crew_credentials']:r['valid_from']=CUT
    for field,ds in [('resource_id','schedule_windows'),('employee_id','crew_windows')]:
        for n,ident in enumerate(sorted({r[field] for r in table[ds]}),1):
            table[ds].append(dict(id=f'WIP-CARRY-{ds}-{n:03d}',study_id=mapping['SP-261002-001' if ds.startswith('schedule') else 'CR-261002-001'],**{field:ident},started=CUT,finished='2026-10-01T20:00:00',basis=BASIS+' 截止后的独立连续续作窗口。'))
    bindings=[r for r in oldtables['joint_bindings'] if r['bom_id'] in refs['bom']]
    table['joint_bindings']=[common(r) for r in bindings];bindingmap={a['id']:b['id'] for a,b in zip(bindings,table['joint_bindings'])}
    line=Record.objects.filter(dataset='order_lines',values__product_id=pid).order_by('business_key').first().values
    order=Record.objects.get(dataset='orders',business_key=line['order_id']).values
    locations={k:Record.objects.get(dataset='wip_locations',business_key='ZW.LOC.000') for k in ('定子','转子')}
    jobs=[];taskmap={}
    for n in (1,2):
        jid=f'SP-261001-W001-B{n:03d}';wo=f'MO-261001-W{n:03d}';oid=f'SO20261001W{n:03d}';lid=oid+'-001'
        job=dict(sourcejob,id=jid,study_id=mapping['SP-261002-001'],released=CUT,priority=n,reference='SIM-WIP-'+wo);jobs.append(job);table['schedule_jobs'].append(job)
        remap={r['id']:r['id'].replace(sourceid,jid) for r in originaltasks};taskmap[n]=remap
        table['schedule_tasks'] += [dict(r,id=remap[r['id']],job_id=jid) for r in originaltasks]
        for ds in ('schedule_edges','schedule_options','crew_candidates'):
            source=[r for r in oldtables[ds] if r.get('task_id',r.get('from_task_id')) in tids]
            for i,r in enumerate(source,1):
                x=common(r);x['id']=f'WIP-{ds}-B{n}-{i:03d}'
                for field in ('task_id','from_task_id','to_task_id'):
                    if field in x:x[field]=remap[r[field]]
                table[ds].append(x)
        for i,r in enumerate(oldtables['joint_demands'],1):
            if r['job_id']==sourceid:table['joint_demands'].append(dict(r,id=f'WIP-DEMAND-B{n}-{i:03d}',study_id=mapping['MP-261002-001'],job_id=jid,binding_id=bindingmap[r['binding_id']]))
        table['orders'].append(dict(order,id=oid,order_date='2026-10-01',status='执行中',customer_po='SIM-WIP-PO-'+str(n)))
        table['order_lines'].append(dict(line,id=lid,order_id=oid,qty=6,original_due='2026-10-03',due='2026-10-03',change_reason=None,custom_requirement='在制余量联立试排模拟，保留原配置。'))
        table['work_orders'].append(dict(id=wo,product_id=pid,planned_qty=6,planned_start='2026-10-01',planned_end='2026-10-03',priority='普通',status='生产中',bom_version=product['bom_version'],route_version=product['route_version']))
        table['allocations'].append(dict(id='FP-WIP-'+str(n),work_order_id=wo,order_line_id=lid,qty=6,effective='2026-10-01'))
        for kind,short in [('定子','DZ'),('转子','ZZ')]:
            bid=f'{short}-261001-W{n:03d}';lot='ZW-'+bid
            table['batches'].append(dict(id=bid,work_order_id=wo,kind=kind,qty=6,created='2026-10-01T12:00:00',status='在制',container='BOX-'+bid))
            table['wip_lots'].append(dict(id=lot,product_id=pid,kind=kind,created='2026-10-01T12:00:00',container='BOX-'+bid,note=BASIS))
            table['wip_openings'].append(dict(id='OPEN-'+bid,root_batch_id=bid,lot_id=lot,location_id=locations[kind].business_key,qty=6,occurred='2026-10-01T17:55:00',recorded=CUT,owner_id='E00001',reference='SIM-COUNT-'+bid,note=BASIS+' 定子和转子分别登记，不能相加为整机台数。'))
    mids={refs['bom'][r['bom_id']]['material_id'] for r in bindings}
    for i,mid in enumerate(sorted(mids),1):
        table['joint_supplies'].append(dict(id=f'WIP-PARENT-STOCK-{i:02d}',study_id=mapping['MP-261002-001'],material_id=mid,lot=f'SIM-WIP-PARENT-{i:02d}',unit=refs['materials'][mid]['unit'],qty=1000,unavailable_qty=0,available_from=CUT,status='可预留',kind='期初假设',reference='SIM-PARENT-ONLY',basis=BASIS+' 原整批参考池，不进入剩余试排。'))
    for ds,fields in [('schedule_studies',{'job_count':'schedule_jobs','task_count':'schedule_tasks','edge_count':'schedule_edges','option_count':'schedule_options','window_count':'schedule_windows','block_count':'schedule_blocks'}),('crew_studies',{'credential_count':'crew_credentials','candidate_count':'crew_candidates','window_count':'crew_windows','block_count':'crew_blocks'}),('joint_studies',{'binding_count':'joint_bindings','demand_count':'joint_demands','supply_count':'joint_supplies'})]:
        x=common(oldtables[ds][0]);x.update(name='两工单在制试排原始假设',**{f:len(table[d]) for f,d in fields.items()})
        if ds=='schedule_studies':x.update(baseline=CUT,scope='2张完整工单，每单6台；原始整批参考与余量试排分开。',assumptions=BASIS+' 保留原工艺与人机候选；另声明截止后2小时续作窗口。')
        elif ds=='joint_studies':x.update(scope='同配置两工单12台；独立参考物料池，不代表余料。',assumptions=BASIS)
        table[ds]=[x]
    for ds in ('work_orders','batches'):refs[ds].update({r['id']:r for r in table[ds]})
    # Four genuine source reports, then explicit task-to-report mappings.
    reports={}
    for n,index,start,finish,good,status in [(1,0,'14:00:00','15:00:00',6,'完成'),(1,1,'15:00:00','16:00:00',6,'完成'),(1,2,'17:45:00',None,3,'进行中'),(2,0,'16:05:00','17:00:00',3,'中断')]:
        tid=taskmap[n][originaltasks[index]['id']];task=next(r for r in table['schedule_tasks'] if r['id']==tid);route=refs['routes'][task['route_id']]
        option=next(r for r in table['schedule_options'] if r['task_id']==tid);candidate=next(r for r in table['crew_candidates'] if r['task_id']==tid)
        credential=next(r for r in table['crew_credentials'] if r['id']==candidate['credential_id']);person=refs['skills'][credential['skill_id']]['employee_id'];res=refs['production_resources'][option['resource_id']]
        op=dict(id=f'BG-WIP-B{n}-T{index+1:02d}',work_order_id=f'MO-261001-W{n:03d}',object_type='生产批次',object_id=f'{"DZ" if route["branch"]=="定子" else "ZZ"}-261001-W{n:03d}',process=route['process'],equipment_id=res['equipment_id'],employee_id=person,resource_id=res['id'],started='2026-10-01T'+start,finished='2026-10-01T'+finish if finish else None,input_qty=6,good_qty=good,scrap_qty=0,rework_qty=0,status=status)
        table['operations'].append(op);refs['operations'][op['id']]=op;reports[tid]=op
    rt={ds:table[ds] for ds in RESOURCE[1:]};ct={ds:table[ds] for ds in CREW[1:]};jt={ds:table[ds] for ds in JOINT[1:]}
    base=dict(result=finite_schedule.analyze(table[RESOURCE[0]][0],rt,refs),tables=rt)
    parent=dict(result=crew_schedule.analyze(table[CREW[0]][0],ct,base,refs),tables=ct,base=base)
    joint=dict(result=joint_schedule.analyze(table[JOINT[0]][0],jt,parent,refs),tables=jt,parent=parent)
    assert joint['result']['state']=='trial',joint['result']['issues']
    profiles=[]
    names=['已完成前序与在制续作','排队任务缺料','专属余料不能跨工单','加工中连续窗口不足','报工数量待核对','续作工时更新版本','原始依据变化待重核','已投入量超过剩余定额']
    for n,name in enumerate(names,1):
        sid=f'WR-261001-{n:03d}';s=dict(id=sid,name=name,series='WR-261001-A' if n in (1,6) else f'WR-261001-S{n}',version=2 if n==6 else 1,supersedes_id='WR-261001-001' if n==6 else None,joint_study_id=table['joint_studies'][0]['id'],cutoff=CUT,owner_id='E00001',basis=BASIS+' '+name)
        t={ds:[] for ds in WIP[1:]}
        for i,job in enumerate(jobs,1):t['wip_trial_jobs'].append(dict(id=f'{sid}-J{i}',study_id=sid,job_id=job['id'],work_order_id=f'MO-261001-W{i:03d}',basis=BASIS+' 全工单6台，与独立原批次数量相等。'))
        for i,task in enumerate(table['schedule_tasks'],1):
            op=reports.get(task['id']);state={'完成':'已完成','进行中':'加工中','中断':'中断待续'}[op['status']] if op else '未开始';done=op['good_qty'] if op else 0;rem=task['lot_qty']-done
            minutes=0 if not rem else 12 if state=='加工中' else round(rem*task['unit_minutes'],3)
            p=dict(id=f'{sid}-P{i:03d}',study_id=sid,task_id=task['id'],state=state,operation_id=op['id'] if op else None,completed_qty=done,remaining_qty=rem,remaining_minutes=minutes,recovery_minutes=5 if state=='中断待续' else 0,resource_id=op['resource_id'] if state=='加工中' else None,employee_id=op['employee_id'] if state=='加工中' else None,basis=BASIS+' 加工中剩余12分钟；暂停恢复5分钟；其余按声明每台工时。')
            if n==4 and state=='加工中':p['remaining_minutes']=150
            if n==5 and state=='加工中':p['completed_qty']=2
            if n==6 and state=='加工中':p['remaining_minutes']=18;p['basis']=BASIS+' v2模拟重新测算剩余18分钟，保留v1的12分钟。'
            t['wip_trial_tasks'].append(p)
            for b in table['joint_bindings']:
                if b['route_id']!=task['route_id']:continue
                bom=refs['bom'][b['bom_id']];unit=refs['materials'][bom['material_id']]['unit'];gross=joint_schedule.requirement(rem,bom['qty'],bom['scrap_allowance'],b['quantum']) if rem else 0
                embedded=min(gross,1) if state=='中断待续' else 0
                if n==8 and state=='中断待续':embedded=gross+1
                t['wip_trial_materials'].append(dict(id=f'{sid}-M{len(t["wip_trial_materials"])+1:03d}',study_id=sid,task_id=task['id'],binding_id=b['id'],embedded_qty=float(embedded),required_qty=float(max(0,gross-embedded)),unit=unit,basis=BASIS+' 剩余任务逐行向上取整，扣声明已投入；已投入不是可复用库存。'))
        for i,mid in enumerate(sorted(mids),1):
            unit=refs['materials'][mid]['unit'];qty=1000
            if n==2 and mid==refs['bom']['BOM-00008-02']['material_id']:qty=0
            t['wip_trial_supplies'].append(dict(id=f'{sid}-S{i:02d}',study_id=sid,material_id=mid,lot=f'SIM-WIP-COUNT-{i:02d}',location='SIM-WIP-STORE',unit=unit,qty=qty,unavailable_qty=0,available_from=CUT,status='可投入',kind='线边盘点' if n==3 else '仓库余料',owner_job_id=jobs[0]['id'] if n==3 else None,observed_at=CUT,reference='SIM-COUNT-261001',basis=BASIS+' 独立尚未耗用池，不叠加原整批库存假设。'))
        for f,ds in [('job_count',WIP[1]),('task_count',WIP[2]),('material_count',WIP[3]),('supply_count',WIP[4])]:s[f]=len(t[ds])
        s['reference_hash']=contract.references_hash(wip_trial.parent_tables(joint),refs,t)
        if n==7:s['reference_hash']='0'*64
        s['content_hash']=contract.bundle_hash(s,t)
        refs['wip_trial_studies'][sid]=s
        result=wip_trial.analyze(s,t,joint,refs,CUT)
        assert result['state']==('trial' if n in (1,2,3,6) else 'paused'),(n,result['issues'])
        profiles.append(dict(id=sid,name=name,state=result['state'],summary=result['summary'],issues=result['issues']))
        table['wip_trial_studies'].append(s)
        for ds,rows in t.items():table[ds]+=rows
    # Don't create empty worksheets. Existing templates supply their contracts.
    table={ds:rows for ds,rows in table.items() if rows}
    for ds,rows in table.items():
        assert len({r['id'] for r in rows})==len(rows),ds
        assert not Record.objects.filter(dataset=ds,business_key__in=[r['id'] for r in rows]).exists(),ds+' already imported; authoring is not a reset'
        expected={f['name'] for f in SCHEMAS[ds]['fields']}
        assert all(set(r)==expected for r in rows),(ds,[(set(r)-expected,expected-set(r)) for r in rows[:1]])
    out=dict(synthetic=True,tables=table,schemas={ds:SCHEMAS[ds] for ds in table},profiles=profiles)
    (ROOT/'data/wip_trial_scenario.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(rows=sum(map(len,table.values())),tables={ds:len(rows) for ds,rows in table.items()},profiles=profiles),ensure_ascii=False))


if __name__=='__main__':main()
