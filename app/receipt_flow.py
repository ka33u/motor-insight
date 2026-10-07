"""Receipt-node elapsed time and source-backed work-window decomposition."""
from collections import defaultdict
from datetime import datetime,date
from decimal import Decimal
import statistics
from . import supply,analytics

STAGES={'all':'全部到货','waiting_inspection':'尚无检验登记','disposition':'待检验处置','putaway':'批准待足量入库','complete':'已足量入库','attention':'实物事实待核对','work_attention':'作业登记待核对'}
NOTE='按到货批次计数，时间是截至快照的日历历时；检验登记时间不等于作业开始。已完成历时与未闭合观察时长分开，未纳入完成批次的分位数。kg与件分别统计。'
BOUNDARY='作业窗口来自模拟Excel，可含设备运行；不等于个人直接工时、实际排队、工作日历、SLA超时或因果瓶颈。窗口缺失/冲突时分解留空，实物节点保留。未预测入库时间，未修改检验批准、库存可用状态、承诺或U8/MES。'
def dt(v):return datetime.fromisoformat(v)
def elapsed(a,b):return (dt(b)-dt(a)).total_seconds()/3600 if a and b else None
def union_hours(intervals):
 if not intervals:return 0.0
 ordered=sorted((dt(a),dt(b)) for a,b in intervals);a,b=ordered[0];seconds=0
 for c,d in ordered[1:]:
  if c<=b:b=max(b,d)
  else:seconds+=(b-a).total_seconds();a,b=c,d
 return (seconds+(b-a).total_seconds())/3600
def stats(values):
 xs=sorted(x for x in values if x is not None);n=len(xs)
 def quantile(p):
  if not n:return None
  index=(n-1)*p;left=int(index);return xs[left]+(xs[min(left+1,n-1)]-xs[left])*(index-left)
 return dict(n=n,median=statistics.median(xs) if xs else None,p90=quantile(.9),minimum=xs[0] if xs else None,maximum=xs[-1] if xs else None)

class ReceiptFlow:
 def __init__(self,d=None,cutoff=None):
  self.data=d if d is not None else analytics.tables();self.cutoff=cutoff or analytics.AS_OF;self.clock=dt(self.cutoff);self.supply=supply.SupplyData(self.data,self.cutoff)
  self.headers=self.data.get('receipt_jobs',[]);self.versions=self.data.get('receipt_job_versions',[]);self.header_index=supply.ix(self.headers);self.version_index=supply.ix(self.versions);self.by_job=supply.group(self.versions,'job_id');self.by_receipt=supply.group(self.headers,'receipt_id')
  self.inspections=supply.ix(self.data['incoming_inspections']);self.movements=supply.ix(self.data['inventory_movements']);self.employees=supply.ix(self.data['employees'])
  self.rows=[self.build(r) for r in self.supply.receipts.values()];self.index=supply.ix(self.rows)
  self.global_issues=[{'id':h['id'],'message':'作业任务未关联截止内到货'} for h in self.headers if h['created']<=self.cutoff and h['receipt_id'] not in self.supply.receipts]
  self.global_issues += [{'id':v['id'],'message':'作业版本缺少任务头'} for v in self.versions if v['registered']<=self.cutoff and v['job_id'] not in self.header_index]

 def eligible(self,v):return v['status']=='模拟确认' and v['registered']<=self.cutoff
 def snapshot_issues(self,h,v,r):
  issues=[]
  if not v.get('owner_id') in self.employees or not all(v.get(k) for k in ['station','reference','reason']):issues.append('作业岗位或登记依据不完整')
  try:
   created=dt(h['created']);registered=dt(v['registered']);a,b,c=[dt(v[k]) if v.get(k) else None for k in ['assigned','started','finished']]
   if not dt(r['received'])<=created<=registered<=self.clock:issues.append('任务建立、登记或截止时间无效')
   if not a:issues.append('派工时间缺失')
   if a and not created<=a<=registered:issues.append('派工时间不在任务建立与登记之间')
   if b and (not a or not a<=b<=registered):issues.append('作业开始时间无效')
   if c and (not b or not b<=c<=registered):issues.append('作业结束时间无效')
   if h['stage']=='来料检验':
    if v.get('movement_id'):issues.append('检验任务不应引用入库流水')
    source=self.inspections.get(v.get('inspection_id'))
    if c and (not source or source['receipt_id']!=r['id'] or source['inspected']<v['finished'] or source['inspected']>self.cutoff):issues.append('检验结束晚于原登记或引用不一致')
    if source and not c:issues.append('已引用检验记录但未登记窗口结束')
   elif h['stage']=='入库上架':
    if v.get('inspection_id'):issues.append('上架任务不应引用检验单')
    source=self.movements.get(v.get('movement_id'))
    if c and (not source or source['reference']!=r['id'] or source['material_id']!=r['material_id'] or source['lot']!=r['lot'] or source['movement']!='采购入库' or supply.dec(source['qty_signed'])<=0 or source['occurred']<v['finished'] or source['occurred']>self.cutoff):issues.append('上架结束晚于原入库或引用不一致')
    if source and not c:issues.append('已引用入库流水但未登记窗口结束')
    if b:
     previous=[q for q in r['_inspections'] if q['inspected']<=v['started']];approved=previous[-1] if previous else None
     if not approved or approved['result']!='合格' or approved['disposition']!='批准入库':issues.append('上架开始时缺少合格及批准证据')
   else:issues.append('作业环节尚未映射')
  except (TypeError,ValueError,KeyError):issues.append('作业时间或引用无效')
  return issues

 def job(self,h,r):
  history=sorted(self.by_job[h['id']],key=lambda v:(v['version'],v['registered'],v['id']));eligible=[v for v in history if self.eligible(v)];selected=max(eligible,key=lambda v:(v['version'],v['registered'],v['id'])) if eligible and h['created']<=self.cutoff else None
  issues=[];seen=set();node=selected
  if h['created']<=self.cutoff and not selected:issues.append('缺少截止前模拟确认作业版本')
  if not h.get('reference') or not h.get('note'):issues.append('任务依据不完整')
  while node:
   if node['id'] in seen:issues.append('作业前序链循环');break
   seen.add(node['id'])
   if node['job_id']!=h['id']:issues.append('前序版本属于其他作业');break
   if not self.eligible(node):issues.append('前序版本未确认或在截止后')
   if type(node['version']) is not int or node['version']<1:issues.append('登记版本须为正整数');break
   issues += [('前序'+node['id']+'：' if node['id']!=selected['id'] else '')+x for x in self.snapshot_issues(h,node,r)]
   if sum(v['version']==node['version'] for v in eligible)>1:issues.append('同一作业版本号重复确认')
   if node['version']==1:
    if node.get('previous_id'):issues.append('首版不应引用前序')
    break
   prev=self.version_index.get(node.get('previous_id'))
   if not prev:issues.append('前序版本缺失');break
   if prev['version']!=node['version']-1 or prev['registered']>node['registered']:issues.append('前序版本未连续或登记倒序')
   node=prev
  if any(v['status'] not in ['模拟确认','草稿','作废'] and v['registered']<=self.cutoff for v in history):issues.append('作业登记状态尚未映射')
  valid=bool(selected and not issues);hours=elapsed(selected.get('started'),selected.get('finished')) if valid else None
  return dict(**h,selected=selected,valid=valid,issues=list(dict.fromkeys(issues)),work_hours=hours,open_work_hours=elapsed(selected.get('started'),self.cutoff) if valid and selected.get('started') and not selected.get('finished') else None,versions=[dict(**v,used=bool(selected and selected['id']==v['id']),eligible=self.eligible(v),exclusion='草稿不采用' if v['status']=='草稿' else '作废不采用' if v['status']=='作废' else '截止后不采用' if v['registered']>self.cutoff else '') for v in history])

 def decomposition(self,jobs,stage,expected,start,end):
  relevant=[j for j in jobs if j['stage']==stage and j['created']<=self.cutoff];field='inspection_id' if stage=='来料检验' else 'movement_id'
  selected=[j for j in relevant if j['selected'] and j['selected'].get(field) in expected]
  covered=bool(expected and selected and {j['selected'][field] for j in selected}==expected and all(j['valid'] and j['selected'].get('started') and j['selected'].get('finished') for j in selected))
  # Invalid jobs cannot disappear by changing their source reference.
  if any(j['issues'] for j in relevant):covered=False
  if not covered:return dict(known=False,reason='缺少完整、有效且对应节点的作业时段',total_hours=elapsed(start,end),before_start_hours=None,work_hours=None,gap_hours=None,job_ids=[j['id'] for j in selected])
  intervals=[(j['selected']['started'],j['selected']['finished']) for j in selected];first=min(a for a,b in intervals)
  if first<start or any(b>end for a,b in intervals):return dict(known=False,reason='作业窗口超出节点历时范围',total_hours=elapsed(start,end),before_start_hours=None,work_hours=None,gap_hours=None,job_ids=[j['id'] for j in selected])
  work=union_hours(intervals);before=elapsed(start,first);gap=elapsed(first,end)-work
  assert gap>=-1e-8
  return dict(known=True,reason='',total_hours=elapsed(start,end),before_start_hours=before,work_hours=work,gap_hours=max(0,gap),job_ids=[j['id'] for j in selected])

 def build(self,r):
  p=self.supply.po_index.get(r['purchase_line_id'],{});m=self.supply.materials.get(r['material_id'],{});issues=list(r['issues'])
  if not p or not m:issues.append('采购或物料档案缺失')
  if r['status'] not in ['待检','检验合格','隔离']:issues.append('到货状态尚未映射')
  jobs=[self.job(h,r) for h in self.by_receipt[r['id']]];qs=r['_inspections'];moves=sorted(r['_moves'],key=lambda x:(x['occurred'],x['id']));first=qs[0] if qs else None
  full=None;running=Decimal(0);posted=[]
  for move in moves:
   if move['movement']=='采购入库' and move['material_id']==r['material_id'] and move['lot']==r['lot'] and supply.dec(move['qty_signed'])>0:
    running+=supply.dec(move['qty_signed']);posted.append(move)
    if not full and running>=supply.dec(r['qty']):full=move['occurred']
  approved_at=None
  if posted:
   earlier=[q for q in qs if q['inspected']<=posted[0]['occurred'] and q['result']=='合格' and q['disposition']=='批准入库'];approved_at=earlier[-1]['inspected'] if earlier else None
  state='attention' if issues else 'waiting_inspection' if not first else 'disposition' if not r['approved'] else 'putaway' if not full else 'complete'
  completed_inspection=elapsed(r['received'],first['inspected']) if first and not issues else None
  completed_stock=elapsed(r['received'],full) if full and not issues else None
  latest=qs[-1] if qs else None;observed_from=r['received'] if state=='waiting_inspection' else latest['inspected'] if state in ['disposition','putaway'] else None
  inspection=self.decomposition(jobs,'来料检验',{first['id']} if first else set(),r['received'],first['inspected'] if first else None)
  putaway=self.decomposition(jobs,'入库上架',{x['id'] for x in posted if full and x['occurred']<=full},approved_at,full)
  if issues:
   for part in [inspection,putaway]:part.update(known=False,reason='原始实物事实待核对',total_hours=None,before_start_hours=None,work_hours=None,gap_hours=None)
  work_issues=[j['id']+'：'+'；'.join(j['issues']) for j in jobs if j['issues']]
  if first and not inspection['known']:work_issues.append('首检作业历时未完整覆盖')
  if full and not putaway['known']:work_issues.append('整批入库作业历时未完整覆盖')
  sources=self.supply.po_sources(p) if p else []
  sources+=supply.refs('receipt_jobs',self.by_receipt[r['id']])+supply.refs('receipt_job_versions',[v for h in self.by_receipt[r['id']] for v in self.by_job[h['id']]])
  sources+=supply.refs('employees',[self.employees[v['owner_id']] for h in self.by_receipt[r['id']] for v in self.by_job[h['id']] if v['owner_id'] in self.employees])
  return dict(id=r['id'],purchase_line_id=r['purchase_line_id'],material_id=r['material_id'],material=m.get('name','档案缺失'),category=m.get('category','未知'),unit=m.get('unit','未知'),supplier_id=p.get('supplier_id',''),supplier=p.get('supplier','档案缺失'),lot=r['lot'],received=r['received'],qty=r['qty'],approved=r['approved'],putaway_qty=r['putaway_qty'],unposted_qty=r['unposted_qty'],state=state,state_label=STAGES[state],first_inspected=first['inspected'] if first else None,first_inspection_id=first['id'] if first else None,approval_before_first_stock=approved_at if not issues else None,full_stock_at=full if not issues else None,inspection_hours=completed_inspection,stock_hours=completed_stock,observation_from=observed_from,open_observation_hours=elapsed(observed_from,self.cutoff),inspection_decomposition=inspection,putaway_decomposition=putaway,jobs=jobs,inspections=qs,movements=[supply.without_money(x) for x in moves],issues=list(dict.fromkeys(issues)),work_issues=list(dict.fromkeys(work_issues)),sources=supply.unique_refs(sources),flags=['all',state]+(['work_attention'] if work_issues else []))

 def cohort(self,f):
  return [r for r in self.rows if all(not f.get(k) or f[k]==r[k] for k in ['category','material_id','supplier_id']) and (not f.get('received_from') or r['received'][:10]>=f['received_from']) and (not f.get('received_to') or r['received'][:10]<=f['received_to']) and (not f.get('q') or f['q'].lower() in ' '.join(str(r[k]) for k in ['id','purchase_line_id','material_id','material','supplier','lot']).lower())]

def brief(r):return {k:v for k,v in r.items() if k not in ['jobs','inspections','movements','sources']}
def summary(rows):
 out=dict(objects=len(rows),completed=sum(r['state']=='complete' for r in rows),waiting_inspection=sum(r['state']=='waiting_inspection' for r in rows),disposition=sum(r['state']=='disposition' for r in rows),putaway=sum(r['state']=='putaway' for r in rows),attention=sum(bool(r['issues']) for r in rows),work_attention=sum(bool(r['work_issues']) for r in rows),inspection_elapsed=stats(r['inspection_hours'] for r in rows),stock_elapsed=stats(r['stock_hours'] for r in rows))
 out['open_states']=[{'state':k,'label':STAGES[k],**stats(r['open_observation_hours'] for r in rows if r['state']==k)} for k in ['waiting_inspection','disposition','putaway']]
 out['decompositions']=[]
 for key,name in [('inspection_decomposition','首检登记历时分解'),('putaway_decomposition','批准至整批入库分解')]:
  known=[r[key] for r in rows if r[key]['known']];eligible=[r for r in rows if r['first_inspected']] if key=='inspection_decomposition' else [r for r in rows if r['full_stock_at']]
  out['decompositions'].append({'key':key,'name':name,'n':len(known),'eligible':len(eligible),'unknown':len(eligible)-len(known),'means':{f:statistics.mean(x[f] for x in known) if known else None for f in ['total_hours','before_start_hours','work_hours','gap_hours']}})
 out['units']=[]
 for unit,rr in sorted(supply.group(rows,'unit').items()):
  buckets=[]
  for key in ['waiting_inspection','disposition','putaway','complete','attention']:
   group=[r for r in rr if r['state']==key];known=[r for r in group if not r['issues']]
   buckets.append({'state':key,'label':STAGES[key],'rows':len(group),'qty':float(sum((supply.dec(r['qty']) for r in known),Decimal(0))) if len(group)==len(known) else None})
  out['units'].append({'unit':unit,'rows':len(rr),'states':buckets})
 return out
