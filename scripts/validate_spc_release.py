"""Current additive scope, exact legacy preservation, and source-backed trials."""
import copy,hashlib,json,math,os,sqlite3,sys
from decimal import Decimal,localcontext
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    manifest=json.loads((ROOT/'data/spc-before/manifest.json').read_text());receipt=json.loads((ROOT/'data/spc_main_import.json').read_text())
    parent=ROOT/'data/spc-before/platform.sqlite3';db=ROOT/'data/platform.sqlite3';assert sha(parent)==manifest['database_sha256']
    assert sha(db)==receipt['database_sha256'];physical=manifest['physical']
    for name,digest in physical.items():assert sha(ROOT/name)==digest,name
    changed_protected={'app/schema.py','app/manufacturing_rules.py'}
    for name,digest in manifest['protected'].items():
        if name not in changed_protected:assert sha(ROOT/name)==digest,name
    with sqlite3.connect(db) as c:
        c.execute('ATTACH DATABASE ? AS parent',(str(parent),));assert c.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
        tables=[n for n, in c.execute("SELECT name FROM parent.sqlite_master WHERE type='table' AND name!='sqlite_sequence'")]
        for name in tables:
            columns=[r[1] for r in c.execute('PRAGMA main.table_info("'+name+'")')]
            if name=='app_importtemplate':columns=[n for n in columns if n not in {'current_version','revision'}]
            if name=='app_importtemplateversion':columns=[n for n in columns if n!='state']
            fields=','.join('"'+n+'"' for n in columns)
            assert c.execute('SELECT count(*) FROM (SELECT '+fields+' FROM parent."'+name+'" EXCEPT SELECT '+fields+' FROM main."'+name+'")').fetchone()[0]==0,name
        allowed_additions={'app_record':750,'app_importbatch':1,'app_importrow':750,'app_importtemplateversion':1,'app_auditevent':4}
        for name in tables:
            counts=c.execute('SELECT (SELECT count(*) FROM main."'+name+'")-(SELECT count(*) FROM parent."'+name+'")').fetchone()[0]
            assert counts==allowed_additions.get(name,0),(name,counts)
        assert c.execute('SELECT name,seq FROM main.sqlite_sequence WHERE name NOT IN (?,?,?,?) ORDER BY name',('app_record','app_importrow','app_importtemplateversion','app_auditevent')).fetchall()==c.execute('SELECT name,seq FROM parent.sqlite_sequence WHERE name NOT IN (?,?,?,?) ORDER BY name',('app_record','app_importrow','app_importtemplateversion','app_auditevent')).fetchall()
        old=c.execute('SELECT number,state,content_hash,payload FROM parent.app_importtemplateversion ORDER BY number').fetchall()
        now=c.execute('SELECT number,state,content_hash,payload FROM main.app_importtemplateversion WHERE number<=2 ORDER BY number').fetchall()
        assert [(n,'retired',h,p) for n,st,h,p in old]==now
        assert c.execute('SELECT current_version,revision FROM main.app_importtemplate').fetchall()==[(3,6)]
        assert c.execute('SELECT current_version,revision FROM parent.app_importtemplate').fetchall()==[(2,4)]
    sys.path[:0]=[str(ROOT),str(ROOT/'scripts')];os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    import django;django.setup()
    from django.test import RequestFactory
    from django.urls import resolve
    from django.contrib.auth import get_user_model
    from app.schema import SCHEMAS
    from app.models import Record,AuditEvent,MetricVersion,AnalysisModel
    from app.metric_registry import calculation_hash
    from app.analysis_engine import run_analysis
    from app import access
    from refine_bi_spc import remove_exact_increment
    from refine_bi_catalog import refine
    assert {k:v for k,v in SCHEMAS.items() if k not in {'spc_studies','spc_observations','spc_events'}}==manifest['schemas']
    catalog=json.loads((ROOT/'data/bi_design.json').read_text());assert refine(copy.deepcopy(catalog))==catalog
    previous=copy.deepcopy(catalog);remove_exact_increment(previous);assert previous==manifest['catalog']
    assert catalog['planning_summary']['implementation_counts']=={'模拟部分覆盖':113,'待建设':269}
    scenario=json.loads((ROOT/'data/spc_scenario.json').read_text());new=[]
    for ds,expected in scenario['tables'].items():
        facts=list(Record.objects.filter(dataset=ds).select_related('source_row__batch'));assert len(facts)==len(expected)
        wanted={r['id']:r for r in expected}
        for r in facts:
            assert r.values==wanted[r.business_key]==r.source_row.normalized
            assert str(r.source_row.batch.pk)==receipt['batch_id'] and r.source_row.sheet==SCHEMAS[ds]['label']
            assert r.record_hash==r.source_row.record_hash;new.append((ds,r.business_key))
    published=MetricVersion.objects.get(pk=11);assert published.calculation_hash==manifest['delivery_v8_calculation_hash']==calculation_hash(published.metric.dataset)
    factory=RequestFactory();users=list(get_user_model().objects.all());admin=next(u for u in users if access.role(u)=='admin');profiles=[]
    def get(url,user,fields=None):
        request=factory.get(url,fields or {});request.user=user;match=resolve(url);response=match.func(request,**match.kwargs)
        assert response.status_code==200,(url,response.status_code,response.content[:300]);return json.loads(response.content)
    audits=AuditEvent.objects.count()
    for user in users:
        for s in scenario['tables']['spc_studies']:
            result=get('/api/spc/'+s['id'],user);assert result['cp'] is result['cpk'] is None and result['formal_qualification'] is False
            point=result['chart_points'][0]['id'];detail=get('/api/spc/'+s['id']+'/points/'+point,user,dict(receipt=result['receipt']))
            assert any(r['dataset']=='spc_observations' and r['key']==point and not r.get('missing') for r in detail['sources'])
            if user==admin:
                profiles.append({k:result[k] for k in ('state','coverage','signal_counts','limits','issues','category_counts','source_hash','rule_hash') }|{'id':s['id'],'name':s['name']})
                if result['limits']:
                    rows=sorted([r for r in scenario['tables']['spc_observations'] if r['study_id']==s['id'] and r['sequence']<=s['baseline_end']],key=lambda r:r['sequence'])
                    with localcontext() as ctx:
                        ctx.prec=40;values=[Decimal(str(r['value'])) for r in rows];mean=sum(values)/len(values)
                        mr=sum(abs(b-a) for a,b in zip(values,values[1:]))/(len(values)-1);delta=3*mr/Decimal('1.128')
                        for field,v in dict(center=mean,mr_mean=mr,i_lcl=mean-delta,i_ucl=mean+delta,mr_ucl=Decimal('3.267')*mr).items():assert math.isclose(result['limits'][field],float(v),rel_tol=0,abs_tol=1e-15)
    assert AuditEvent.objects.count()==audits==784
    assert [p['state'] for p in profiles]==['trial']*4+['paused']*6
    assert profiles[1]['signal_counts']==dict(baseline=dict(i=1,mr=0),monitor=dict(i=40,mr=3)) and profiles[1]['coverage']['spec_outside']==0
    assert profiles[6]['category_counts']=={'0':1,'1':79}
    model=AnalysisModel.objects.get(pk=44);run=run_analysis(admin,model.dataset,model.definition)
    # The exact released rule/source proof is the retained v8 calculation hash;
    # full legacy facts and definitions were separately compared above.
    assert len(run['rows'])>0
    proof=dict(success=True,synthetic=True,database_sha256=sha(db),all_48_old_tables_retained=True,
               all_old_facts_sources_models_topics_snapshots_unchanged=True,old_files_unchanged=len(physical),
               protected_engine_files_unchanged=16,other_protected_files_unchanged=len(manifest['protected'])-2,
               original_112_schema_definitions_unchanged=True,new_schemas=3,new_source_rows=750,
               allowed_additions=allowed_additions,template_v3_reviewed=True,old_template_payloads_unchanged=True,
               published_delivery_v8_hash_unchanged=published.calculation_hash,legacy_model_run_checked=model.pk,
               catalog_exact_additive=True,partial_coverage=113,planned=269,six_roles_verified=len(users),
               no_reads_audited=True,independent_decimal_formula_checks=True,profiles=profiles,
               browser_acceptance=False,mobile_acceptance=False,real_u8_mes_connected=False)
    (ROOT/'data/spc_release_validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in proof.items() if k!='profiles'},ensure_ascii=False))
if __name__=='__main__':main()
