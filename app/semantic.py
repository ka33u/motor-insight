"""Business views preaggregate facts before joining them to a stable grain."""
from collections import defaultdict,Counter
from datetime import datetime,timedelta
from decimal import Decimal,ROUND_HALF_UP
from functools import lru_cache
from . import analytics
from .semantic_schema import SEMANTIC_SCHEMAS

def cents(value):return int(Decimal(str(value)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def group(rows,field):
    result=defaultdict(list)
    for row in rows:result[row[field]].append(row)
    return result
def refs(*groups):return [{'dataset':dataset,'key':row['id']} for dataset,rows in groups for row in rows]
def with_refs(row,*groups):return {**row,'_sources':refs(*groups)}
def by_id(rows):return {r['id']:r for r in rows}
def union_minutes(intervals):
    end=None;seconds=0
    for a,b in sorted(intervals):
        if b<=a:continue
        start=max(a,end) if end else a
        if b>start:seconds+=(b-start).total_seconds()
        end=max(end,b) if end else b
    return seconds/60
def day_segments(start,end):
    current=datetime.fromisoformat(start);end=datetime.fromisoformat(end)
    while current<end:
        boundary=datetime.combine(current.date()+timedelta(days=1),datetime.min.time());stop=min(boundary,end)
        yield current.date().isoformat(),current,stop
        current=stop

def build(d):
    cutoff=analytics.AS_OF;day=cutoff[:10];products=by_id(d['products']);orders=by_id(d['orders']);customers=by_id(d['customers']);lines=by_id(d['order_lines']);work_orders=by_id(d['work_orders'])
    allocations=group([a for a in d['allocations'] if a['effective']<=day],'work_order_id');alloc_by_line=group([a for a in d['allocations'] if a['effective']<=day],'order_line_id')
    units=[u for u in d['units'] if u['assembly_at']<=cutoff];unit_by_wo=group(units,'work_order_id')
    sessions,_=analytics.quality_state(d);release_by_unit=group([r for r in d['releases'] if r['released']<=cutoff and r['status']=='批准放行'],'unit_id')
    measurements_by_session=group(d['measurements'],'session_id');specs_by_product=group(d['test_specs'],'product_id')
    shipments=[s for s in d['shipments'] if s['shipped']<=cutoff];ship_by_id=by_id(shipments);ship_by_line=group(shipments,'order_line_id');ship_by_plan=group(shipments,'delivery_plan_id')
    packed=group([p for p in d['shipment_units'] if p['shipment_id'] in ship_by_id],'unit_id');plans_by_line=group(d['delivery_plans'],'order_line_id')
    cost_by_wo=group([c for c in d['costs'] if c['occurred']<=day],'work_order_id');unit_rows=[]
    for u in units:
        p=products[u['product_id']];ss=sessions[u['id']];complete=[s for s in ss if s['calculated_complete']];first=complete[0] if complete else None
        assigned={a['order_line_id'] for a in allocations[u['work_order_id']]};customer=None
        if len(assigned)==1:customer=customers[orders[lines[next(iter(assigned))]['order_id']]['customer_id']]['name']
        approved=sorted(release_by_unit[u['id']],key=lambda r:r['released']);hours=(datetime.fromisoformat(approved[0]['released'])-datetime.fromisoformat(u['assembly_at'])).total_seconds()/3600 if approved else None
        measurements=[m for s in ss for m in measurements_by_session[s['id']]]
        unit_rows.append(with_refs({'id':u['id'],'work_order_id':u['work_order_id'],'product_id':u['product_id'],'family':p['family'],'power_kw':p['power_kw'],'voltage':p['voltage'],'customer':customer,'assembly_at':u['assembly_at'],'stator_batch':u['stator_batch'],'rotor_batch':u['rotor_batch'],'session_count':len(ss),'first_tested_count':int(bool(first)),'first_pass_count':int(bool(first and first['calculated_result']=='合格')),'complete_count':int(bool(complete)),'latest_result':ss[-1]['calculated_result'] if ss else '未检测','first_equipment':first['equipment_id'] if first else None,'released_count':int(bool(approved)),'shipped_count':int(bool(packed[u['id']])),'release_hours':round(hours,4) if hours is not None and hours>=0 else None,'status':u['status']},('units',[u]),('products',[p]),('test_sessions',ss),('test_specs',specs_by_product[p['id']]),('measurements',measurements),('releases',approved),('shipment_units',packed[u['id']]),('allocations',allocations[u['work_order_id']])))
    unit_metrics=group(unit_rows,'work_order_id');order_rows=[]
    for line in d['order_lines']:
        order=orders[line['order_id']]
        if order['order_date']>day:continue
        p=products[line['product_id']];customer=customers[order['customer_id']];shipped=sum(s['qty'] for s in ship_by_line[line['id']]);plans=plans_by_line[line['id']];due=[p for p in plans if p['due']<day]
        overdue=sum(max(0,p['qty']-sum(s['qty'] for s in ship_by_plan[p['id']])) for p in due);ontime=sum(sum(s['qty'] for s in ship_by_plan[p['id']] if s['shipped'][:10]<=p['due'])>=p['qty'] for p in due)
        alloc=alloc_by_line[line['id']];woids={a['work_order_id'] for a in alloc};ambiguous=any(len({a['order_line_id'] for a in allocations[w]})>1 for w in woids)
        produced=None if ambiguous else sum(len(unit_by_wo[w]) for w in woids)
        order_rows.append(with_refs({'id':line['id'],'order_id':order['id'],'customer':customer['name'],'region':customer['region'],'product_id':p['id'],'family':p['family'],'power_kw':p['power_kw'],'order_date':order['order_date'],'due':line['due'],'qty':line['qty'],'allocated_qty':sum(a['qty'] for a in alloc),'produced_qty':produced,'shipped_qty':shipped,'remaining_qty':max(0,line['qty']-shipped),'overdue_qty':overdue,'due_plan_count':len(due),'on_time_plan_count':ontime,'order_net_cents':line['qty']*line['unit_price_cents'],'custom_requirement':line['custom_requirement'],'attribution':'共用工单，SN归属待明确' if ambiguous else '工单唯一归属'},('order_lines',[line]),('orders',[order]),('customers',[customer]),('products',[p]),('delivery_plans',plans),('allocations',alloc),('work_orders',[work_orders[w] for w in sorted(woids)]),('units',[u for w in sorted(woids) for u in unit_by_wo[w]] if not ambiguous else []),('shipments',ship_by_line[line['id']])))
    wo_rows=[]
    for w in d['work_orders']:
        p=products[w['product_id']];uu=unit_metrics[w['id']];costs=cost_by_wo[w['id']];total=sum(c['amount_cents'] for c in costs)
        wo_rows.append(with_refs({'id':w['id'],'product_id':p['id'],'family':p['family'],'planned_end':w['planned_end'],'planned_qty':w['planned_qty'],'produced_qty':len(uu),'first_tested_count':sum(u['first_tested_count'] for u in uu),'first_pass_count':sum(u['first_pass_count'] for u in uu),'released_qty':sum(u['released_count'] for u in uu),'pending_qty':max(0,w['planned_qty']-len(uu)),'total_cost_cents':total,'material_cost_cents':sum(c['amount_cents'] for c in costs if c['category']=='材料'),'unit_cost_cents':round(total/len(uu),2) if uu else None,'status':w['status']},('work_orders',[w]),('products',[p]),('units',unit_by_wo[w['id']]),('costs',costs)))
    materials=by_id(d['materials']);stocks=defaultdict(lambda:{'opening':[],'movements':[],'states':[]})
    for name,field,stamp in [('inventory_opening','opening','as_of'),('inventory_movements','movements','occurred'),('inventory_status_events','states','occurred')]:
        for r in d.get(name,[]):
            if r[stamp]>(day if stamp=='as_of' else cutoff):continue
            stocks[(r['material_id'],r['lot'],r['location'])][field].append(r)
    inventory=[]
    for (mid,lot,loc),source in sorted(stocks.items()):
        m=materials[mid];opens=source['opening'];moves=source['movements'];events=sorted(source['states'],key=lambda s:(s['occurred'],s['id']));state=opens[-1]['status'] if opens else '可用'
        for e in events:state=e['to_status']
        oq=sum(Decimal(str(s['qty'])) for s in opens);incoming=sum((Decimal(str(s['qty_signed'])) for s in moves if s['qty_signed']>0),Decimal(0));outgoing=-sum((Decimal(str(s['qty_signed'])) for s in moves if s['qty_signed']<0),Decimal(0));balance=oq+incoming-outgoing;price=opens[-1]['unit_cost_cents'] if opens else m['unit_cost_cents']
        inventory.append(with_refs({'id':f'{mid}|{lot}|{loc}','material_id':mid,'material':m['name'],'category':m['category'],'lot':lot,'location':loc,'unit':m['unit'],'opening_qty':float(oq),'inbound_qty':float(incoming),'outbound_qty':float(outgoing),'balance_qty':float(balance),'available_qty':float(balance) if state=='可用' else 0,'state':state,'reference_value_cents':cents(balance*price),'last_movement':max((s['occurred'] for s in moves),default=None)},('materials',[m]),('inventory_opening',opens),('inventory_movements',moves),('inventory_status_events',events)))
    suppliers=by_id(d['suppliers']);receipts=group([r for r in d['receipts'] if r['received']<=cutoff],'purchase_line_id');iqc=group([r for r in d['incoming_inspections'] if r['inspected']<=cutoff],'receipt_id');purchase=[]
    for p in d['purchase_lines']:
        if p['ordered']>day:continue
        rr=receipts[p['id']];inspections=[q for r in rr for q in iqc[r['id']]];m=materials[p['material_id']];received=sum(Decimal(str(r['qty'])) for r in rr);remaining=max(Decimal(0),Decimal(str(p['qty']))-received)
        latest_iqc={r['id']:max(iqc[r['id']],key=lambda q:(q['inspected'],q['id']),default={}) for r in rr}
        accepted=sum(Decimal(str(r['qty'])) for r in rr if r['status']=='检验合格' and latest_iqc[r['id']].get('result')=='合格' and latest_iqc[r['id']].get('disposition')=='批准入库')
        due=p['due']<=day;on_time=sum(Decimal(str(r['qty'])) for r in rr if r['received'][:10]<=p['due'])>=Decimal(str(p['qty']))
        purchase.append(with_refs({'id':p['id'],'supplier':suppliers[p['supplier_id']]['name'],'material_id':m['id'],'material':m['name'],'category':m['category'],'unit':m['unit'],'ordered':p['ordered'],'due':p['due'],'ordered_qty':p['qty'],'received_qty':float(received),'accepted_qty':float(accepted),'remaining_qty':float(remaining),'overdue_qty':float(remaining) if due else 0,'due_line_count':int(due),'on_time_line_count':int(due and on_time),'iqc_rejected_count':sum(q['result']=='不合格' for q in inspections),'status':p['status']},('purchase_lines',[p]),('suppliers',[suppliers[p['supplier_id']]]),('materials',[m]),('receipts',rr),('incoming_inspections',inspections)))
    payments=group([p for p in d['payments'] if p['paid']<=day],'invoice_id');ar=[]
    for inv in d['invoices']:
        if inv['issued']>day:continue
        customer=customers[inv['customer_id']];paid=sum(p['amount_cents'] for p in payments[inv['id']]);gross=inv['net_cents']+inv['tax_cents'];balance=max(0,gross-paid);days=max(0,(datetime.fromisoformat(day)-datetime.fromisoformat(inv['due'])).days) if balance else 0
        bucket='已结清' if not balance else '未到期' if not days else '1—30天' if days<=30 else '31—60天' if days<=60 else '61—90天' if days<=90 else '90天以上'
        ar.append(with_refs({'id':inv['id'],'customer':customer['name'],'region':customer['region'],'issued':inv['issued'],'due':inv['due'],'net_cents':inv['net_cents'],'tax_cents':inv['tax_cents'],'gross_cents':gross,'paid_cents':paid,'balance_cents':balance,'overdue_cents':balance if days else 0,'overdue_days':days,'aging_bucket':bucket,'status':inv['status']},('invoices',[inv]),('customers',[customer]),('payments',payments[inv['id']])) )
    equipment=by_id(d['equipment']);slots=defaultdict(lambda:{'intervals':[],'fault':[],'events':[],'maintenance':[]})
    for event in d['downtime']:
        for date,a,b in day_segments(event['started'],min(event['finished'],cutoff)):
            slot=slots[(event['equipment_id'],date)];slot['intervals'].append((a,b));slot['events'].append(event)
            if event['reason']=='设备故障':slot['fault'].append((a,b))
    for task in d['maintenance']:
        if task['reported']<=cutoff:slots[(task['equipment_id'],task['reported'][:10])]['maintenance'].append(task)
    equipment_days=[]
    for (eid,date),slot in sorted(slots.items()):
        e=equipment[eid];mm=slot['maintenance'];equipment_days.append(with_refs({'id':eid+'|'+date,'equipment_id':eid,'equipment':e['name'],'workshop':e['workshop'],'process':e['process'],'date':date,'downtime_events':len(slot['events']),'downtime_minutes':round(union_minutes(slot['intervals']),3),'fault_minutes':round(union_minutes(slot['fault']),3),'maintenance_count':len(mm),'maintenance_cost_cents':sum(m['cost_cents'] for m in mm)},('equipment',[e]),('downtime',slot['events']),('maintenance',mm)))
    energy_slots=defaultdict(lambda:{'rows':[],'kwh':Decimal(0),'cost':Decimal(0)})
    for r in d['energy']:
        duration=(datetime.fromisoformat(r['ended'])-datetime.fromisoformat(r['started'])).total_seconds()
        if duration<=0:continue
        for date,a,b in day_segments(r['started'],min(r['ended'],cutoff)):
            slot=energy_slots[(r['workshop'],date)];fraction=Decimal(str((b-a).total_seconds()))/Decimal(str(duration));kwh=Decimal(str(r['kwh']))*fraction
            slot['kwh']+=kwh;slot['cost']+=kwh*r['tariff_cents'];slot['rows'].append(r)
    energy_rows=[with_refs({'id':shop+'|'+date,'workshop':shop,'date':date,'readings':len(v['rows']),'kwh':float(v['kwh']),'energy_cost_cents':cents(v['cost'])},('energy',v['rows'])) for (shop,date),v in sorted(energy_slots.items())]
    from .production import resource_days
    return dict(bi_order_lines=order_rows,bi_work_orders=wo_rows,bi_units=unit_rows,bi_inventory=inventory,bi_purchase=purchase,bi_receivables=ar,bi_equipment_day=equipment_days,bi_energy_day=energy_rows,bi_resource_day=resource_days(d,cutoff))

@lru_cache(maxsize=1)
def _built(revision):return build(analytics._tables(revision))
def rows(dataset):return _built(analytics.revision())[dataset]
