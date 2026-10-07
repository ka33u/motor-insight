"""Batch date evidence, age/expiry warnings and non-reserving pick-order examples."""
from collections import defaultdict,Counter
from datetime import date
from decimal import Decimal
from django.core.exceptions import ObjectDoesNotExist
from . import analytics,supply

DATASETS=['inventory_lot_dates','inventory_age_policies']
STAGES={'all':'全部批次库位','overage':'超龄候选','near':'临期库存','expired':'过期库存','unknown':'资料待核对','ranked':'可参考排序'}
BUCKETS=['0—30天','31—60天','61—90天','91—180天','181—365天','超过365天','日期未知']
EXPIRY=['不适用','有效','临期','过期','未知']
NOTE='库龄按截止日减首次入库登记日计算，不用期初基准日冒充首次入库。按物料×批次×库位核对数量，按单位分别汇总；日期与规则保留登记版本。'
BOUNDARY='全部为模拟Excel，关注阈值为演练假设。超龄不等于呆滞，最近出库只反映已导入流水。日期登记不证明原件核验或完整历史。FIFO/FEFO仅为按物料排列的参考，不预留、不自动冻结或批准领料；现有库存与备料池不随日期提示改变。'
def unique(xs):return list(dict.fromkeys(xs))
def amount(v):return Decimal(str(v))
def days(a,b):return (date.fromisoformat(a)-date.fromisoformat(b)).days
def group(rows,key):
    out=defaultdict(list)
    for r in rows:out[key(r)].append(r)
    return out
def bucket(n):
    if n is None:return BUCKETS[-1]
    return BUCKETS[next((i for i,end in enumerate([30,60,90,180,365]) if n<=end),5)]
def select_version(rows,eligible,index,identity):
    candidates=[r for r in rows if eligible(r)]
    if not candidates:return None,['缺少截止前有效登记版本']
    current=max(candidates,key=lambda r:(r['version'],r['registered'],r['id']));issues=[]
    if Counter(r['version'] for r in candidates)[current['version']]>1:issues.append('同对象有效版本号重复')
    seen=set();r=current
    while r:
        if r['id'] in seen:issues.append('版本链循环');break
        seen.add(r['id'])
        if Counter(x['version'] for x in candidates)[r['version']]>1:issues.append('同对象有效版本号重复')
        if type(r['version']) is not int or r['version']<1:issues.append('版本须为正整数');break
        previous=index.get(r['supersedes_id']) if r['supersedes_id'] else None
        if r['version']==1:
            if r['supersedes_id']:issues.append('首版不得引用上一版本')
            break
        if not previous or not eligible(previous) or identity(previous)!=identity(r) or previous['version']!=r['version']-1 or previous['registered']>=r['registered']:
            issues.append('上一版本、对象或登记顺序不匹配');break
        if 'effective_from' in r and previous['effective_from']>r['effective_from']:issues.append('规则版本的生效日期倒序')
        r=previous
    # A late back-dated lower version cannot silently supersede a higher version.
    if any(r['version']<current['version'] and r['registered']>current['registered'] for r in candidates):issues.append('版本与登记先后不一致')
    return current,unique(issues)

class InventoryAge:
    def __init__(self,data=None,cutoff=analytics.AS_OF,order='fifo'):
        self.data=data if data is not None else analytics.tables();self.cutoff=cutoff;self.day=cutoff[:10];self.order=order
        if order not in ['fifo','fefo']:raise ValueError('参考排序方式无效')
        d=self.data;stock=supply.SupplyData(d,cutoff);materials=supply.ix(d['materials']);people=supply.ix(d['employees'])
        profiles=d.get('inventory_lot_dates',[]);policies=d.get('inventory_age_policies',[]);pi=supply.ix(profiles);ri=supply.ix(policies)
        dates_by=group(profiles,lambda r:(r['material_id'],r['lot']));rules_by=group(policies,lambda r:r['material_id']);self.rows=[];self.index={};self.global_issues=[]
        known={(r['material_id'],r['lot']) for r in stock.lots}
        self.global_issues += [f'{r["id"]} 没有对应的当前账面批次，未计入库存' for r in profiles if (r['material_id'],r['lot']) not in known and r['registered']<=cutoff and not r['voided']]
        for l in stock.lots:
            material=materials.get(l['material_id'],{});history=dates_by[(l['material_id'],l['lot'])];rules=rules_by[l['material_id']]
            profile,date_issues=select_version(history,lambda r:r['registered']<=cutoff and not r['voided'],pi,lambda r:(r['material_id'],r['lot']))
            policy,policy_issues=select_version(rules,lambda r:r['registered']<=cutoff and r['effective_from']<=self.day and r['status']!='草稿',ri,lambda r:r['material_id'])
            if policy:
                if policy['status']!='模拟确认':policy_issues.append('规则未处于模拟确认状态')
                if policy['owner_id'] not in people or not policy['reason'].strip():policy_issues.append('规则负责人与依据待核对')
                if policy['age_limit_days'] is not None and policy['age_limit_days']<=0:policy_issues.append('超龄关注天数须为正或未设置')
                if policy['warning_days'] is not None and policy['warning_days']<0:policy_issues.append('临期关注天数不得为负')
            first=profile.get('first_stock_date') if profile else None;made=profile.get('manufactured') if profile else None;expires=profile.get('expires') if profile else None;mode=profile.get('expiry_mode') if profile else None
            if profile:
                if profile['owner_id'] not in people or not profile['document_no'].strip():date_issues.append('日期登记人员或依据号待核对')
                if mode not in ['固定日期','不适用','待核实']:date_issues.append('有效期类型尚未映射')
                if mode in ['不适用','待核实'] and expires:date_issues.append('有效期类型与日期不符')
                if first and first>self.day or made and made>self.day:date_issues.append('制造或首次入库登记日期在截止后')
                if first and made and made>first:date_issues.append('制造日期晚于首次入库登记日期')
                if made and expires and expires<made:date_issues.append('有效截至早于制造日期')
                earliest=min([o['as_of'] for o in l['_opening']]+[m['occurred'][:10] for m in l['_moves']],default=None)
                if first and earliest and first>earliest:date_issues.append('首次入库登记晚于已存在的期初或流水')
                if policy and not policy_issues and policy['expiry_required'] and mode=='不适用':date_issues.append('物料规则要求有效期资料，登记却为不适用')
            date_issues=unique(date_issues);policy_issues=unique(policy_issues)
            age=days(self.day,first) if first and not date_issues else None
            expiry_days=days(expires,self.day) if mode=='固定日期' and expires and not date_issues else None
            warning=policy['warning_days'] if policy and not policy_issues else None
            expiry_state='未知' if date_issues else '不适用' if mode=='不适用' else ('过期' if expiry_days<0 else '临期' if warning is not None and expiry_days<=warning else '有效') if expiry_days is not None else '未知'
            ledger_valid=l['balance_qty'] is not None and l['balance_qty']>=0 and not l['issues']
            positive=ledger_valid and l['balance_qty']>0
            limit=policy['age_limit_days'] if policy and not policy_issues else None
            overage=bool(positive and age is not None and limit is not None and age>limit)
            issues=list(l['issues'])+date_issues+policy_issues
            if age is None:issues.append('首次入库日期未能核对，库龄未知')
            if expiry_state=='未知':issues.append('有效期资料未知')
            if not ledger_valid:issues.append('余额或库存流水待核对')
            rank_eligible=bool(positive and l['state']=='可用' and age is not None and expiry_state in ['不适用','有效','临期'] and policy and not policy_issues)
            flags=['all']+(['overage'] if overage else [])+(['near'] if positive and expiry_state=='临期' else [])+(['expired'] if positive and expiry_state=='过期' else [])+(['unknown'] if issues else [])+(['ranked'] if rank_eligible else [])
            sources=supply.refs('materials',[material] if material else [])+supply.refs('inventory_lot_dates',history)+supply.refs('inventory_age_policies',rules)+supply.refs('inventory_opening',l['_opening'])+supply.refs('inventory_movements',l['_moves'])+supply.refs('inventory_status_events',l['_events'])
            last_out=max((m['occurred'] for m in l['_moves'] if m['qty_signed']<0),default=None)
            observed_from=min([o['as_of'] for o in l['_opening']]+[m['occurred'][:10] for m in l['_moves']],default=None)
            out={**supply.clean(l),'material':material.get('name','档案缺失'),'category':material.get('category','未知'),'quantity_valid':ledger_valid,'positive':positive,'date_profile_id':profile['id'] if profile else None,'date_version':profile['version'] if profile else None,'policy_id':policy['id'] if policy else None,'policy_version':policy['version'] if policy else None,'first_stock_date':first,'manufactured':made,'expires':expires,'expiry_mode':mode,'age_days':age,'age_bucket':bucket(age),'age_limit_days':limit,'warning_days':warning,'expiry_days':expiry_days,'expiry_state':expiry_state,'overage':overage,'last_outbound':last_out,'observed_from':observed_from,'rank_eligible':rank_eligible,'reference_rank':None,'reference_order':order,'date_issues':date_issues,'policy_issues':policy_issues,'ledger_issues':l['issues'],'issues':unique(issues),'flags':flags,'date_history':history,'policy_history':rules,'sources':supply.unique_refs(sources),'ledger_timeline':l['_timeline']}
            self.rows.append(out);self.index[out['id']]=out
        for mid,rows in group(self.rows,lambda r:r['material_id']).items():
            candidates=[r for r in rows if r['rank_eligible']]
            key=(lambda r:(r['first_stock_date'],r['lot'],r['location'])) if order=='fifo' else (lambda r:(r['expires'] or '9999-12-31',r['first_stock_date'],r['lot'],r['location']))
            for n,r in enumerate(sorted(candidates,key=key),1):r['reference_rank']=n
        self.rows.sort(key=lambda r:(r['material_id'],r['reference_rank'] or 999999,r['lot'],r['location']))
    def selected(self,f):
        return [r for r in self.rows if (not f['category'] or r['category']==f['category']) and (not f['material_id'] or r['material_id']==f['material_id']) and (not f['unit'] or r['unit']==f['unit']) and f['stage'] in r['flags'] and (not f['q'] or f['q'].lower() in ' '.join(str(r.get(k) or '') for k in ['material_id','material','lot','location']).lower())]
    def detail(self,key,f):
        r=self.index.get(key)
        if r is None or key not in {r['id'] for r in self.selected(f)}:raise ObjectDoesNotExist()
        return r

def summary(rows):
    units=[]
    for unit in sorted({r['unit'] for r in rows}):
        rr=[r for r in rows if r['unit']==unit];valid=[r for r in rr if r['quantity_valid']];pos=[r for r in valid if r['positive']]
        quantity=lambda xs:float(sum((amount(r['balance_qty']) for r in xs),Decimal(0))) if valid else None
        units.append({'unit':unit,'known_rows':len(valid),'quantity_unknown_rows':len(rr)-len(valid),'known_balance':quantity(valid),'buckets':[{'name':b,'rows':sum(r['age_bucket']==b for r in pos),'qty':quantity([r for r in pos if r['age_bucket']==b])} for b in BUCKETS],'expiry':[{'name':state,'rows':sum(r['expiry_state']==state for r in pos),'qty':quantity([r for r in pos if r['expiry_state']==state])} for state in EXPIRY]})
    return {'objects':len(rows),'positive':sum(r['positive'] for r in rows),'overage':sum('overage' in r['flags'] for r in rows),'near':sum('near' in r['flags'] for r in rows),'expired':sum('expired' in r['flags'] for r in rows),'unknown':sum('unknown' in r['flags'] for r in rows),'ranked':sum(r['rank_eligible'] for r in rows),'units':units}
