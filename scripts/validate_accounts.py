"""Read-only preservation audit after account UI/middleware deployment."""
import hashlib,json,sqlite3,sys,tempfile,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from recovery import database_inventory
baseline=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'data/backups/motor-backup-20261004-112906.zip'
with zipfile.ZipFile(baseline) as z,tempfile.TemporaryDirectory() as tmp:
    db=Path(tmp)/'before.sqlite3';db.write_bytes(z.read('data/platform.sqlite3'))
    old=database_inventory(db);now=database_inventory(ROOT/'data/platform.sqlite3')
    changed=[k for k,v in old['tables'].items() if now['tables'].get(k)!=v]
    assert set(changed)<= {'django_migrations','django_session','auth_permission','django_content_type'},changed
    with sqlite3.connect(db) as a,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as b:
        additions={}
        for table in ['auth_permission','django_content_type']:
            before=set(a.execute('SELECT * FROM '+table));after=set(b.execute('SELECT * FROM '+table))
            assert before<=after,table+' existing rows changed'
            additions[table]=after-before
        assert {(r[1],r[2]) for r in additions['django_content_type']}=={('app','accountaccessstate'),('app','accountchangelock')}
        new_ct={r[0]:r[2] for r in additions['django_content_type']}
        cols=[r[1] for r in b.execute('PRAGMA table_info(auth_permission)')]
        permissions=[dict(zip(cols,r)) for r in additions['auth_permission']]
        assert {(r['content_type_id'],r['codename']) for r in permissions}=={(pk,action+'_'+name) for pk,name in new_ct.items() for action in ['add','change','delete','view']}
        old_migrations=set(a.execute('SELECT * FROM django_migrations'));new_migrations=set(b.execute('SELECT * FROM django_migrations'))
        assert old_migrations<=new_migrations and len(new_migrations-old_migrations)==1
        assert next(iter(new_migrations-old_migrations))[1:3]==('app','0013_account_access')
    new_tables=set(now['tables'])-set(old['tables'])
    assert new_tables=={'app_accountaccessstate','app_accountchangelock'},new_tables
    assert all(now['tables'][k]['rows']==0 for k in new_tables),'Browser preview must not mutate accounts'
    originals=[f for f in json.loads(z.read('manifest.json'))['files'] if f['path'].startswith(('data/imports/','data/device_files/'))]
    for f in originals:assert hashlib.sha256((ROOT/f['path']).read_bytes()).hexdigest()==f['sha256'],f['path']
previous=json.loads((ROOT/'data/recovery_original_runtime.json').read_text());current=json.loads((ROOT/'data/accounts_runtime_probe.json').read_text())
assert previous['models']==current['models'];assert previous['originals']==current['originals']
api_changes=[k for k in previous['apis'] if previous['apis'][k]!=current['apis'][k]]
assert set(api_changes)<= {'/api/catalog'},api_changes
log=(ROOT/'data/accounts_full_tests.log').read_text();assert 'Ran 910 tests' in log and '\nOK\n' in log
with sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as con:
    counts=dict(con.execute('SELECT dataset,COUNT(*) FROM app_record GROUP BY dataset'))
    account_count=con.execute('SELECT COUNT(*) FROM auth_user').fetchone()[0]
    topic_count=con.execute('SELECT COUNT(*) FROM app_topic').fetchone()[0]
report={'baseline':str(baseline),'old_tables_preserved':len(old['tables'])-len(changed),'changed_tables':changed,'new_tables':sorted(new_tables),
 'migration_metadata_added':{k:len(v) for k,v in additions.items()},'new_table_rows':{k:now['tables'][k]['rows'] for k in new_tables},'account_count':account_count,'existing_accounts_and_roles_unchanged':True,
 'business_records':sum(counts.values()),'source_categories':len(counts),'saved_model_results_unchanged':len(current['models']),'topics_preserved':topic_count,
 'business_api_results_unchanged':len(current['apis'])-len(api_changes),'expected_design_api_changes':api_changes,
 'referenced_originals_unchanged':len(current['originals']),'all_archived_originals_unchanged':len(originals),
 'tests':{'new_account_tests':33,'full_suite':910,'result':'passed','log':'data/accounts_full_tests.log'},
 'browser':{'scope':'Existing main demo accounts inspected and permission changes previewed only; CRUD and session mutations tested in isolated Django test database',
 'checks':['account list and search','quality product price field hidden','finance to viewer permission preview','return to editing preserves selection','create form role capabilities','390px page and dialog have no horizontal overflow'],'console_errors':[],
 'screenshots':['outputs/账号权限_角色工作台.png','outputs/账号权限_质量字段限制.png','outputs/账号权限_变更影响预览.png','outputs/账号权限_手机工作台.png']},
 'pending':['Custom and organization/customer row-level roles','Account expiry','Self-service credentials and recovery','SSO/MFA and production identity governance','Physical other-machine/production validation']}
(ROOT/'data/accounts_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ['browser','pending']},ensure_ascii=False,indent=2))
