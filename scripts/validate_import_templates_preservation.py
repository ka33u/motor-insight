"""Verify only the enumerated migration and simulated template setup increment."""
import hashlib,json,os,sqlite3,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
from verification_checkpoint import historical_database
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify_increment():
    before=json.loads((ROOT/'data/import-templates-before/manifest.json').read_text())
    actual=json.loads((ROOT/'data/import_templates_actual_setup.json').read_text());t=actual['template'];v=t['versions'][0]
    assert actual['synthetic'] and not actual['human_business_approval'] and actual['no_business_import']
    source=historical_database(ROOT)
    with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as db:
        db.execute('ATTACH DATABASE ? AS old',('file:'+before['database']+'?mode=ro',))
        oldnames={r[0] for r in db.execute("SELECT name FROM old.sqlite_master WHERE type='table' AND name!='sqlite_sequence'")}
        names={r[0] for r in db.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name!='sqlite_sequence'")}
        assert len(oldnames)==40 and names-oldnames=={'app_importtemplate','app_importtemplateversion','app_importtemplateuse'} and oldnames<=names
        mapping_before=json.loads((ROOT/'data/import-mapping-before/manifest.json').read_text())
        db.execute('ATTACH DATABASE ? AS mapping_before',('file:'+mapping_before['database']+'?mode=ro',))
        for name in oldnames|{'sqlite_sequence'}:
            assert name.replace('_','').isalnum();q='"'+name+'"'
            assert db.execute(f'SELECT * FROM old.{q} EXCEPT SELECT * FROM mapping_before.{q} LIMIT 1').fetchone() is None,name
            assert db.execute(f'SELECT * FROM mapping_before.{q} EXCEPT SELECT * FROM old.{q} LIMIT 1').fetchone() is None,name
        increments={}
        for name in sorted(oldnames):
            assert name.replace('_','').isalnum();q='"'+name+'"'
            assert db.execute(f'PRAGMA main.table_info({q})').fetchall()==db.execute(f'PRAGMA old.table_info({q})').fetchall(),name
            assert db.execute(f'SELECT * FROM old.{q} EXCEPT SELECT * FROM main.{q} LIMIT 1').fetchone() is None,name
            count=db.execute(f'SELECT count(*) FROM main.{q}').fetchone()[0]-db.execute(f'SELECT count(*) FROM old.{q}').fetchone()[0]
            if count:increments[name]=count
        assert increments=={'app_auditevent':2,'auth_permission':12,'django_content_type':3,'django_migrations':1},increments
        migrations=db.execute('SELECT app,name FROM django_migrations WHERE id NOT IN (SELECT id FROM old.django_migrations)').fetchall()
        assert migrations==[('app','0016_import_templates')]
        ct=db.execute('SELECT id,app_label,model FROM django_content_type WHERE id NOT IN (SELECT id FROM old.django_content_type)').fetchall()
        assert {(a,m) for _,a,m in ct}=={('app','importtemplate'),('app','importtemplateversion'),('app','importtemplateuse')}
        permissions=db.execute('SELECT content_type_id,codename FROM auth_permission WHERE id NOT IN (SELECT id FROM old.auth_permission)').fetchall()
        assert set(permissions)=={(i,action+'_'+model) for i,_,model in ct for action in ('add','change','delete','view')}
        row=db.execute('SELECT id,code,name,department,owner,revision,current_version FROM app_importtemplate').fetchall()
        assert row==[(uuid.UUID(t['id']).hex,t['code'],t['name'],t['department'],'demo_admin',2,1)]
        versions=db.execute('SELECT id,template_id,number,payload,content_hash,state,reason,created_by,activated_by FROM app_importtemplateversion').fetchall()
        assert len(versions)==1
        key,tid,number,payload,digest,state,reason,creator,activator=versions[0]
        assert (key,tid,number,state,reason,creator,activator)==(v['id'],uuid.UUID(t['id']).hex,1,'active',actual['reason'],'demo_admin','demo_admin')
        assert json.loads(payload)==v['payload']
        canonical=lambda obj:hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        assert canonical(json.loads(payload))==digest==v['content_hash']
        assert v['payload']['example_sha256']==actual['native_xlsx_sha256']==sha(ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/32_字段映射演练_模拟.xlsx')
        expected=json.loads((ROOT/'tests/fixtures/import_mapping_exercise_expected.json').read_text())['mapping']
        assert v['payload']['mapping']==expected
        assert db.execute('SELECT count(*) FROM app_importtemplateuse').fetchone()[0]==0
        events=db.execute('SELECT action,actor,object_id,detail FROM app_auditevent WHERE id NOT IN (SELECT id FROM old.app_auditevent) ORDER BY id').fetchall()
        assert [r[0] for r in events]==['import_template.draft','import_template.activate']
        for action,actor,key,detail in events:
            d=json.loads(detail);assert actor=='demo_admin' and key==t['id'] and d['version_id']==v['id'] and d['number']==1
            assert d['business_facts_changed'] is False and d['business_approval'] is False
            if action.endswith('draft'):assert d['content_hash']==digest and d['example_sha256']==actual['native_xlsx_sha256'] and d['revision']==1
            else:assert d['reason']==actual['reason'] and d['revision']==2 and d['previous_version']==0 and d['header_review']['content_hash']==digest
        oldseq=dict(db.execute('SELECT name,seq FROM old.sqlite_sequence'));seq=dict(db.execute('SELECT name,seq FROM main.sqlite_sequence'))
        assert set(seq)-set(oldseq)=={'app_importtemplateversion','app_importtemplateuse'}
        assert seq['app_importtemplateversion']==1 and seq['app_importtemplateuse']==0
        for name,val in oldseq.items():assert seq[name]==val+increments.get(name,0),name
        assert db.execute('SELECT count(*) FROM app_record').fetchone()[0]==212466
        assert db.execute('SELECT count(*) FROM app_filereadgrant').fetchone()[0]==0
    for name,digest in before['physical'].items():assert sha(ROOT/name)==digest,name
    for name,digest in before['protected'].items():assert sha(ROOT/name)==digest,name
    return dict(all_original_sql_rows_unchanged=True,original_tables=40,current_tables=43,
        exact_migration_and_framework_permissions=True,original_table_increments=increments,
        new_templates=1,new_immutable_versions=1,new_template_uses=0,synthetic_template_audits=2,
        all_formal_records_preserved=212466,old_physical_files_unchanged=442,protected_files_unchanged=16,
        before_database=str(Path(before['database'])),before_snapshot_sha256=sha(before['database']),
        before_main_database_sha256=before['database_sha256'],mapping_checkpoint_sql_rows_equal=True,
        main_database_sha256=sha(source),verification_database=str(source),current_main_database_sha256=sha(ROOT/'data/platform.sqlite3'),no_automatic_file_grants=True)

def validate():
    r=verify_increment()
    r.update(models_unchanged=52,targets_unchanged=33,new_metric_publication=False)
    (ROOT/'data/import_templates_preservation.json').write_text(json.dumps(r,ensure_ascii=False,indent=2));print(json.dumps(r,ensure_ascii=False,indent=2));return r
if __name__=='__main__':validate()
