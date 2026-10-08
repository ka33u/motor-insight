"""Read-only checks on the unchanged, normally imported public Excel snapshot."""
import hashlib,json,os,sys
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import wip_readiness,analytics
from app.models import Record

def verify():
    d,rev=wip_readiness.current();data=analytics._tables(rev);cutoff=datetime.fromisoformat(analytics.AS_OF)
    reported=set();open_orders=set();unknown=0
    for op in data['operations']:
        try:
            start=datetime.fromisoformat(op['started']);finish=datetime.fromisoformat(op['finished']) if op.get('finished') else None
            assert start.tzinfo is None and (finish is None or finish.tzinfo is None and finish>=start)
        except (ValueError,TypeError,AssertionError):unknown+=1;continue
        if start<=cutoff:
            reported.add(op['work_order_id'])
            if not finish or finish>cutoff:open_orders.add(op['work_order_id'])
    summary=d.summary(d.rows)
    assert summary['work_orders']==len(data['work_orders'])==312
    assert summary['reported']==len(reported)==200 and summary['open']==len(open_orders)==0
    assert summary['unknown_reports']==unknown==0
    assert summary['positions']==0 and summary['unknown']==119
    assert sum(r['orders'] for r in d.matrix(d.rows))==312
    for row in d.rows:
        assert row['remaining_task_qty'] is row['remaining_task_minutes'] is row['remaining_material_qty'] is None
        assert row['scheduling_state']=='not_computed'
        for g in row['wip_groups']:
            roots=[r for r in d.wip.rows if r['work_order_id']==row['id'] and r['kind']==g['kind']]
            known=[r for r in roots if r['state'] not in ('attention','missing') and r['baseline_qty'] is not None]
            assert g['roots']==len(roots) and g['verified_roots']==len(known)
            assert g['wip_qty']==(sum(r['wip_qty'] for r in known) if roots and len(roots)==len(known) else None)
    # Independent Decimal reconstruction for a released-return order; no report/assembly credit.
    key='MO-260928-Q002';wo=next(r for r in data['work_orders'] if r['id']==key)
    items=d.details[key]['materials'];assert len(items)==8
    bom=[b for b in data['bom'] if b['product_id']==wo['product_id'] and b['version']==wo['bom_version']]
    for item in items:
        b=[r for r in bom if r['material_id']==item['material_id']]
        need=sum(Decimal(wo['planned_qty'])*Decimal(str(r['qty']))*(1+Decimal(str(r['scrap_allowance']))) for r in b)
        if item['unit']=='件':need=need.to_integral_value(rounding='ROUND_CEILING')
        moves=[r for r in data['inventory_movements'] if r.get('work_order_id')==key and r['material_id']==item['material_id'] and r['occurred']<=analytics.AS_OF]
        issued=-sum(Decimal(str(r['qty_signed'])) for r in moves if r['movement']=='生产领料')
        returned=sum(Decimal(str(r['qty_signed'])) for r in moves if r['movement']=='生产退料')
        assert Decimal(str(item['gross_required']))==need
        assert Decimal(str(item['issued_qty']))==issued-returned
        assert Decimal(str(item['remaining_required']))==max(Decimal(0),need-issued+returned)
    hashes=Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash')
    digest=hashlib.sha256()
    for row in hashes:digest.update((json.dumps(row,ensure_ascii=False)+'\n').encode())
    assert digest.hexdigest()=='0a6c15c5ce7de3d94300758836d9e16dec97aa92dc7d2491c72910ae49b2d9db'
    result=dict(success=True,summary=summary,matrix=d.matrix(d.rows),independent_material_checks=8,records=234037,
                record_hash_digest=digest.hexdigest(),business_inputs_unchanged=True,remaining_schedule_computed=False,browser_acceptance=False)
    return result

if __name__=='__main__':
    result=verify();(ROOT/'data/wip_readiness_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
