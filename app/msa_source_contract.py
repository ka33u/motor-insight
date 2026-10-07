"""Row validation; completeness and crossed membership are analytical checks."""
import math
from datetime import datetime
def issues(dataset,row):
 out=[]
 def add(field,message):out.append(dict(code='MSA_SOURCE',field=field,message=message))
 for f in ('started','finished','measured','registered'):
  v=row.get(f)
  if v:
   try:
    t=datetime.fromisoformat(v)
    if t.tzinfo is not None or len(v)!=19 or t.isoformat(timespec='seconds')!=v:raise ValueError()
   except (ValueError,TypeError):add(f,'使用厂内YYYY-MM-DDTHH:MM:SS时间')
 for f in ('part_count','operator_count','repeat_count','repeat','run_order'):
  if f in row and type(row[f]) is int and row[f]<=0:add(f,'须为正整数')
 if dataset=='msa_studies':
  for f,allowed in [('design',{'交叉可重复测量（模拟）','破坏性测量（模拟）'}),('model',{'CROSSED_RANDOM_FULL','待选型'}),('status',{'采集中','已结束'})]:
   if row.get(f) and row[f] not in allowed:add(f,'登记值不在当前支持范围')
  if row.get('status')=='已结束' and not row.get('finished'):add('finished','已结束试验须有结束时间')
  if row.get('started') and row.get('finished') and row['finished']<=row['started']:add('finished','结束须晚于开始')
 elif dataset=='msa_members':
  kind=row.get('kind')
  if kind not in ('样件','操作员'):add('kind','成员须为样件或操作员')
  elif kind=='样件' and (not row.get('unit_id') or row.get('operator_id')):add('unit_id','样件成员只登记SN')
  elif kind=='操作员' and (not row.get('operator_id') or row.get('unit_id')):add('operator_id','操作员成员只登记工号')
 elif dataset=='msa_observations':
  if row.get('state') not in ('有效','缺测','待核查','作废'):add('state','观测状态不可用')
  v=row.get('value');finite=type(v) in (int,float) and math.isfinite(v)
  if row.get('state')=='有效' and not finite:add('value','有效观测须有有限数值，零可保留')
  if row.get('state')=='缺测' and v is not None:add('value','缺测数值须为空')
  if row.get('registered') and row.get('measured') and row['registered']<row['measured']:add('registered','登记不能早于测量')
 return out
