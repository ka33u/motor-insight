"""Supplier commitment snapshots and analytical receipt distribution."""
from collections import defaultdict
from datetime import datetime,date
from decimal import Decimal
from . import analytics,supply
from .models import Record

STAGES={'all':'全部采购行','changed':'当前承诺有变更','late_change':'原逾期后改承诺','overdue':'当前分段逾期未到','attention':'承诺资料待核对','cancelled':'采购已取消'}
NOTE='原采购承诺保留。当前承诺是截止时点前已确认、生效且登记的完整版本；完整数量不允许改变原采购数量。到货按时间顺序、分段按到期日及段次分配，每批数量只使用一次。'
BOUNDARY='分段收货分配是“最早承诺优先”的分析假设，未登记真实段次匹配。最新版本复算不替代原承诺绩效；到货不等于检验批准或库存可用。无ETA预测、采购批准、实际预留或U8/MES写回。'
EPS=Decimal('0.000001')
def q(v):return supply.dec(v)
def number(v):return float(v) if v is not None else None
def stamp(v):return datetime.fromisoformat(v)
def day(v):return date.fromisoformat(v)
def same(a,b):return abs(q(a)-q(b))<=EPS

class Commitments:
 def __init__(self,d=None,cutoff=None):
  self.data=d if d is not None else analytics.tables();self.cutoff=cutoff or analytics.AS_OF;self.supply=supply.SupplyData(self.data,self.cutoff);self.clock=stamp(self.cutoff);self.today=day(self.cutoff[:10])
  self.versions=self.data.get('purchase_commitment_versions',[]);self.lines=self.data.get('purchase_commitment_lines',[])
  self.by_id={r['id']:r for r in self.versions};self.by_po=supply.group(self.versions,'purchase_line_id');self.by_version=supply.group(self.lines,'version_id')
  self.rows=[self.build(p) for p in self.supply.po_rows];self.index={p['id']:p for p in self.rows}
  self.global_issues=[{'dataset':'purchase_commitment_versions','id':v['id'],'message':'承诺版本未关联截止内采购行'} for v in self.versions if v['purchase_line_id'] not in self.supply.po_index and v.get('registered','')<=self.cutoff]
  self.global_issues += [{'dataset':'purchase_commitment_lines','id':r['id'],'message':'分段缺少版本头'} for r in self.lines if r['version_id'] not in self.by_id]

 def eligible(self,v):
  if v.get('status')!='模拟确认':return False
  # Missing clocks in a confirmed version are errors, never a reason to fall back.
  for field in ['confirmed','effective','registered']:
   try:
    if v.get(field) and stamp(v[field])>self.clock:return False
   except (ValueError,TypeError):pass
  return True

 def snapshot_issues(self,v,p):
  issues=[];lines=sorted(self.by_version[v['id']],key=lambda r:(r['sequence'],r['id']))
  if type(v['line_count']) is not int or v['line_count']<=0 or len(lines)!=v['line_count']:issues.append('完整版本声明行数与分段明细不符')
  if any(type(r['sequence']) is not int for r in lines) or [r['sequence'] for r in lines]!=list(range(1,len(lines)+1)):issues.append('交付段次重复或不连续')
  if not v.get('reference') or not v.get('reason'):issues.append('版本确认依据或变更说明缺失')
  if v.get('owner_id') not in {r['id'] for r in self.data.get('employees',[])}:issues.append('采购登记人档案缺失')
  if any(not r.get('reference') for r in lines):issues.append('分段依据缺失')
  try:
   if q(v['total_qty'])<=0 or not same(v['total_qty'],p['qty']):issues.append('完整承诺数量与原采购数量不符')
   if not lines or not same(sum((q(r['qty']) for r in lines),Decimal(0)),v['total_qty']):issues.append('分段数量合计与完整承诺不符')
   for r in lines:
    if q(r['qty'])<=0:issues.append('分段数量必须为正')
    if p['unit']=='件' and q(r['qty'])!=q(r['qty']).to_integral_value():issues.append('件数分段必须为整数')
    if day(r['due'])<day(p['ordered']):issues.append('分段承诺早于采购日期')
   if [r['due'] for r in lines]!=sorted(r['due'] for r in lines):issues.append('分段承诺未按交付段次日期排序')
  except (ValueError,TypeError,KeyError):issues.append('分段日期或数量无效')
  return issues,lines

 def validate(self,v,p):
  issues=[];seen=set();node=v
  while node:
   if node['id'] in seen:issues.append('承诺前序链形成循环');break
   seen.add(node['id'])
   if node['purchase_line_id']!=p['id']:issues.append('前序版本属于其他采购行');break
   if node['status']!='模拟确认':issues.append('有效版本前序未经模拟确认')
   if type(node['version']) is not int or node['version']<=0:issues.append('承诺版本须为正整数')
   problems,_=self.snapshot_issues(node,p)
   issues += [('前序'+node['id']+'：' if node['id']!=v['id'] else '')+x for x in problems]
   try:
    times=[stamp(node[k]) for k in ['confirmed','effective','registered']]
    if not (day(p['ordered'])<=times[0].date() and times[0]<=times[1]<=times[2]<=self.clock):issues.append('确认、生效、登记时间顺序或截止无效')
   except (ValueError,TypeError,KeyError):issues.append('版本时间资料不完整')
   if node['version']==1:
    if node.get('previous_id'):issues.append('首版不应引用前序版本')
    break
   prev=self.by_id.get(node.get('previous_id'))
   if not prev:issues.append('前序版本缺失');break
   if prev['version']!=node['version']-1:issues.append('承诺版本未连续衔接')
   if prev.get('registered','')>node.get('registered',''):issues.append('前序版本登记晚于后续版本')
   node=prev
  for n in (self.by_id[x] for x in seen):
   peers=[a for a in self.by_po[p['id']] if a['version']==n['version'] and self.eligible(a)]
   if len(peers)>1:issues.append('同一采购行承诺版本编号重复')
  lines=sorted(self.by_version[v['id']],key=lambda r:(r['sequence'],r['id']))
  return list(dict.fromkeys(issues)),lines

 def build(self,p):
  versions=sorted(self.by_po[p['id']],key=lambda v:(v['version'],v['registered'],v['id']));active=[v for v in versions if self.eligible(v)]
  issues=list(p['issues']);cancelled=p['status']=='已取消';selected=max(active,key=lambda v:(v['version'],v['registered'],v['id'])) if active else None
  if not selected and not cancelled:issues.append('截止前缺少已确认的完整承诺版本')
  segments=[]
  if selected:
   problems,segments=self.validate(selected,p);issues+=problems
  if any(v['status'] not in ['模拟确认','草稿','作废'] and v['registered']<=self.cutoff for v in versions):issues.append('承诺状态尚未映射')
  valid=bool(selected and not issues and not cancelled)
  sources=self.supply.po_sources(p)
  sources+=supply.refs('purchase_commitment_versions',versions)
  sources+=supply.refs('purchase_commitment_lines',[r for v in versions for r in self.by_version[v['id']]])
  sources+=supply.refs('employees',[r for r in self.data.get('employees',[]) if r['id'] in {v['owner_id'] for v in versions}])
  rows=[];assigned=Decimal(0)
  if valid:
   receipts=[dict(id=r['id'],received=r['received'],left=q(r['qty'])) for r in sorted(p['_receipts'],key=lambda r:(r['received'],r['id']))]
   for seg in sorted(segments,key=lambda r:(r['due'],r['sequence'],r['id'])):
    left=q(seg['qty']);slices=[]
    for rec in receipts:
     take=min(left,rec['left'])
     if take<=0:continue
     before=rec['left'];rec['left']-=take;left-=take;assigned+=take
     slices.append(dict(receipt_id=rec['id'],received=rec['received'],qty=number(take),receipt_before=number(before),receipt_after=number(rec['left']),by_due=rec['received'][:10]<=seg['due']))
    due=day(seg['due'])<self.today;ontime=sum((q(x['qty']) for x in slices if x['by_due']),Decimal(0))
    rows.append(dict(**seg,arrived_qty=number(q(seg['qty'])-left),remaining_qty=number(left),on_time_qty=number(ontime),due_sample=due,on_time_full=due and same(ontime,seg['qty']),overdue_unreceived=number(left) if due else 0.0,slices=slices))
   assert same(assigned,p['received_qty']) and all(r['left']<=EPS for r in receipts)
  changed=valid and (len(segments)!=1 or segments[0]['due']!=p['due'] or selected['version']>1)
  late_change=bool(changed and selected['effective'][:10]>p['due'])
  overdue=sum((q(r['overdue_unreceived']) for r in rows),Decimal(0)) if valid else None
  history=[dict(**v,used=bool(selected and v['id']==selected['id']),eligible=self.eligible(v),exclusion=('草稿不采用' if v['status']=='草稿' else '作废不采用' if v['status']=='作废' else '确认/生效/登记在截止后' if not self.eligible(v) else ''),lines=self.by_version[v['id']]) for v in versions]
  flags=['all']+(['changed'] if changed else [])+(['late_change'] if late_change else [])+(['overdue'] if overdue is not None and overdue>0 else [])+(['attention'] if issues else [])+(['cancelled'] if cancelled else [])
  return dict(id=p['id'],supplier_id=p['supplier_id'],supplier=p['supplier'],material_id=p['material_id'],material=p['material'],category=p['category'],unit=p['unit'],status=p['status'],ordered=p['ordered'],original_due=p['due'],qty=p['qty'],received_qty=p['received_qty'],approved_qty=p['approved_qty'],putaway_qty=p['putaway_qty'],remaining_qty=p['remaining_qty'],original_due_sample=p['due_count'],original_on_time_full=p['ontime_count'],original_issues=list(p['issues']),version_id=selected['id'] if selected else None,version=selected['version'] if selected else None,valid=valid,cancelled=cancelled,changed=bool(changed),late_change=late_change,first_due=min((r['due'] for r in segments),default=None) if valid else None,last_due=max((r['due'] for r in segments),default=None) if valid else None,overdue_unreceived=number(overdue),segments=rows,versions=history,issues=list(dict.fromkeys(issues)),flags=flags,sources=supply.unique_refs(sources))

 def cohort(self,f):
  return [r for r in self.rows if all(not f.get(k) or r.get(k)==f[k] for k in ['supplier_id','material_id','category']) and (not f.get('q') or f['q'].lower() in ' '.join(str(r.get(k,'')) for k in ['id','supplier','material','material_id','version_id']).lower())]
 def detail(self,key,f):
  r=next((r for r in self.cohort(f) if r['id']==key),None)
  if not r:raise Record.DoesNotExist()
  return r

def brief(r):return {k:v for k,v in r.items() if k not in ['segments','versions','sources']}
def summary(rows):
 original_due=sum(r['original_due_sample'] for r in rows);original_on_time=sum(r['original_on_time_full'] for r in rows)
 segments=[s for r in rows if r['valid'] for s in r['segments']];due=sum(s['due_sample'] for s in segments);ontime=sum(s['on_time_full'] for s in segments)
 return dict(objects=len(rows),valid=sum(r['valid'] for r in rows),attention=sum(bool(r['issues']) for r in rows),cancelled=sum(r['cancelled'] for r in rows),changed=sum(r['changed'] for r in rows),late_change=sum(r['late_change'] for r in rows),original_due=original_due,original_on_time=original_on_time,original_rate=analytics.percent(original_on_time,original_due) if not any(r['original_issues'] for r in rows) else None,segment_due=due,segment_on_time=ontime,segment_rate=analytics.percent(ontime,due),versions=sum(len(r['versions']) for r in rows),segments=len(segments),segment_excluded_rows=sum(not r['valid'] for r in rows))

def unit_totals(rows):
 grouped=defaultdict(list)
 for r in rows:grouped[r['unit']].append(r)
 result=[]
 for unit,rr in sorted(grouped.items()):
  raw=[r for r in rr if not r['cancelled']];valid=[r for r in rr if r['valid']];bad=any(r['original_issues'] for r in raw)
  out={'unit':unit,'objects':len(rr),'current_valid':len(valid),'current_unknown':sum(not r['valid'] and not r['cancelled'] for r in rr)}
  for field in ['qty','received_qty','approved_qty','putaway_qty','remaining_qty']:out[field]=None if bad else number(sum((q(r[field]) for r in raw),Decimal(0)))
  out['known_current_overdue']=number(sum((q(r['overdue_unreceived']) for r in valid),Decimal(0)))
  result.append(out)
 return result
