"""Inspectable cohort metrics computed from committed Excel records only."""
from collections import Counter,defaultdict
from functools import lru_cache
from datetime import datetime
from django.db.models import Count,Max
from .models import Record,ImportBatch
from .schema import SCHEMAS

AS_OF='2026-10-01T18:00:00'
DAY=AS_OF[:10]

def revision():
    q=Record.objects.aggregate(n=Count('id'),at=Max('updated_at'))
    return (q['n'],str(q['at']))

@lru_cache(maxsize=2)
def _tables(rev):
    tables={k:[] for k in SCHEMAS}
    for key,values in Record.objects.values_list('dataset','values').iterator(chunk_size=2500):tables[key].append(values)
    return tables

def tables():return _tables(revision())
def indexed(rows):return {r['id']:r for r in rows}
def percent(a,b):return round(a/b*100,2) if b else None

def quality_state(data):
    units=indexed(data['units']);specs=indexed(data['test_specs']);expected=defaultdict(set);measurements=defaultdict(list)
    for s in specs.values():
        if s['mandatory']:expected[(s['product_id'],s['version'])].add(s['id'])
    for m in data['measurements']:measurements[m['session_id']].append(m)
    sessions=defaultdict(list);inconsistent=[]
    for s in data['test_sessions']:
        if s['voided'] or s['tested']>AS_OF or s['unit_id'] not in units:continue
        product=units[s['unit_id']]['product_id'];required=expected[(product,s['spec_version'])];ms=measurements[s['id']]
        ids=[m['spec_id'] for m in ms]
        complete=bool(required) and required.issubset(ids) and len(ids)==len(set(ids))
        valid=True;passed=True
        for m in ms:
            spec=specs.get(m['spec_id'])
            if not spec or spec['product_id']!=product or spec['version']!=s['spec_version'] or m['unit']!=spec['unit']:
                valid=False;continue
            result=(spec['lsl'] is None or m['value']>=spec['lsl']) and (spec['usl'] is None or m['value']<=spec['usl'])
            passed=passed and result
            if (m['result']=='合格')!=result:inconsistent.append(m['id'])
        complete=complete and valid
        actual='合格' if complete and passed else '不合格' if complete else '不完整'
        if s['complete']!=complete or s['result']!=actual:inconsistent.append(s['id'])
        sessions[s['unit_id']].append({**s,'calculated_complete':complete,'calculated_result':actual})
    for ss in sessions.values():ss.sort(key=lambda s:(s['tested'],s['attempt'],s['id']))
    return sessions,inconsistent

@lru_cache(maxsize=2)
def _overview(rev,family):
    d=_tables(rev);products=indexed(d['products']);orders=indexed(d['orders']);customers=indexed(d['customers']);all_lines=indexed(d['order_lines'])
    match=lambda pid:not family or products.get(pid,{}).get('family')==family
    units=[u for u in d['units'] if u['assembly_at']<=AS_OF and match(u['product_id'])];unit_ids={u['id'] for u in units}
    lines={k:v for k,v in all_lines.items() if match(v['product_id'])}
    work_orders={w['id']:w for w in d['work_orders'] if match(w['product_id'])}
    sessions,inconsistent=quality_state(d)
    eligible={u['id']:[s for s in sessions[u['id']] if s['calculated_complete']] for u in units}
    complete={k:v for k,v in eligible.items() if v};first_pass=sum(v[0]['calculated_result']=='合格' for v in complete.values())
    latest_pass={k for k,v in sessions.items() if k in unit_ids and v and v[-1]['calculated_result']=='合格'}
    untested=[u for u in units if not sessions[u['id']]]
    incomplete=[u for u in units if sessions[u['id']] and not sessions[u['id']][-1]['calculated_complete']]
    failed=[u for u in units if sessions[u['id']] and sessions[u['id']][-1]['calculated_result']=='不合格']
    release_by_unit={r['unit_id']:r for r in d['releases'] if r['status']=='批准放行' and r['released']<=AS_OF and r['unit_id'] in unit_ids}
    approved=set(release_by_unit);waiting_release=latest_pass-approved
    shipped_ids={r['unit_id'] for r in d['shipment_units'] if r['unit_id'] in unit_ids};waiting_shipping=approved-shipped_ids
    shipments=[s for s in d['shipments'] if s['shipped']<=AS_OF and s['order_line_id'] in lines]
    plan_ship=defaultdict(list);line_ship=Counter()
    for s in shipments:plan_ship[s['delivery_plan_id']].append(s);line_ship[s['order_line_id']]+=s['qty']
    due_plans=[p for p in d['delivery_plans'] if p['due']<DAY and p['order_line_id'] in lines]
    on_time=sum(sum(s['qty'] for s in plan_ship[p['id']] if s['shipped'][:10]<=p['due'])>=p['qty'] for p in due_plans)
    late=[]
    for p in due_plans:
        left=max(0,p['qty']-sum(s['qty'] for s in plan_ship[p['id']]))
        if left:
            line=lines[p['order_line_id']];order=orders.get(line['order_id'],{})
            late.append({'id':p['id'],'line':line['id'],'order':line['order_id'],'product':line['product_id'],'customer':customers.get(order.get('customer_id'),{}).get('name','未接入'),'due':p['due'],'remaining':left,'days':(datetime.fromisoformat(DAY)-datetime.fromisoformat(p['due'])).days})
    late.sort(key=lambda p:(-p['days'],-p['remaining']))
    output=Counter(u['assembly_at'][:10] for u in units);daily=[]
    for day,n in sorted(output.items()):
        cohort=[u for u in units if u['assembly_at'].startswith(day)];cs=[eligible[u['id']] for u in cohort if eligible[u['id']]]
        daily.append({'day':day,'units':n,'complete':len(cs),'first_pass':sum(s[0]['calculated_result']=='合格' for s in cs),'fpy':percent(sum(s[0]['calculated_result']=='合格' for s in cs),len(cs))})
    family_rows=[]
    for name in sorted({p['family'] for p in products.values()}):
        cohort=[u for u in units if products[u['product_id']]['family']==name]
        if cohort:family_rows.append({'name':name,'units':len(cohort),'shipped':sum(u['id'] in shipped_ids for u in cohort),'pending':sum(u['id'] not in approved for u in cohort)})
    invoices=[i for i in d['invoices'] if i['issued']<=DAY and i['shipment_id'] in {s['id'] for s in shipments}]
    paid=Counter()
    for p in d['payments']:
        if p['paid']<=DAY:paid[p['invoice_id']]+=p['amount_cents']
    ar=sum(max(0,i['net_cents']+i['tax_cents']-paid[i['id']]) for i in invoices)
    overdue_ar=sum(max(0,i['net_cents']+i['tax_cents']-paid[i['id']]) for i in invoices if i['due']<DAY)
    costs=Counter()
    for c in d['costs']:
        if c['work_order_id'] in work_orders and c['occurred']<=DAY:costs[c['category']]+=c['amount_cents']
    by_device=defaultdict(lambda:[0,0])
    for ss in complete.values():
        s=ss[0];by_device[s['equipment_id']][1]+=1;by_device[s['equipment_id']][0]+=s['calculated_result']=='合格'
    energy=Counter();downtime=Counter()
    for e in d['energy']:
        if e['ended']<=AS_OF:energy[e['workshop']]+=e['kwh']
    for t in d['downtime']:
        if t['finished']<=AS_OF:downtime[t['reason']]+=(datetime.fromisoformat(t['finished'])-datetime.fromisoformat(t['started'])).total_seconds()/60
    issues=[]
    for title,rows,level in [('未检测',untested,'待办'),('检测项目不全',incomplete,'高'),('终检不合格',failed,'高')]:
        for u in rows:issues.append({'key':title+u['id'],'kind':title,'object':u['id'],'dataset':'units','owner':'质量试验','severity':level,'detail':f"工单 {u['work_order_id']} · {u['product_id']}"})
    for u in sorted(waiting_release):issues.append({'key':'待放行'+u,'kind':'合格待放行','object':u,'dataset':'units','owner':'质量试验','severity':'待办','detail':'检测合格，但尚无批准放行记录'})
    for p in late:issues.append({'key':'逾期'+p['id'],'kind':'逾期未交','object':p['line'],'dataset':'order_lines','owner':'计划 / 销售','severity':'高','detail':f"剩余 {p['remaining']} 台 · 逾期 {p['days']} 天"})
    for t in d['tools']:
        if t['next_due']<DAY:issues.append({'key':'校准'+t['id'],'kind':'校准到期','object':t['id'],'dataset':'tools','owner':'设备计量','severity':'高','detail':f"到期日 {t['next_due']} · {t['equipment_id']}"})
    for n in d['nonconformities']:
        if n['unit_id'] in unit_ids and not n['closed'] and n['due']<DAY:issues.append({'key':'整改'+n['id'],'kind':'整改逾期','object':n['unit_id'],'dataset':'units','owner':'质量 / 工艺','severity':'高','detail':n['id']+' · '+n['description']})
    metric=lambda key,name,num,den,unit,note,dataset:{'key':key,'name':name,'value':percent(num,den) if den is not None else num,'numerator':num,'denominator':den,'unit':unit,'note':note,'dataset':dataset}
    kpis=[metric('otif','按期足量交付',on_time,len(due_plans),'%','按已过承诺日的交付计划行；当日到期不提前判迟交，承诺日当天发货计按期。','delivery_plans'),metric('fpy','首次完整检测合格',first_pass,len(complete),'%','按装配队列SN；取最早有效完整检测，复测不冲掉首检失败。','test_sessions'),metric('coverage','完整检测覆盖',len(complete),len(units),'%','装配完成视为应检；至少一次规范必检项目齐全。','units'),metric('late','逾期未交',sum(p['remaining'] for p in late),None,'台','到期计划剩余数量，不与其他计划超交抵消。','delivery_plans'),metric('produced','累计装配',len(units),None,'台','2026-09-21 至 09-25 装配队列，截至快照时点。','units'),metric('shipped','累计发货',sum(s['qty'] for s in shipments),None,'台','发货口径；签收另列，不能代替客户验收。','shipments')]
    return {'as_of':AS_OF,'synthetic':True,'scope':family or '全部产品族','families':sorted({p['family'] for p in products.values()}),'kpis':kpis,'daily':daily,'families_chart':family_rows,'flow':[{'name':n,'value':v} for n,v in [('装配完成',len(units)),('完整检测',len(complete)),('最新检测合格',len(latest_pass)),('批准放行',len(approved)),('装箱发运',len(shipped_ids))]],'quality':{'untested':len(untested),'incomplete':len(incomplete),'failed':len(failed),'waiting_release':len(waiting_release),'waiting_shipping':len(waiting_shipping),'inconsistencies':len(inconsistent),'devices':[{'name':k,'pass':v[0],'total':v[1],'fpy':percent(*v)} for k,v in sorted(by_device.items())]},'late_plans':late,'issues':issues,'finance':{'order_net_cents':sum(l['qty']*l['unit_price_cents'] for l in lines.values()),'invoiced_net_cents':sum(i['net_cents'] for i in invoices),'ar_cents':ar,'overdue_ar_cents':overdue_ar,'costs':[{'name':k,'cents':v} for k,v in costs.items()],'note':'发票金额不是会计确认收入；成本为未结账暂估，不能据此认定正式毛利。'},'energy':[{'name':k,'kwh':round(v,2)} for k,v in energy.items()],'downtime':[{'name':k,'minutes':round(v,1)} for k,v in downtime.items()],'factory_scope_note':'能源、设备与计量为全厂数据，不随产品族筛选分摊。','counts':{k:len(v) for k,v in d.items()},'record_total':sum(len(v) for v in d.values())}

def overview(family=''):return _overview(revision(),family)

def trace(unit_id):
    d=tables();unit=next((u for u in d['units'] if u['id']==unit_id),None)
    if not unit:raise Record.DoesNotExist('未找到该SN')
    wo=next((w for w in d['work_orders'] if w['id']==unit['work_order_id']),None)
    allocations=[a for a in d['allocations'] if a['work_order_id']==unit['work_order_id']];line_ids={a['order_line_id'] for a in allocations}
    lines=[l for l in d['order_lines'] if l['id'] in line_ids];order_ids={l['order_id'] for l in lines}
    orders=[o for o in d['orders'] if o['id'] in order_ids];customers=[c for c in d['customers'] if c['id'] in {o['customer_id'] for o in orders}]
    batch_ids={unit['stator_batch'],unit['rotor_batch']}
    if unit.get('assembly_batch'):batch_ids.add(unit['assembly_batch'])
    links=[g for g in d['genealogy'] if g['child_id']==unit_id or g['child_id'] in batch_ids]
    sessions=[s for s in d['test_sessions'] if s['unit_id']==unit_id];session_ids={s['id'] for s in sessions}
    specs=indexed(d['test_specs']);measurements=[{**m,'spec':specs.get(m['spec_id']),'attachment_available':False} for m in d['measurements'] if m['session_id'] in session_ids]
    packed=[s for s in d['shipment_units'] if s['unit_id']==unit_id];shipments=[s for s in d['shipments'] if s['id'] in {p['shipment_id'] for p in packed}]
    source=Record.objects.select_related('source_row__batch').get(dataset='units',business_key=unit_id).source_row
    return {'unit':unit,'product':next(p for p in d['products'] if p['id']==unit['product_id']),'work_order':wo,'allocations':allocations,'orders':orders,'order_lines':lines,'customers':customers,'batches':[b for b in d['batches'] if b['id'] in batch_ids],'genealogy':links,'operations':[o for o in d['operations'] if o['object_id']==unit_id or o['object_id'] in batch_ids],'sessions':sessions,'measurements':measurements,'releases':[r for r in d['releases'] if r['unit_id']==unit_id],'shipments':shipments,'nonconformities':[n for n in d['nonconformities'] if n['unit_id']==unit_id],'service':[s for s in d['service'] if s['unit_id']==unit_id],'source':{'batch':str(source.batch_id),'file':source.batch.filename,'sheet':source.sheet,'row':source.row_number},'notice':'全为模拟数据。原始检测文件名是模拟引用，尚未附带设备原文件；检验限值不能用于真实放行。'}
