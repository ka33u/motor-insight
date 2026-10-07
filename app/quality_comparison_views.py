import json
from django.db import transaction
from . import quality_comparison as comparison
from .models import AuditEvent
from .views import api,reply
from .quality_views import csv_reply

@api()
def board(request):
    data,_=comparison.context(request.GET);return reply(data)

@api()
def samples(request):
    data,rows=comparison.context(request.GET,('group','kind','revision','page'))
    chosen,selected=comparison.selection(data,rows,request.GET)
    page=int(request.GET.get('page','1'))
    if not 1<=page<=100000:raise ValueError('页码不可用')
    return reply({'rows':chosen[(page-1)*30:page*30],'total':len(chosen),'page':page,'size':30,'selection':selected,'revision':data['revision']})

@api()
@transaction.atomic
def export(request):
    data,rows=comparison.context(request.GET,('group','kind','revision','mode'))
    chosen,selected=comparison.selection(data,rows,request.GET)
    mode=request.GET.get('mode','summary')
    result=[['同条件分布比较 · 合成模拟数据','截止',data['as_of']],['比较定义',json.dumps(data['config'],ensure_ascii=False)],
            ['规范',json.dumps(data['spec'],ensure_ascii=False)],['说明',data['notice']],['样本规则',data['sample_note']],
            ['排除',json.dumps(data['excluded'],ensure_ascii=False)],['计算依据',data['revision']]]
    if mode=='summary':
        if selected['group'] or selected['kind']!='all':raise ValueError('汇总导出应包含完整比较范围')
        fields=['n','unique_units','outside','min','q1','median','q3','max','iqr','lower_fence','upper_fence','lower_whisker','upper_whisker','mean','sample_stddev','outliers']
        result.append(['类型',data['compare_label'],'测量次数','唯一SN','规范超限','最小值','Q1','中位数','Q3','最大值','IQR','下围栏','上围栏','下须','上须','均值','样本标准差','按本行范围围栏识别的离群','二值0条数','二值1条数','单位'])
        for kind,group in [('全范围重算',{'label':'全部范围',**data['overall']})]+[('分组',g) for g in data['groups']]:
            counts={v['value']:v['count'] for v in group['binary_counts']}
            result.append([kind,group['label'],*[group[k] for k in fields],counts.get(0),counts.get(1),data['spec']['unit']])
        count=len(data['groups'])+1
    elif mode=='samples':
        result.append(['样本选择',json.dumps(selected,ensure_ascii=False)])
        result.append(['结果号','SN','会话号','分组','工单','定子批次','转子批次','装配日期','检测时间','设备','环境温度℃','数值','单位','规范判定','组内统计离群'])
        fields=['id','unit_id','session_id','group_label','work_order_id','stator_batch','rotor_batch','assembly_day','tested','equipment_id','temperature_c','value','unit','result','statistical_outlier']
        result.extend([[r.get(k) for k in fields] for r in chosen]);count=len(chosen)
    else:raise ValueError('比较导出类型不可用')
    AuditEvent.objects.create(action='quality.comparison_export',actor=request.user.username,object_type='QualityComparison',object_id=data['spec']['id'],detail={'config':data['config'],'mode':mode,'selection':selected,'rows':count,'revision':data['revision']})
    return csv_reply(result,'quality-comparison-'+mode)
