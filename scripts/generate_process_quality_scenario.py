"""Detailed synthetic process inspection source; no business database writes."""
import os,sys,json
from pathlib import Path
from datetime import datetime,timedelta
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app.process_quality import ProcessQuality,filters,NEW_TABLES,TABLES
from app.analytics import AS_OF

data={ds:list(Record.objects.filter(dataset=ds).order_by('business_key').values_list('values',flat=True)) for ds in TABLES if ds not in NEW_TABLES}
wo={r['id']:r for r in data['work_orders']};batches={r['id']:r for r in data['batches']};products=data['products'][:8];pids={p['id'] for p in products}
parameters={
 '冲片':[('BURR','毛刺高度','mm',0,.05),('THICKNESS','片厚','mm',.48,.52)],
 '叠压':[('HEIGHT','叠高','mm',79.8,80.2),('RUNOUT','端面跳动','mm',0,.08)],
 '绕线嵌线':[('RESISTANCE','相电阻','Ω',4.8,5.2),('FILL','槽满率','%',65,78)],
 '浸漆固化':[('CURE_TEMP','固化温度点','℃',145,155),('VACUUM','绝对压力点','kPa',15,25)],
 '转子铸铝':[('METAL_TEMP','铝液温度','℃',690,720),('PRESSURE','注射压力','MPa',50,60)],
 '机加工':[('DIAMETER','轴颈尺寸','mm',19.99,20.01),('ROUGHNESS','表面粗糙度','μm',0,1.6)],
 '动平衡':[('BALANCE_A','A端剩余不平衡','g·mm',0,3),('BALANCE_B','B端剩余不平衡','g·mm',0,3)],
 '装配':[('ENDPLAY','轴向游隙','mm',.1,.3),('TORQUE','紧固扭矩','N·m',15,20)],
}
tables={k:[] for k in NEW_TABLES};spec_index={}
for p in products:
    routes=[r for r in data['routes'] if r['product_id']==p['id'] and r['version']==p['route_version'] and r['process'] in parameters]
    for r in routes:
        for version,effective,expires in [('PQ-A.01','2026-09-01','2026-09-20'),('PQ-A.02','2026-09-20',None)]:
            for code,name,unit,lo,hi in parameters[r['process']]:
                shift=(int(p['id'][3:8])-1)*.5 if code in ['HEIGHT','DIAMETER'] else 0
                low=round(lo+shift,4);high=round(hi+shift-(hi-lo)*.05*(version.endswith('02')),4)
                sid=f'CSGF-{len(tables["process_specs"])+1:05d}'
                s=dict(id=sid,product_id=p['id'],route_version=p['route_version'],process=r['process'],branch=r['branch'],version=version,parameter=code,name=name,unit=unit,lsl=low,usl=high,mandatory=True,effective=effective,expires=expires,basis='合成模拟限值，仅验证数据与页面；不是图纸、公差或工艺批准依据。失效日不包含在有效区间内。')
                tables['process_specs'].append(s);spec_index[(p['id'],r['process'],r['branch'],version,code)]=s
grouped=defaultdict(list)
for op in data['operations']:
    w=wo[op['work_order_id']]
    if w['product_id'] not in pids or op['process'] not in parameters:continue
    branch='整机' if op['object_type']=='整机' else batches[op['object_id']]['kind']
    grouped[(w['product_id'],op['process'],branch)].append(op)
chosen=[op for key in sorted(grouped) for op in sorted(grouped[key],key=lambda r:(r['started'],r['id']))[:4]]
inspectors=[r['id'] for r in data['employees'] if r['department_id']=='D07' and r['active']]
for op in chosen:
    pid=wo[op['work_order_id']]['product_id'];branch='整机' if op['object_type']=='整机' else batches[op['object_id']]['kind'];start=datetime.fromisoformat(op['started']);seconds=(datetime.fromisoformat(op['finished'])-start).total_seconds()
    for stage,fraction in [('首件',.2),('巡检',.7)]:
        n=len(tables['process_check_plans'])+1;due=start+timedelta(seconds=int(seconds*fraction));version='PQ-A.01' if due.date().isoformat()<'2026-09-20' else 'PQ-A.02'
        plan=dict(id=f'GJH26-{n:05d}',operation_id=op['id'],stage=stage,due=due.isoformat(),spec_version=version,basis='合成应检计划；本批报工取一个首件样本及一个巡检样本，不覆盖其他未建计划的报工，不构成投产批准。')
        tables['process_check_plans'].append(plan)
        if n%17==0:continue
        attempts=2 if n%23==0 or n%29==0 else 1
        for attempt in range(attempts):
            cid=f'GJ26-{n:05d}-{attempt+1:02d}';voided=n%29==0 and attempt==1;when=due+timedelta(seconds=int(seconds*.12)*attempt)
            tables['process_checks'].append(dict(id=cid,plan_id=plan['id'],sample=f'YB26-{n:05d}',checked=when.isoformat(),inspector_id=inspectors[n%len(inspectors)],voided=voided,reason='模拟作废的重复采集，保留原值' if voided else '模拟复查，不覆盖首检' if attempt else '模拟单位错录待核对' if n%37==0 else '模拟首件/巡检记录；检验结果由参数计算，不代替批准'))
            for j,(code,name,unit,lo,hi) in enumerate(parameters[op['process']],1):
                if n%19==0 and j==2 and attempt==0:continue
                s=spec_index[pid,op['process'],branch,version,code];span=s['usl']-s['lsl']
                value=s['lsl']+span*(.25+((n+j)%7)*.07)
                if j==1 and attempt==0 and (n%13==0 or n%23==0):value=s['usl']+span*.2
                tables['process_readings'].append(dict(id=f'CS26-{n:05d}-{attempt+1:02d}-{j:02d}',check_id=cid,spec_id=s['id'],value=round(value,4),unit='未知单位' if n%37==0 and j==1 and attempt==0 else unit,instrument=f'MON-{op["equipment_id"]}-{j:02d}（模拟采集点）'))
board=ProcessQuality({**data,**tables},filters({}));summary=board.summary(board.selected())
assert set(r['process'] for r in board.selected())==set(parameters)
assert summary['pending'] and summary['missing'] and summary['out'] and summary['attention']
output={'notice':'全部为合成模拟数据。8个产品配置、8道工序，限值为演练设定，非生产标准；每个选定报工建立首件和巡检计划，含未检、漏项、超限、复查、作废和单位错录。计划仅覆盖本文件列明的报工，不表示全厂覆盖；原报工和生产数量不变。','as_of':AS_OF,'schema_version':1,'tables':tables,'schemas':{k:SCHEMAS[k] for k in NEW_TABLES},'controls':{'operations':len(chosen),'rows':sum(map(len,tables.values())),'summary':summary,'types':dict(Counter(r['state'] for r in board.selected()))}}
(ROOT/'data/process_quality_scenario.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
print(json.dumps(output['controls'],ensure_ascii=False))
