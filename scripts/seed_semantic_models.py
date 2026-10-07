"""Add governed cross-table examples without replacing user-owned content."""
import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.db import transaction
from app.models import AnalysisModel,Topic,AuditEvent

MODEL_SPECS=[
 ('客户订单金额（分）','bi_order_lines','customer','sum','order_net_cents',None,'bar','经营 / 销售'),
 ('产品族按期足量交付率（%）','bi_order_lines','family','ratio','on_time_plan_count','due_plan_count','bar','订单交付'),
 ('客户逾期未交台数','bi_order_lines','customer','sum','overdue_qty',None,'bar','订单交付'),
 ('产品族装配完成率（%）','bi_work_orders','family','ratio','produced_qty','planned_qty','bar','生产执行'),
 ('工单未完成装配台数','bi_work_orders','id','sum','pending_qty',None,'bar','生产执行'),
 ('产品族首检合格率（%）','bi_units','family','ratio','first_pass_count','first_tested_count','bar','终检质量'),
 ('整机最新检测状态','bi_units','latest_result','count',None,None,'donut','终检质量'),
 ('供应商按期足量到货率（%）','bi_purchase','supplier','ratio','on_time_line_count','due_line_count','bar','采购供应'),
 ('采购缺口明细（分物料）','bi_purchase','material','sum','overdue_qty',None,'table','采购供应'),
 ('库存参考金额构成（分）','bi_inventory','category','sum','reference_value_cents',None,'bar','仓储物流'),
 ('库存余额（分计量单位）','bi_inventory','unit','sum','balance_qty',None,'table','仓储物流'),
 ('产品族暂估成本（分）','bi_work_orders','family','sum','total_cost_cents',None,'bar','成本资金'),
 ('未核销应收账龄（分）','bi_receivables','aging_bucket','sum','balance_cents',None,'bar','成本资金'),
 ('车间去重停机分钟','bi_equipment_day','workshop','sum','downtime_minutes',None,'bar','设备工装'),
 ('车间能源日费用（分）','bi_energy_day','date','sum','energy_cost_cents',None,'line','能源安环'),
 ('工序排班占用率（%）','bi_resource_day','process','ratio','busy_minutes','available_minutes','bar','资源与工时'),
 ('资源日作业分钟','bi_resource_day','date','sum','busy_minutes',None,'line','资源与工时'),
 ('作业工时分类（分钟）','labor_entries','activity','sum','minutes',None,'bar','资源与工时')]

def seed():
    added={}
    with transaction.atomic():
        for name,dataset,dimension,agg,field,denominator,chart,topic in MODEL_SPECS:
            metric={'agg':agg,'field':field}
            if denominator:metric['denominator']=denominator
            definition={'dimension':dimension,'grain':'value','metrics':[metric],'filters':[],'chart':chart,'sort':'dimension'}
            model,created=AnalysisModel.objects.get_or_create(name=name,owner='system',defaults={'dataset':dataset,'definition':definition,'is_public':True})
            added.setdefault(topic,[]).append(model.pk)
        for name,models in added.items():
            if name=='资源与工时':
                Topic.objects.get_or_create(name=name,owner='system',defaults={'description':'独立资源位、排班停机与工时成本；点击导航中的资源与工时查看时间轴。全部为模拟数据。','layout':[{'model_id':i,'span':1} for i in models],'is_public':True})
            topic=Topic.objects.filter(name=name,owner='system',version=1).first()
            if not topic:continue
            present={c['model_id'] for c in topic.layout};new=[{'model_id':i,'span':1} for i in models if i not in present]
            if new:
                topic.layout+=new;topic.version+=1;topic.save()
                AuditEvent.objects.create(action='topic.upgrade',object_type='Topic',object_id=str(topic.pk),detail={'reason':'add governed business grain models','models':models,'version':topic.version})
    return len(MODEL_SPECS)

if __name__=='__main__':print('Semantic models ready:',seed())
