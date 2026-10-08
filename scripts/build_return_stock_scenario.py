"""Create a JSON authoring intermediate for synthetic Excel, never business records."""
import json,os,sys
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app import analytics,supply,return_stock


def main():
    source='CP.00008.A';product=Record.objects.get(dataset='products',business_key=source).values
    base={ds:[r.values for r in Record.objects.filter(dataset=ds,values__product_id=source).order_by('business_key')] for ds in ('bom','routes','route_dependencies')}
    approver=Record.objects.filter(dataset='inventory_status_events').order_by('business_key').first().values['approver_id']
    assert Record.objects.get(dataset='employees',business_key=approver).values['active']
    tables={ds:[] for ds in ('materials','products','bom','routes','route_dependencies','work_orders','inventory_opening','inventory_movements','inventory_status_events')}
    ids={}
    for index in (1,2):
        pid=f'CP.0910{index}.A';ids[index]={};tables['products'].append(dict(product,id=pid,drawing=f'DJ-0910{index}-A'))
        for old in sorted({r['material_id'] for r in base['bom']}):
            material=Record.objects.get(dataset='materials',business_key=old).values
            mid=old.rsplit('.',1)[0]+f'.910{index}';ids[index][old]=mid
            tables['materials'].append(dict(material,id=mid,safety_qty=0))
            if old!='01.01.0002':tables['inventory_opening'].append(dict(id=f'QC-260901-RQ{index}-{mid}',material_id=mid,lot=f'RTQ2609-{index}-{mid}',location='YL-RQ-'+str(index),as_of='2026-09-01',qty=1000,unit_cost_cents=material['unit_cost_cents'],status='可用'))
        for row in base['bom']:tables['bom'].append(dict(row,id=row['id'].replace('00008',f'0910{index}'),product_id=pid,material_id=ids[index][row['material_id']]))
        routes={r['id']:r['id'].replace('00008',f'0910{index}') for r in base['routes']}
        tables['routes'] += [dict(r,id=routes[r['id']],product_id=pid) for r in base['routes']]
        tables['route_dependencies'] += [dict(r,id=r['id'].replace('00008',f'0910{index}'),product_id=pid,from_route_id=routes[r['from_route_id']],to_route_id=routes[r['to_route_id']]) for r in base['route_dependencies']]
    reasons={2:'模拟登记：退料后待检转可用；之后再次领用1 kg。未附逐退料检验报告。',3:'模拟登记：待检转隔离，不可供生产领用。',4:'模拟矛盾：登记原状态可用，期初实际登记待检；保留矛盾供核对。',5:'模拟登记：状态变更与退料同刻，原始资料没有先后顺序。',6:'模拟未来登记：10月2日转可用，不在当前业务截止内。',7:'模拟登记：同一目标库位两笔退料后转可用，库存余额不能重复计数。'}
    for n in range(1,8):
        index=2 if n==4 else 1;work=f'MO-260928-Q{n:03d}';mid=ids[index]['01.01.0002'];lot=f'RTQ2609-{n:03d}';loc=f'DJ-RQ-{n:02d}'
        tables['work_orders'].append(dict(id=work,product_id=f'CP.0910{index}.A',planned_qty=4,planned_start='2026-09-28',planned_end='2026-10-06',priority='普通',status='已下达',bom_version=product['bom_version'],route_version=product['route_version']))
        material=next(r for r in tables['materials'] if r['id']==mid)
        opening=dict(id=f'QC-260901-RQ{n:03d}-01',material_id=mid,lot=lot,location='YL-RQ-'+str(n),as_of='2026-09-01',qty=100,unit_cost_cents=material['unit_cost_cents'],status='可用')
        tables['inventory_opening'] += [opening,dict(opening,id=f'QC-260901-RQ{n:03d}-02',location=loc,qty=0,status='待检')]
        original=dict(id=f'CK-260928-Q{n:03d}-01',material_id=mid,lot=lot,location=opening['location'],occurred='2026-09-28T08:00:00',movement='生产领料',qty_signed=-(6 if n==7 else 10),work_order_id=work,reference=work)
        tables['inventory_movements'].append(original)
        for j,qty in enumerate({1:[3],2:[4],3:[5],4:[2],5:[3],6:[2],7:[1,2]}[n],1):
            tables['inventory_movements'].append(dict(original,id=f'TL-260930-Q{n:03d}-{j:02d}',location=loc,occurred=f'2026-09-30T09:0{j}:00',movement='生产退料',qty_signed=qty,reference=original['id']))
        if n in reasons:
            when='2026-09-30T09:01:00' if n==5 else '2026-10-02T09:00:00' if n==6 else '2026-10-01T09:00:00'
            tables['inventory_status_events'].append(dict(id=f'ZT-261001-RQ{n:03d}',material_id=mid,lot=lot,location=loc,occurred=when,from_status='可用' if n==4 else '待检',to_status='隔离' if n==3 else '可用',reason=reasons[n],approver_id=approver))
        if n==2:tables['inventory_movements'].append(dict(original,id='CK-261001-Q002-02',location=loc,occurred='2026-10-01T10:00:00',qty_signed=-1))
    combined=deepcopy(analytics._tables(analytics.revision()))
    for ds,rows in tables.items():
        assert len({r['id'] for r in rows})==len(rows)
        existing={r['id']:r for r in combined[ds]}
        for row in rows:
            if row['id'] in existing:assert row==existing[row['id']]
            else:combined[ds].append(row)
    d=return_stock.ReturnStock(supply.SupplyData(combined));f=return_stock.filters({'q':'MO-260928-Q'});rows=d.cohort(f)
    assert len(rows)==8 and d.summary(rows)==dict(returns=8,target_lots=7,documents_verified=8,current_verified=7,arrival_known=7,attention=2)
    u=d.units(rows)[0];assert (u['returned_qty'],u['target_balance_qty'],u['target_usable_qty'],u['unknown_lots'])==(22,21,None,1)
    normal=d.cohort(return_stock.filters({'material_id':'01.01.9101'}));u=d.units(normal)[0]
    assert (u['returned_qty'],u['target_balance_qty'],u['target_usable_qty'],u['target_lots'])==(20,19,9,6)
    profiles=[{k:r[k] for k in ('id','work_order_id','qty_signed','document_verified','arrival_state','current_state','flags')} for r in rows]
    out=dict(synthetic=True,source_product=source,tables=tables,schemas={ds:SCHEMAS[ds] for ds in tables},profiles=profiles)
    (ROOT/'data/return_stock_scenario.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(rows=sum(map(len,tables.values())),tables={ds:len(rows) for ds,rows in tables.items()},profiles=profiles),ensure_ascii=False))


if __name__=='__main__':main()
