"""Intrinsic row validity; cross-row capture gaps remain visible in the analysis."""
from decimal import Decimal,InvalidOperation
from .finite_schedule_contract import time
COUNTS=('window_count','event_count','cycle_count','output_count','total_qty','good_first_qty','rework_qty','scrap_qty','unknown_qty')
def issues(dataset,row):
 out=[]
 def add(f,m):out.append(dict(code='OEE_SOURCE',field=f,message=m))
 for f in ('started','finished','reported'):
  if f in row:
   try:time(row[f])
   except (TypeError,ValueError):add(f,'使用厂内YYYY-MM-DDTHH:MM:SS时间')
 if row.get('started') and row.get('finished') and row['finished']<=row['started']:add('finished','结束须晚于开始')
 for f in COUNTS:
  if f in row and (type(row[f]) is not int or row[f]<0):add(f,'数量须为非负整数')
 if dataset=='oee_studies' and row.get('capture_state') not in ('完整','未闭合'):add('capture_state','采集闭合状态须为完整或未闭合')
 if dataset=='oee_events' and row.get('kind') not in ('故障','换型','待料','其他停止'):add('kind','停止类别不在登记范围')
 if dataset=='oee_cycles':
  try:
   value=Decimal(str(row.get('seconds_per_unit')))
   if not value.is_finite() or value<=0 or isinstance(row.get('seconds_per_unit'),bool):raise ValueError()
  except (InvalidOperation,ValueError):add('seconds_per_unit','理想秒每单位须为有限正数')
 if dataset=='oee_outputs' and all(type(row.get(k)) is int for k in COUNTS[4:]) and row['total_qty']!=sum(row[k] for k in COUNTS[5:]):add('total_qty','首次经过数量须等于首次良品、需返工、报废和未确认之和')
 return out
