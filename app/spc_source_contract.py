"""Row contracts only; analytical eligibility also checks relationships/order."""
from datetime import datetime
import math


def issues(dataset,row):
    out=[]
    def add(field,message):out.append(dict(code='SPC_SOURCE',field=field,message=message))
    def positive(field):
        v=row.get(field)
        if type(v) is int and v<=0:add(field,'必须为正整数')
    for field in ('started','finished','measured','registered','occurred'):
        value=row.get(field)
        if value:
            try:
                time=datetime.fromisoformat(value)
                if time.tzinfo is not None or time.isoformat()!=value:raise ValueError()
            except (ValueError,TypeError):add(field,'使用统一厂内时间，格式应为YYYY-MM-DDTHH:MM:SS')
    if dataset=='spc_studies':
        for f in ('expected_points','baseline_end'):positive(f)
        if type(row.get('expected_points')) is int and type(row.get('baseline_end')) is int and row['baseline_end']>row['expected_points']:add('baseline_end','基线末序号不能超过计划点数')
        for f,allowed in [('status',{'采集中','已结束'}),('method',{'I_MR','待选型'}),('order_basis',{'设备计数（模拟）','人工顺序登记（模拟）','未知'})]:
            if row.get(f) and row[f] not in allowed:add(f,'登记值不在当前支持范围内')
        if row.get('status')=='已结束' and not row.get('finished'):add('finished','结束试验必须记录结束时间')
        if row.get('started') and row.get('finished'):
            try:
                if datetime.fromisoformat(row['started'])>=datetime.fromisoformat(row['finished']):add('finished','结束时间必须晚于开始')
            except (TypeError,ValueError):pass
    elif dataset=='spc_observations':
        for f in ('sequence','replicate'):positive(f)
        if row.get('state') and row['state'] not in {'有效','缺测','待核查','作废'}:add('state','观测状态不可用')
        value=row.get('value')
        finite=type(value) in (int,float) and math.isfinite(value)
        if row.get('state')=='有效' and not finite:add('value','有效观测需要有限数值，零是有效数值')
        if row.get('state')=='缺测' and value is not None:add('value','缺测应留空，不能同时登记实测数值')
        if row.get('measured') and row.get('registered'):
            try:
                if datetime.fromisoformat(row['registered'])<datetime.fromisoformat(row['measured']):add('registered','登记不能早于实际测量')
            except (TypeError,ValueError):pass
    elif dataset=='spc_events':positive('sequence')
    return out
