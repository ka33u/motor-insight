"""Audit business semantics separately from XLSX type/key round-trip checks."""
import os,sys,json
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from decimal import Decimal,ROUND_HALF_UP
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from app.analytics import tables,indexed,quality_state

def audit():
    d=tables();materials=indexed(d['materials']);issues=defaultdict(list)
    initial={(r['material_id'],r['lot'],r['location']):r for r in d['inventory_opening']}
    states=defaultdict(list)
    for r in d.get('inventory_status_events',[]):states[(r['material_id'],r['lot'],r['location'])].append(r)
    for events in states.values():events.sort(key=lambda r:(r['occurred'],r['id']))
    for key,events in states.items():
        status=initial.get(key,{}).get('status','可用')
        for event in events:
            if event['from_status']!=status:issues['inventory_status_sequence_conflict'].append(event['id'])
            status=event['to_status']
    expected_material_cost=defaultdict(int)
    for r in d['inventory_movements']:
        key=(r['material_id'],r['lot'],r['location']);opening=initial.get(key);state=opening['status'] if opening else '可用'
        for event in states[key]:
            if event['occurred']<=r['occurred']:state=event['to_status']
        if r['qty_signed']<0 and state!='可用':issues['frozen_lot_consumed'].append(r['id'])
        if opening and r['occurred'][:10]<opening['as_of']:issues['movement_before_opening'].append(r['id'])
        if materials[r['material_id']]['unit']=='件' and not float(r['qty_signed']).is_integer():issues['fractional_indivisible_material'].append(r['id'])
        if r['qty_signed']<0 and r.get('work_order_id'):
            amount=Decimal(str(-r['qty_signed']))*Decimal(materials[r['material_id']]['unit_cost_cents'])
            expected_material_cost[r['work_order_id']]+=int(amount.quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    actual_material_cost=defaultdict(int)
    for row in d['costs']:
        if row['category']=='材料':actual_material_cost[row['work_order_id']]+=row['amount_cents']
    for wo in set(expected_material_cost)|set(actual_material_cost):
        if expected_material_cost[wo]!=actual_material_cost[wo]:issues['material_cost_not_reconciled_to_issue'].append(wo)
    for r in d['energy']:
        if r['started']>=r['ended']:issues['nonpositive_meter_interval'].append(r['id'])
    units=indexed(d['units']);sessions=indexed(d['test_sessions']);release=indexed(d['releases'])
    for r in d['test_sessions']:
        if r['tested']<units[r['unit_id']]['assembly_at']:issues['test_before_assembly'].append(r['id'])
    for r in d['releases']:
        s=sessions[r['session_id']]
        if s['unit_id']!=r['unit_id'] or s['result']!='合格' or s['tested']>r['released']:issues['invalid_release_evidence'].append(r['id'])
    by_resource=defaultdict(list)
    for r in d['operations']:
        if r['finished']:by_resource[r['equipment_id']].append(r)
        if r['finished'] and r['finished']<r['started']:issues['operation_reversed_time'].append(r['id'])
    peaks={}
    for resource,rows in by_resource.items():
        events=[]
        for r in rows:events.extend([(r['started'],1),(r['finished'],-1)])
        running=0;peak=0
        for _,delta in sorted(events,key=lambda e:(e[0],e[1])):running+=delta;peak=max(peak,running)
        peaks[resource]=peak
    from app.production import audit as production_audit
    from app.analytics import AS_OF
    production=production_audit(d,AS_OF) if d.get('production_resources') else None
    unresolved=[] if production else [{'equipment':k,'peak_simultaneous_events':v} for k,v in peaks.items() if v>1]
    _,mismatches=quality_state(d)
    next_actions=(['Resolve current semantic findings before using the affected quantities.'] if issues else [])+['Calibrate resource capacity, staffing and process standards with actual factory evidence before OEE or production commitments.','Add historical finance and longer production periods for overdue cash, seasonality and cohort analysis.']
    result={'record_count':sum(map(len,d.values())),'blocking_semantic_findings':{k:{'count':len(v),'examples':v[:8]} for k,v in issues.items()},'quality_recalculation_differences':len(mismatches),'capacity_definition_required':unresolved,'scope':'Checks imported synthetic records. Passing keys and Excel round-trip does not prove production realism.','next_actions':next_actions}
    result['production_constraints']=production
    return result

if __name__=='__main__':
    result=audit();(ROOT/'data/business_semantics_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
