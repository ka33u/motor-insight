"""Import-row constraints; graph/window completeness is a trial-level check."""
import math
from datetime import datetime
def time(value):
 if not isinstance(value,str):raise ValueError('使用厂内YYYY-MM-DDTHH:MM:SS时间')
 t=datetime.fromisoformat(value)
 if t.tzinfo is not None or len(value)!=19 or t.isoformat(timespec='seconds')!=value:raise ValueError('使用厂内YYYY-MM-DDTHH:MM:SS时间')
 return t
def issues(dataset,row):
 out=[]
 def add(field,message):out.append(dict(code='SCHEDULE_SOURCE',field=field,message=message))
 for f in ('baseline','horizon_end','released','due','started','finished'):
  if f in row:
   try:time(row[f])
   except (ValueError,TypeError):add(f,'使用厂内YYYY-MM-DDTHH:MM:SS时间')
 for a,b in [('baseline','horizon_end'),('released','due'),('started','finished')]:
  if row.get(a) and row.get(b) and row[b]<=row[a]:add(b,'结束或应完成时间须晚于起点')
 for f in ('qty','lot_qty','priority','task_count','job_count'):
  if f in row and (type(row[f]) is not int or row[f]<=0):add(f,'须为正整数')
 for f in ('edge_count','option_count','window_count','block_count'):
  if f in row and (type(row[f]) is not int or row[f]<0):add(f,'须为非负整数')
 for f in ('unit_minutes','setup_minutes','lag_minutes'):
  if f in row and (type(row[f]) not in (int,float) or not math.isfinite(row[f]) or row[f]<0 or (f=='unit_minutes' and row[f]==0)):add(f,'加工须为正数；换型与等待须为非负有限数')
 return out
