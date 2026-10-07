from .finite_schedule_contract import time
def issues(dataset,row):
 out=[]
 def add(f,m):out.append(dict(code='CREW_SOURCE',field=f,message=m))
 for f in ('valid_from','valid_until','started','finished'):
  if f in row:
   try:time(row[f])
   except (TypeError,ValueError):add(f,'使用厂内YYYY-MM-DDTHH:MM:SS时间')
 for a,b in [('valid_from','valid_until'),('started','finished')]:
  if row.get(a) and row.get(b) and row[b]<=row[a]:add(b,'窗口结束须晚于开始，失效起点不包含在窗口内')
 for f in ('credential_count','candidate_count','window_count','block_count'):
  if f in row and (type(row[f]) is not int or row[f]<0):add(f,'声明数量须为非负整数')
 return out
