"""Authoring intermediate for Excel only; never writes business records."""
import json,os,sys
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app import analytics,material_planning

def main():
    source='CP.00008.A'
    product=Record.objects.get(dataset='products',business_key=source).values
    base={ds:[r.values for r in Record.objects.filter(dataset=ds,values__product_id=source).order_by('business_key')] for ds in ('bom','routes','route_dependencies')}
    tables={ds:[] for ds in ('materials','products','bom','routes','route_dependencies','work_orders','inventory_opening','inventory_movements')}
    ids={}
    for index in (1,2):
        pid=f'CP.0900{index}.A';ids[index]={};tables['products'].append(dict(product,id=pid,drawing=f'DJ-0900{index}-A'))
        for old in sorted({r['material_id'] for r in base['bom']}):
            material=Record.objects.get(dataset='materials',business_key=old).values
            mid=old.rsplit('.',1)[0]+f'.9{index:03d}';ids[index][old]=mid
            tables['materials'].append(dict(material,id=mid,safety_qty=0))
            tables['inventory_opening'].append(dict(id=f'QC-260901-RT{index}-{mid}',material_id=mid,lot=f'RT2609-{index}-{mid}',location='YL-RT-'+str(index),as_of='2026-09-01',qty=1000,unit_cost_cents=material['unit_cost_cents'],status='可用'))
        for row in base['bom']:
            tables['bom'].append(dict(row,id=row['id'].replace('00008',f'0900{index}'),product_id=pid,material_id=ids[index][row['material_id']]))
        routes={r['id']:r['id'].replace('00008',f'0900{index}') for r in base['routes']}
        tables['routes'] += [dict(r,id=routes[r['id']],product_id=pid) for r in base['routes']]
        tables['route_dependencies'] += [dict(r,id=r['id'].replace('00008',f'0900{index}'),product_id=pid,from_route_id=routes[r['from_route_id']],to_route_id=routes[r['to_route_id']]) for r in base['route_dependencies']]
    mid=ids[1]['01.01.0002'];opening=next(r for r in tables['inventory_opening'] if r['material_id']==mid)
    tables['inventory_opening'].append(dict(opening,id='QC-260901-RT1-QC',location='DJ-RT-01',qty=0,status='待检'))
    for n in range(1,6):
        index=2 if n==5 else 1;work=f'MO-260928-R{n:03d}';mid=ids[index]['01.01.0002']
        tables['work_orders'].append(dict(id=work,product_id=f'CP.0900{index}.A',planned_qty=4,planned_start='2026-09-28',planned_end='2026-10-06',priority='普通',status='已下达',bom_version=product['bom_version'],route_version=product['route_version']))
        original=dict(id=f'CK-260928-R{n:03d}-01',material_id=mid,lot=f'RT2609-{index}-{mid}',location='YL-RT-'+str(index),occurred='2026-09-28T08:00:00',movement='生产领料',qty_signed=-(n*10 if n<5 else 10),work_order_id=work,reference=work)
        tables['inventory_movements'].append(original)
        quantities={1:[2,1.5],2:[20],3:[5],4:[4],5:[6,6]}[n]
        for j,qty in enumerate(quantities,1):
            tables['inventory_movements'].append(dict(original,id=f'TL-260930-R{n:03d}-{j:02d}',location='DJ-RT-01' if n==3 else original['location'],occurred=f'2026-10-02T09:0{j}:00' if n==4 else f'2026-09-30T09:0{j}:00',movement='生产退料',qty_signed=qty,reference=original['id']))
    bearing=ids[1]['02.01.0002'];work='MO-260928-R001'
    original=dict(id='CK-260928-R001-02',material_id=bearing,lot=f'RT2609-1-{bearing}',location='YL-RT-1',occurred='2026-09-28T08:05:00',movement='生产领料',qty_signed=-4,work_order_id=work,reference=work)
    tables['inventory_movements'] += [original,dict(original,id='TL-260930-R001-03',occurred='2026-09-30T09:03:00',movement='生产退料',qty_signed=1,reference=original['id'])]
    for ds,rows in tables.items():
        assert len({r['id'] for r in rows})==len(rows)
        existing=set(Record.objects.filter(dataset=ds,business_key__in=[r['id'] for r in rows]).values_list('business_key',flat=True))
        for row in rows:
            if row['id'] in existing:assert Record.objects.get(dataset=ds,business_key=row['id']).values==row
    all_data=deepcopy(analytics._tables(analytics.revision()))
    for ds,rows in tables.items():
        old={r['id'] for r in all_data.get(ds,[])};all_data.setdefault(ds,[]).extend(r for r in rows if r['id'] not in old)
    result=material_planning.MaterialPlanning(all_data,material_planning.filters({'q':'MO-260928-R','stock_policy':'all_usable'}))
    profiles=[]
    for work in tables['work_orders']:
        row=result.orders[work['id']];mid=ids[2 if work['id'].endswith('005') else 1]['01.01.0002'];item=next(x for x in row['items'] if x['material_id']==mid)
        profiles.append(dict(id=work['id'],state=row['state'],material_id=mid,**{k:material_planning.clean(item[k]) for k in ('gross_required','gross_issued_qty','returned_qty','issued_qty','remaining_required')}))
    assert [r['state'] for r in profiles]==['covered']*4+['attention'],profiles
    assert [r['issued_qty'] for r in profiles]==[6.5,0,25,40,None],profiles
    out=dict(synthetic=True,source_product=source,tables=tables,schemas={ds:SCHEMAS[ds] for ds in tables},profiles=profiles)
    (ROOT/'data/material_returns_scenario.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(rows=sum(map(len,tables.values())),tables={ds:len(rows) for ds,rows in tables.items()},profiles=profiles),ensure_ascii=False))

if __name__=='__main__':main()
