"""Full imported-source reconciliation; writable workflows run on a DB copy."""
import os,sys,json,hashlib,sqlite3,tempfile,uuid,csv,io
from pathlib import Path
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.conf import settings
from django.db import connection,connections
from django.test import RequestFactory
from django.contrib.auth.models import User
from app import topic_workspace as ws,topic_linkage as links,topic_linkage_views as lv,topic_snapshots as ss,bi_card_summary_views as sv
from app.models import Record,TopicView,TopicSnapshot,AuditEvent,AnalysisModel,MetricVersion

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def post(view,user,topic_id,p):
    req=RequestFactory().post('/',json.dumps(p),content_type='application/json');req.user=user;response=view(req,topic_id)
    assert response.status_code==200,response.content.decode();return json.loads(response.content)
def evaluate(user,topic_id,conf):return ws.run(user,topic_id,dict(context_token=ws.context(user,topic_id)['context_token'],config=conf))
def picked(user,topic_id,slot,group):
    result=evaluate(user,topic_id,dict(scope={},reference_scope={},primary_label='当前范围',reference_label='相同参照'))
    data=post(lv.select,user,topic_id,dict(context_token=result['context_token'],facts_token=result['facts_token'],config=result['config'],slot=slot,group=group,side='primary'))
    return evaluate(user,topic_id,data['config'])
def ids(user,result,slot,side):
    seen=[];page=1
    while True:
        p=dict(context_token=result['context_token'],facts_token=result['facts_token'],config=result['config'],slot=slot,side=side,group=None,page=page)
        evidence=ws.evidence(user,result['topic']['id'],p);seen.extend(r['values']['id'] for r in evidence['rows'])
        if page*30>=evidence['total']:break
        page+=1
    assert len(seen)==len(set(seen));return set(seen)

def main():
    main_db=ROOT/'data/platform.sqlite3';before=sha(main_db);assert before=='cc17088ff8da71770975a599da397faee8ae074f6efd85dc83a825f7ea0d4866'
    raw={}
    for ds,row in Record.objects.values_list('dataset','values'):raw.setdefault(ds,[]).append(row)
    admin=User.objects.get(username='demo_admin');report=dict(synthetic=True,main_database_sha256=before,business_rows=Record.objects.count(),source='Existing Excel-imported records; no new business facts')
    # Work-order identifiers are full codes; independently derive each population.
    wo=next(w['id'] for w in raw['work_orders'] if any(u['work_order_id']==w['id'] for u in raw['units']))
    production=picked(admin,3,3,wo);expected=[{u['id'] for u in raw['units'] if u['work_order_id']==wo},{o['id'] for o in raw['operations'] if o['work_order_id']==wo},{wo},{wo}]
    for slot,wanted in enumerate(expected):
        for side in ('primary','reference'):assert ids(admin,production,slot,side)==wanted,(slot,side)
    assert production['cards'][0]['scope_summary']['primary']['value']==len(expected[0])
    quantity=sum(w['planned_qty'] for w in raw['work_orders'] if w['id']==wo);c=production['cards'][2]['scope_summary']['primary'];assert c['numerator']==len(expected[0]) and c['denominator']==quantity
    report['work_order']=dict(id=wo,source_counts=[len(x) for x in expected],complete_pages_and_both_sides_match=True)
    workshop=raw['energy'][0]['workshop'];energy=picked(admin,11,0,workshop)
    assert ids(admin,energy,0,'primary')=={r['id'] for r in raw['energy'] if r['workshop']==workshop}
    assert ids(admin,energy,1,'primary')=={r['id'] for r in raw['ehs'] if r['workshop']==workshop}
    assert Decimal(str(energy['cards'][0]['scope_summary']['primary']['value']))==sum(Decimal(str(r['kwh'])) for r in raw['energy'] if r['workshop']==workshop)
    assert all(c['linkage']['mapped'][0]['field']=='workshop' for c in energy['cards'])
    report['workshop']=dict(value=workshop,counts=[c['primary']['matched'] for c in energy['cards']],raw_energy_sum_matches=True)
    product=next(w['product_id'] for w in raw['work_orders'] if w['id']==wo);scatter=picked(admin,20,0,product);wanted={w['id'] for w in raw['work_orders'] if w['product_id']==product}
    assert ids(admin,scatter,0,'primary')==wanted and len(scatter['cards'][0]['primary']['scatter']['points'])==1
    # Sum actual source cost rows and assembled SNs independently of semantic.rows.
    costs=sum(Decimal(str(c['amount_cents'])) for c in raw['costs'] if c['work_order_id'] in wanted and c['occurred']<=ws.analytics.DAY)
    units=sum(u['work_order_id'] in wanted and u['assembly_at']<=ws.analytics.AS_OF for u in raw['units']);point=scatter['cards'][0]['primary']['scatter']['points'][0]
    assert point['x']==units and abs(Decimal(str(point['y']))-costs/100/units)<Decimal('1e-9')
    report['configuration']=dict(value=product,work_orders=len(wanted),units=units,total_cost_cents=str(costs),scatter_independently_reconciled=True)
    # Existing published receipt can intersect configuration without replacing v8.
    conf=scatter['config'];published=evaluate(admin,15,conf);c=published['cards'][0];assert c['primary']['metric_receipt']['version']==8
    order_ids={r['id'] for r in raw['order_lines'] if r['product_id']==product};assert ids(admin,published,0,'primary')==order_ids
    report['published_metric']=dict(key='DELIVERY_OTIF',version=8,source_order_lines=len(order_ids),fixed_receipt_retained=True)
    # Exercise the other four declared identities on real imported source
    # populations, including master id -> foreign key. No new model is saved.
    other=[]
    for kind,master,target,field in [('unit','units','test_sessions','unit_id'),('equipment','equipment','operations','equipment_id'),('supplier','suppliers','purchase_lines','supplier_id'),('material','materials','inventory_movements','material_id')]:
        value=next(r[field] for r in raw[target] if r.get(field))
        assert any(r['id']==value for r in raw[master])
        for ds,dimension in ((master,'id'),(target,field)):
            model=dict(id=-1,name='只读原生字段关系核对',version=1,dataset=ds,definition=dict(dimension=dimension,metrics=[dict(agg='count')],chart='bar'))
            base=links.engine.run_analysis(admin,ds,model['definition'])
            choice=next(c for c in links.choices(admin,model,base,{},'primary') if c['group']==value);assert choice['kind']==kind
            selected,_=links.effective(admin,model,links.validate(dict(revision=links.REVISION,rules_hash=links.rules_hash(),selections=[dict(kind=kind,value=value)])))
            result=links.engine.run_analysis(admin,ds,selected['definition']);assert result['matched']==sum(r.get(dimension)==value for r in raw[ds])
            assert result['rows'][0]['m0']==result['matched']
        other.append(dict(kind=kind,value=value,master=master,target=target,direct_field=field,native_source_counts_match=True))
    report['other_four_identity_native_checks']=other
    roles=[]
    for user in User.objects.filter(username__startswith='demo_').order_by('username'):
        if user.username in ('demo_admin','demo_quality','demo_operations','demo_analyst','demo_finance','demo_viewer'):
            current=evaluate(user,3,production['config']);assert all(c['available'] for c in current['cards']);assert ids(user,current,0,'primary')==expected[0];roles.append(user.username)
    assert len(roles)==6;report['role_profiles']=roles
    # Main facts and definitions remain readonly. Native persistence and exports
    # are deliberately exercised on a consistent isolated backup.
    connections.close_all()
    with tempfile.TemporaryDirectory(prefix='topic-linkage-') as td:
        copy=Path(td)/'platform.sqlite3'
        with sqlite3.connect('file:'+str(main_db)+'?mode=ro',uri=True) as a,sqlite3.connect(copy) as b:a.backup(b)
        original=connection.settings_dict['NAME'];connection.settings_dict['NAME']=str(copy)
        try:
            admin=User.objects.get(username='demo_admin');result=evaluate(admin,3,production['config']);binding=ws.context(admin,3)['context_token'];n=Record.objects.count();audits=AuditEvent.objects.count();views=TopicView.objects.count();snaps=TopicSnapshot.objects.count()
            view=ws.save_view(admin,3,dict(name='模拟工单跨卡联动复盘',config=result['config'],context_token=binding));assert evaluate(admin,3,view['config'])['cards'][0]['primary']['matched']==len(expected[0])
            frozen=ss.create(admin,3,dict(request_id=str(uuid.uuid4()),context_token=binding,facts_token=result['facts_token'],summary_token=result['summary_token'],config=result['config'],name='模拟联动复盘结果',note='本次仅在隔离副本保存可复现的工单联动范围'))
            for slot,wanted in enumerate(expected):assert {r['id'] for r in frozen.payload['cohorts'][str(slot)]['primary']}==wanted
            assert not ss.compare_current(admin,3,frozen.id)['blocked'];rows=ss.export_rows(frozen);assert all(len(r)==len(rows[0]) for r in rows)
            for slot in range(4):
                exported,_=ws.export_rows(admin,3,dict(context_token=binding,facts_token=result['facts_token'],config=result['config'],slot=slot));assert all(len(r)==len(exported[0]) for r in exported)
            req=RequestFactory().get('/',dict(context_token=binding,facts_token=result['facts_token'],summary_token=result['summary_token'],config=json.dumps(result['config'])));req.user=admin;response=sv.export(req,3);assert response.status_code==200;csv_rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))));assert json.loads(csv_rows[2][1])==result['config']
            assert Record.objects.count()==n and TopicView.objects.count()==views+1 and TopicSnapshot.objects.count()==snaps+1 and AuditEvent.objects.count()==audits+3
            report['isolated_copy_workflow']=dict(saved_views=1,saved_snapshots=1,audits=3,all_card_csv_and_frozen_rows_same_scope=True,summary_csv_same_scope=True,native_save_reopen_and_current_compare=True,main_business_writes=False)
        finally:connections.close_all();connection.settings_dict['NAME']=original
    assert sha(main_db)==before;report['main_database_unchanged']=True;report.update(browser_rendered_verified=False,mobile_interaction_verified=False,actual_download_verified=False)
    (ROOT/'data/topic_linkage_runtime_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
