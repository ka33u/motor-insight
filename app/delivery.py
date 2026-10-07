"""Order-line delivery workspace, computed only from committed Excel facts.

Current snapshot, not a prediction. No stock reservation or document readiness
is inferred. A shared work order does not establish an SN's order ownership.
"""
from collections import Counter, defaultdict
from datetime import date
from functools import lru_cache
from . import analytics

STAGES={'all':'全部订单行','open':'仍有未交','overdue':'逾期未交','quality':'检测/放行待处理','ready':'已放行未发','unknown':'数据待核对'}
UNIT_STAGES={'all':'全部明确归属SN','untested':'未检测','incomplete':'检测不完整','failed':'检测不合格','waiting_release':'合格待有效放行','ready':'已放行未发','shipped':'已发货'}
NOTE='以当前导入计划和发货事实计算，截止时间为模拟快照。承诺日期筛选订单行，不重放历史状态。已放行未发仅表示当前检测和放行证据满足检查，未验证物料预留、包装证明和信用条件。'
RELEASE_RULE='当前有效放行要求：最新未作废检测完整合格，最近放行记录为批准放行、引用该会话，且发生在检测和装配之后。若后续新增检测或撤销放行，重新进入核验。此为演示规则v1，需业务审定。'

def index(rows):return {r['id']:r for r in rows}
def grouped(rows,key):
    out=defaultdict(list)
    for r in rows:out[r[key]].append(r)
    return out
def ref(dataset,key):return {'dataset':dataset,'key':key}

def build(d):
    as_of=analytics.AS_OF;today=date.fromisoformat(as_of[:10]);day=today.isoformat()
    products=index(d['products']);orders=index(d['orders']);customers=index(d['customers']);wos=index(d['work_orders']);lines=index(d['order_lines'])
    alloc=[a for a in d['allocations'] if a['effective']<=day]
    by_line=grouped(alloc,'order_line_id');by_wo=grouped(alloc,'work_order_id')
    plans=grouped(d['delivery_plans'],'order_line_id')
    shipping=[s for s in d['shipments'] if s['shipped']<=as_of]
    ship_index=index(shipping);ship_line=grouped(shipping,'order_line_id');ship_plan=grouped(shipping,'delivery_plan_id')
    packs=[x for x in d['shipment_units'] if x['shipment_id'] in ship_index]
    pack_unit=grouped(packs,'unit_id');pack_ship=grouped(packs,'shipment_id')
    releases=grouped([r for r in d['releases'] if r['released']<=as_of],'unit_id')
    sessions,inconsistent=analytics.quality_state(d)
    measurements=grouped(d['measurements'],'session_id');bad=set(inconsistent)
    wo_units=defaultdict(list);unit_index=index(d['units'])
    for u in d['units']:
        if u['assembly_at']>as_of:continue
        ss=sessions[u['id']];latest=ss[-1] if ss else None
        release=max(releases[u['id']],key=lambda r:(r['released'],r['id']),default=None)
        result=latest['calculated_result'] if latest else '未检测'
        release_ok=bool(latest and release and result=='合格' and latest['tested']>=u['assembly_at'] and release['status']=='批准放行' and release['session_id']==latest['id'] and release['released']>=max(latest['tested'],u['assembly_at']))
        ps=pack_unit[u['id']];shipped=bool(ps)
        problem=any(s['id'] in bad or s['tested']<u['assembly_at'] or any(m['id'] in bad for m in measurements[s['id']]) for s in ss)
        stage='shipped' if shipped else 'untested' if not latest else 'incomplete' if result=='不完整' else 'failed' if result=='不合格' else 'ready' if release_ok else 'waiting_release'
        shipment_ids=sorted({x['shipment_id'] for x in ps})
        wo_units[u['work_order_id']].append({'id':u['id'],'product_id':u['product_id'],'work_order_id':u['work_order_id'],'assembly_at':u['assembly_at'],'quality':result,'stage':stage,'stage_label':UNIT_STAGES[stage],'session_count':len(ss),'session_id':latest['id'] if latest else None,'tested':latest['tested'] if latest else None,'release_id':release['id'] if release else None,'release_valid':release_ok,'shipped':shipped,'shipment_ids':shipment_ids,'shipment_lines':sorted({ship_index[x]['order_line_id'] for x in shipment_ids}),'post_shipment_attention':bool(shipped and not release_ok),'data_inconsistent':problem,'_sources':[ref('units',u['id'])]+[ref('test_sessions',s['id']) for s in ss]+[ref('releases',r['id']) for r in releases[u['id']]]})
    operations=grouped([r for r in d['operations'] if r['started']<=as_of],'work_order_id')
    result=[]
    for line in d['order_lines']:
        order=orders.get(line['order_id'])
        if not order or order['order_date']>day:continue
        p=products.get(line['product_id'],{});customer=customers.get(order['customer_id'],{})
        aa=by_line[line['id']];woids=sorted({a['work_order_id'] for a in aa});issues=[]
        ambiguous=any(len({a['order_line_id'] for a in by_wo[w]})!=1 for w in woids)
        if ambiguous:issues.append('存在共用工单，未建立逐SN订单分配；生产和质量数量暂不归入此订单行。')
        if any(w not in wos or wos[w]['product_id']!=line['product_id'] for w in woids):issues.append('工单与订单配置不一致或引用缺失。')
        allocated=sum(a['qty'] for a in aa)
        if allocated>line['qty']:issues.append('工单分配数量超过订单数量。')
        if any(sum(a['qty'] for a in by_wo[w])>wos.get(w,{}).get('planned_qty',0) for w in woids):issues.append('工单的订单分配总量超过计划数量。')
        uu=sorted([u for w in woids for u in wo_units[w]],key=lambda u:u['id'])
        if any(u['product_id']!=line['product_id'] for u in uu):issues.append('工单内整机配置与订单不一致。')
        if any(u['shipment_lines'] and u['shipment_lines']!=[line['id']] for u in uu):issues.append('装箱SN的发货订单与工单归属冲突。')
        ownership_ok=not issues
        unit_rows=uu if ownership_ok else []
        if any(u['data_inconsistent'] for u in uu):issues.append('检测原始结论、规范重算结果或检测与装配时间顺序存在差异，请核对。')
        if len(uu)>line['qty'] and ownership_ok:issues.append('明确归属的装配台数超过订单数量。')
        shipped=sum(s['qty'] for s in ship_line[line['id']]);remaining=max(0,line['qty']-shipped)
        if shipped>line['qty']:issues.append('发货台数超过订单数量。')
        for s in ship_line[line['id']]:
            packed=[x['unit_id'] for x in pack_ship[s['id']]]
            if len(packed)!=len(set(packed)) or len(set(packed))!=s['qty']:issues.append('发货行数量与装箱SN不一致：'+s['id'])
            for uid in packed:
                u=unit_index.get(uid)
                if not u or u['assembly_at']>s['shipped']:issues.append('装箱SN缺少发货前装配记录：'+uid)
                elif u['product_id']!=line['product_id'] or u['work_order_id'] not in woids:issues.append('装箱SN配置或工单分配不符合当前订单：'+uid)
                if len({x['shipment_id'] for x in pack_unit[uid]})>1:issues.append('同一SN关联多个发货行：'+uid)
            plan=next((x for x in plans[line['id']] if x['id']==s['delivery_plan_id']),None)
            if not plan:issues.append('发货引用的交付计划不属于此订单行：'+s['id'])
        all_packed=[x['unit_id'] for s in ship_line[line['id']] for x in pack_ship[s['id']]]
        if len(all_packed)!=len(set(all_packed)):issues.append('同一SN在当前订单行中重复发货。')
        pl=[]
        for plan in sorted(plans[line['id']],key=lambda r:(r['due'],r['id'])):
            ss=ship_plan[plan['id']];delivered=sum(s['qty'] for s in ss if s['order_line_id']==line['id']);on_time=sum(s['qty'] for s in ss if s['order_line_id']==line['id'] and s['shipped'][:10]<=plan['due'])
            left=max(0,plan['qty']-delivered);expired=plan['due']<day;due=expired
            if delivered>plan['qty']:issues.append('交付计划发货量超过约定量：'+plan['id'])
            pl.append({**plan,'shipped_qty':delivered,'remaining_qty':left,'on_time_qty':on_time,'due_count':int(due),'on_time_count':int(due and on_time>=plan['qty']),'overdue_qty':left if expired else 0,'days_late':max(0,(today-date.fromisoformat(plan['due'])).days) if left else 0,'status':'已足量发货' if not left else '逾期未交' if expired else '今日到期' if plan['due']==day else '尚未到期'})
        if not pl or sum(x['qty'] for x in pl)!=line['qty']:issues.append('交付计划数量与订单数量不相等或计划缺失。')
        stages=Counter(u['stage'] for u in unit_rows)
        overdue=sum(x['overdue_qty'] for x in pl);post=sum(u['post_shipment_attention'] for u in unit_rows)
        work=[]
        for wid in woids:
            if wid not in wos:continue
            w=wos[wid];processes=grouped(operations[wid],'process');process_rows=[]
            # Branch-local route sequence numbers are not comparable across
            # stator, rotor and final assembly. Order actual evidence by time.
            for name,events in sorted(processes.items(),key=lambda x:(min(e['started'] for e in x[1]),x[0])):
                ended=[e for e in events if e.get('finished') and e['finished']<=as_of]
                process_rows.append({'name':name,'event_count':len(events),'completed_events':len(ended),'active_events':len(events)-len(ended),'last_finished':max((e['finished'] for e in ended),default=None),'source_ids':[e['id'] for e in events]})
            work.append({'id':wid,'product_id':w['product_id'],'planned_qty':w['planned_qty'],'planned_start':w['planned_start'],'planned_end':w['planned_end'],'status':w['status'],'bom_version':w['bom_version'],'route_version':w['route_version'],'allocated_qty':sum(a['qty'] for a in aa if a['work_order_id']==wid),'produced_qty':len(wo_units[wid]),'shared':len({a['order_line_id'] for a in by_wo[wid]})>1,'processes':process_rows})
        quality_wait=sum(stages[k] for k in ['untested','incomplete','failed','waiting_release']) if ownership_ok else None
        issues=list(dict.fromkeys(issues))
        flags=['all']+(['open'] if remaining else [])+(['overdue'] if overdue else [])+(['quality'] if quality_wait or post else [])+(['ready'] if stages['ready'] else [])+(['unknown'] if issues else [])
        action='核对数据关联与数量' if issues else '协调逾期计划与实际可用对象' if overdue else '核对检测/放行证据' if quality_wait or post else '协调已放行对象的发运条件' if stages['ready'] else '补齐工单分配' if allocated<line['qty'] else '核对未形成装配记录的工单' if remaining and not unit_rows else '关注后续承诺' if remaining else '核对签收与交付资料'
        result.append({'id':line['id'],'order_id':order['id'],'customer_id':order['customer_id'],'customer':customer.get('name',order['customer_id']),'customer_po':order.get('customer_po',''),'product_id':line['product_id'],'family':p.get('family','未知'),'power_kw':p.get('power_kw'),'order_date':order['order_date'],'due':line['due'],'original_due':line.get('original_due',line['due']),'custom_requirement':line.get('custom_requirement',''),'change_reason':line.get('change_reason'),'qty':line['qty'],'allocated_qty':allocated,'unallocated_qty':max(0,line['qty']-allocated),'produced_qty':len(unit_rows) if ownership_ok else None,'production_gap':max(0,line['qty']-len(unit_rows)) if ownership_ok else None,'shipped_qty':shipped,'remaining_qty':remaining,'overdue_qty':overdue,'due_plan_count':sum(x['due_count'] for x in pl),'on_time_plan_count':sum(x['on_time_count'] for x in pl),'ownership_ok':ownership_ok,'stages':{k:stages[k] if ownership_ok else None for k in UNIT_STAGES if k!='all'},'quality_wait_qty':quality_wait,'post_shipment_attention':post if ownership_ok else None,'issues':issues,'flags':flags,'next_action':action,'order_status':order.get('status'),'_plans':pl,'_work_orders':work,'_units':unit_rows,'_shipments':ship_line[line['id']], '_sources':[ref('order_lines',line['id']),ref('orders',order['id']),ref('products',line['product_id']),ref('customers',order['customer_id'])]+[ref('allocations',a['id']) for a in aa]})
    return result

@lru_cache(maxsize=1)
def _built(revision):return build(analytics._tables(revision))
def rows():return _built(analytics.revision())

def filters(query):
    allowed={'family','customer_id','q','due_from','due_to','stage','page','size','unit_stage','unit_page'}
    if set(query)-allowed:raise ValueError('不支持的交付筛选字段')
    clean={k:str(query.get(k,'')).strip() for k in ['family','customer_id','q','due_from','due_to']}
    if any(len(v)>150 for v in clean.values()):raise ValueError('筛选内容过长')
    for key in ['due_from','due_to']:
        if clean[key] and date.fromisoformat(clean[key]).isoformat()!=clean[key]:raise ValueError('日期必须为YYYY-MM-DD')
    if clean['due_from']> (clean['due_to'] or '9999-12-31'):raise ValueError('开始日期不能晚于结束日期')
    clean['stage']=query.get('stage','open')
    if clean['stage'] not in STAGES:raise ValueError('交付状态筛选不可用')
    return clean

def select(all_rows,f):
    found=[]
    for r in all_rows:
        if f['family'] and r['family']!=f['family']:continue
        if f['customer_id'] and r['customer_id']!=f['customer_id']:continue
        if f['due_from'] and r['due']<f['due_from']:continue
        if f['due_to'] and r['due']>f['due_to']:continue
        if f['q'] and f['q'].lower() not in ' '.join(str(r[k]) for k in ['id','order_id','customer','customer_po','product_id','custom_requirement']).lower():continue
        found.append(r)
    facets={key:sum(key in r['flags'] for r in found) for key in STAGES}
    return sorted([r for r in found if f['stage'] in r['flags']],key=lambda r:(r['due'],-r['remaining_qty'],r['id'])),facets

def summary(chosen):
    totals={k:sum(r[k] for r in chosen) for k in ['qty','remaining_qty','overdue_qty','due_plan_count','on_time_plan_count']}
    totals.update(line_count=len(chosen),order_count=len({r['order_id'] for r in chosen}),ready_qty=sum(r['stages']['ready'] or 0 for r in chosen),quality_wait_qty=sum(r['quality_wait_qty'] or 0 for r in chosen),unknown_lines=sum(not r['ownership_ok'] for r in chosen),issue_lines=sum(bool(r['issues']) for r in chosen))
    totals['otif_pct']=analytics.percent(totals['on_time_plan_count'],totals['due_plan_count'])
    return totals

def public_row(row):return {k:v for k,v in row.items() if not k.startswith('_')}
