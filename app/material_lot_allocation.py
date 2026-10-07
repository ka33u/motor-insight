"""Non-reserving batch slices for the existing whole-work-order rehearsal."""
from collections import defaultdict
from decimal import Decimal
from . import inventory_age

POLICIES={'ledger':'账面可用余额 · 不指定批次','fifo':'日期核对 · FIFO先入先用','fefo':'日期核对 · FEFO先到期先用'}
NOTE='日期策略仅纳入正余额、账据可核对、可用状态且日期与规则可核对的批次。超龄候选仍可纳入；过期、日期未知及受限批次排除。有效期核查至库存截止日与计划开工日中较晚一天；到期当天仍有效。安全缓冲从参考顺序末端保留，属于本次模拟假设。缺口是本策略候选库存不足，不证明实际缺料；日期未知部分未纳入。全部物料可覆盖后才逐批扣减模拟池，不写回仓库，不代表质量批准、实际预留或领料指令。'
def qty(v):return Decimal(str(v))
def reason(r):
 if not r['quantity_valid']:return '余额待核对'
 if not r['positive']:return '无正余额'
 if r['state']!='可用':return '状态受限'
 if r['date_issues'] or r['age_days'] is None:return '日期资料待核对'
 if r['policy_issues']:return '规则待核对'
 if r['expiry_state']=='未知':return '有效期资料未知'
 if r['expiry_state']=='过期':return '截止日已过期'
 return '纳入日期候选'

class LotAllocation:
 def __init__(self,data,cutoff,order):
  self.date_data=inventory_age.InventoryAge(data,cutoff,order);self.day=cutoff[:10];self.order=order;self.rows=defaultdict(list);self.slices={}
  for r in self.date_data.rows:self.rows[r['material_id']].append(r)
 def candidates(self,mid):return [r for r in self.rows[mid] if r['rank_eligible']]
 def candidate_qty(self,mid):return sum((qty(r['balance_qty']) for r in self.candidates(mid)),Decimal(0))
 def setup(self,mid,buffer):
  if mid in self.slices:raise ValueError('批次池已建立，不可重复保留缓冲')
  rows=[{'id':r['id'],'lot':r['lot'],'location':r['location'],'balance_qty':qty(r['balance_qty']),'retained':Decimal(0),'initial':qty(r['balance_qty']),'remaining':qty(r['balance_qty']),'expires':r['expires'],'first_stock_date':r['first_stock_date'],'reference_rank':r['reference_rank'],'date_profile_id':r['date_profile_id'],'date_version':r['date_version'],'policy_id':r['policy_id'],'policy_version':r['policy_version']} for r in self.candidates(mid)]
  reserve=buffer
  for r in reversed(rows):
   keep=min(reserve,r['initial']);r['retained']=keep;r['initial']-=keep;r['remaining']=r['initial'];reserve-=keep
  self.slices[mid]=rows
  return sum((r['initial'] for r in rows),Decimal(0))
 def available(self,mid,use_day):return sum((r['remaining'] for r in self.slices[mid] if not r['expires'] or r['expires']>=use_day),Decimal(0))
 def preview(self,mid,need,use_day):
  left=need;out=[]
  for r in self.slices[mid]:
   if r['expires'] and r['expires']<use_day:continue
   take=min(left,r['remaining'])
   if take>0:
    out.append({**r,'qty':take,'before':r['remaining'],'after':r['remaining']-take,'use_day':use_day});left-=take
   if left==0:break
  if left:raise ValueError('批次池与工单可用数量不一致；暂停试配')
  return out
 def commit(self,mid,plans):
  index={r['id']:r for r in self.slices[mid]}
  if len({p['id'] for p in plans})!=len(plans) or any(p['id'] not in index or p['before']!=index[p['id']]['remaining'] or p['qty']<=0 or p['after']!=p['before']-p['qty'] or p['after']<0 for p in plans):raise ValueError('批次试配计划与当前模拟池不一致')
  for p in plans:index[p['id']]['remaining']=p['after']
 def sources(self,mid):return [ref for r in self.rows[mid] for ref in r['sources']]
 def details(self,mid):
  state={r['id']:r for r in self.slices.get(mid,[])}
  out=[]
  for r in self.rows[mid]:
   s=state.get(r['id']);out.append({k:r[k] for k in ['id','lot','location','unit','state','balance_qty','quantity_valid','age_days','expires','expiry_state','reference_rank','date_profile_id','date_version','policy_id','policy_version','issues']}|{'candidate':r['rank_eligible'],'selection_reason':reason(r),'simulated_buffer':s['retained'] if s else None,'initial_pool':s['initial'] if s else None,'remaining_pool':s['remaining'] if s else None})
  return out
