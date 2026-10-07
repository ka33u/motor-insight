"""Bootstrap demo accounts/metadata, then ingest business data ONLY from XLSX."""
import os,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.contrib.auth.models import User,Group
from app.models import CodingRule,AnalysisModel,Topic,Record
from app.ingestion import stage_file,commit_batch
from app.access import ROLES
from app.schema import SCHEMAS

def metadata():
    for role in ROLES:
        group,_=Group.objects.get_or_create(name=role)
        u,created=User.objects.get_or_create(username='demo_'+role,defaults={'is_staff':role=='admin'})
        if created:u.set_password('MotorDemo!2026');u.save()
        u.groups.add(group)
    for key,name,prefix,width,fmt,period in [('motor_sn','整机序列号','M',6,'%y%m%d','day'),('work_order','生产工单','MO',6,'%y%m','month'),('quality_issue','质量不合格单','NCR',5,'%y%m','month'),('custom_part','定制物料','CT',6,'','never')]:
        CodingRule.objects.get_or_create(key=key,defaults={'name':name,'prefix':prefix,'width':width,'date_format':fmt,'reset_period':period,'separator':'-'})
    defs=[
        ('订单状态分布','orders','status','count',None,'bar','经营 / 销售'),
        ('产品族配置数量','products','family','count',None,'donut','经营 / 销售'),
        ('交付计划数量','delivery_plans','due','sum','qty','line','订单交付'),
        ('每日发货台数','shipments','shipped','sum','qty','line','订单交付'),
        ('每日装配台数','units','assembly_at','count',None,'line','生产执行'),
        ('工序报工事件','operations','process','count',None,'bar','生产执行'),
        ('检测会话结论','test_sessions','result','count',None,'donut','终检质量'),
        ('不合格处置状态','nonconformities','status','count',None,'bar','终检质量'),
        ('来料检验结论','incoming_inspections','result','count',None,'bar','采购供应'),
        ('采购行执行状态','purchase_lines','status','count',None,'donut','采购供应'),
        ('库存业务笔数','inventory_movements','movement','count',None,'bar','仓储物流'),
        ('承运商发货台数','shipments','carrier','sum','qty','bar','仓储物流'),
        ('研发项目状态','projects','status','count',None,'bar','研发工艺'),
        ('工艺路线标准分钟','routes','process','avg','minutes','bar','研发工艺'),
        ('维修工单状态','maintenance','status','count',None,'bar','设备工装'),
        ('停机原因次数','downtime','reason','count',None,'bar','设备工装'),
        ('生产与间接工时','attendance','date','sum','productive_hours','line','人员工时'),
        ('技能授权分布','skills','process','count',None,'bar','人员工时'),
        ('暂估成本构成（分）','costs','category','sum','amount_cents','bar','成本资金'),
        ('开票未税金额（分）','invoices','issued','sum','net_cents','line','成本资金'),
        ('车间用电量（kWh）','energy','workshop','sum','kwh','bar','能源安环'),
        ('安环整改状态','ehs','status','count',None,'donut','能源安环'),
        ('售后问题分布','service','failure','count',None,'bar','售后服务'),
        ('售后处理状态','service','status','count',None,'donut','售后服务')]
    topics={}
    for name,dataset,dimension,agg,field,chart,topic in defs:
        grain='day' if dimension in ['assembly_at','shipped','issued'] else 'value'
        definition={'dimension':dimension,'grain':grain,'metrics':[{'agg':agg,'field':field}],'filters':[],'chart':chart,'sort':'dimension'}
        m,_=AnalysisModel.objects.get_or_create(name=name,owner='system',defaults={'dataset':dataset,'definition':definition,'is_public':True})
        topics.setdefault(topic,[]).append({'model_id':m.pk,'span':1})
    for name,layout in topics.items():Topic.objects.get_or_create(name=name,owner='system',defaults={'description':'模拟数据专题；卡片口径和来源可检查，可复制模型构建自己的专题。','layout':layout,'is_public':True})
    source=ROOT.parent/'research/bi_design.json'
    if source.exists() and not (ROOT/'data/bi_design.json').exists():(ROOT/'data/bi_design.json').write_text(source.read_text())

if __name__=='__main__':
    metadata()
    files=sorted((ROOT/'outputs').glob('*/*.xlsx'))
    expected={s['department']+'_模拟.xlsx' for s in SCHEMAS.values()}
    if len(files)!=len(expected) or {p.name for p in files}!=expected:raise RuntimeError(f'部门Excel集合不完整或有重复，预期{len(expected)}份，实际{len(files)}；请检查文件名与来源目录')
    report=[]
    for path in files:
        batch,repeated=stage_file(path)
        if not repeated:batch=commit_batch(batch.pk)
        result={'filename':path.name,'batch':str(batch.pk),'status':batch.status,'summary':batch.summary,'repeated':repeated};report.append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        if batch.summary.get('invalid') or batch.summary.get('conflict'):raise RuntimeError('种子文件存在隔离记录，停止导入以检查')
    output={'files':report,'total_records':Record.objects.count(),'business_source':'XLSX files exclusively'}
    (ROOT/'data/import_validation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2));print('RECORDS',output['total_records'])
