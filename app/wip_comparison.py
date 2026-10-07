"""Same business cutoff, fixed right-hand root cohort, two registration cutoffs."""
from collections import Counter
from . import wip_flow as eng

OUTCOME=['state','baseline_qty','wip_qty','prefix_consumed_qty','prefix_scrap_qty','unknown_remainder','positions','issues','expected_consumption_sn','missing_consumption_sn']
LABELS={'state':'核对状态','baseline_qty':'有效基准','wip_qty':'可核对在制','prefix_consumed_qty':'有效前缀耗用','prefix_scrap_qty':'有效前缀报废','unknown_remainder':'未核定余量','positions':'位置或份额','issues':'核查原因','expected_consumption_sn':'装配引用','missing_consumption_sn':'缺耗用登记'}
NOTE='固定右侧筛选及状态命中的原批次ID，在相同业务截止下对照当时登记与右侧登记截止。不重新按左侧状态或周转号选对象。件数差只在两侧同批次均可核对时计算；新增/失去可核对的对象另列，未知不作零。版本变化不等于业务改善。'+eng.TIME_NOTE

def canonical(r,key):
    value=r[key]
    if key=='positions':return sorted(value,key=lambda p:(p['lot_id'],p['location_id']))
    if isinstance(value,list):return sorted(value)
    return value
def event_state(e):
    # Newly known events after the business cutoff are not historical changes.
    if e['future']:return None
    return dict(selected_id=e['header']['id'] if e['header'] else None,applied=e['applied'],future=e['future'],withdrawn=e['withdrawn'],issues=sorted(set(e['issues'])))
def event_map(d,key):
    return {e['series']:e for e in d.events if key in e['roots'] or key in e['history_roots']}
def small(r):
    return {k:r[k] for k in OUTCOME if k not in ['expected_consumption_sn','missing_consumption_sn']}|dict(expected_consumption_count=len(r['expected_consumption_sn']),missing_consumption_count=len(r['missing_consumption_sn']),state_label=eng.STATES[r['state']])
def row(before,after,key):
    a,b=before.index[key],after.index[key]
    differences=[LABELS[k] for k in OUTCOME if canonical(a,k)!=canonical(b,k)]
    ae,be=event_map(before,key),event_map(after,key);versions=[]
    for series in sorted(ae.keys()|be.keys()):
        x=event_state(ae[series]) if series in ae else None;y=event_state(be[series]) if series in be else None
        if x!=y:versions.append(dict(series=series,before=x,after=y))
    ax=sorted(x['id'] for x in before.origins[key]);bx=sorted(x['id'] for x in after.origins[key])
    outcome=bool(differences);evidence=bool(versions or ax!=bx)
    return dict(id=key,work_order_id=b['work_order_id'],product_id=b['product_id'],kind=b['kind'],created=b['created'],before=small(a),after=small(b),
        outcome_changed=outcome,evidence_changed=evidence,change_type='结果改变' if outcome else '仅依据改变' if evidence else '未改变',
        differences=differences,version_changes=versions,opening_before=ax,opening_after=bx,
        wip_delta=None if a['wip_qty'] is None or b['wip_qty'] is None else b['wip_qty']-a['wip_qty'])
def comparison(before,after,selected):
    assert before.cutoff==after.cutoff and before.known_cutoff<=after.known_cutoff
    rows=[row(before,after,r['id']) for r in selected];counts=Counter(r['change_type'] for r in rows);groups=[]
    for kind in ['定子','转子']:
        rr=[r for r in rows if r['kind']==kind];both=[r for r in rr if r['wip_delta'] is not None]
        groups.append(dict(kind=kind,objects=len(rr),both_verified=len(both),before_comparable_wip=sum(r['before']['wip_qty'] for r in both),after_comparable_wip=sum(r['after']['wip_qty'] for r in both),comparable_delta=sum(r['wip_delta'] for r in both),
            before_unknown=sum(r['before']['wip_qty'] is None for r in rr),after_unknown=sum(r['after']['wip_qty'] is None for r in rr),
            gained_verification=sum(r['before']['wip_qty'] is None and r['after']['wip_qty'] is not None for r in rr),lost_verification=sum(r['before']['wip_qty'] is not None and r['after']['wip_qty'] is None for r in rr)))
    changed=[r for r in rows if r['change_type']!='未改变'];changed.sort(key=lambda r:(not r['outcome_changed'],r['kind'],r['id']))
    return dict(as_of=after.cutoff,before_known_as_of=before.known_cutoff,after_known_as_of=after.known_cutoff,summary=dict(objects=len(rows),outcome_changed=counts['结果改变'],evidence_only=counts['仅依据改变'],unchanged=counts['未改变'],groups=groups),changed=changed,all_rows=rows,note=NOTE)
