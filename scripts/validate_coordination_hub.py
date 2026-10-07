"""Current database preservation, independent follow-up counts and browser CSVs."""
import os,sys,json,sqlite3,zipfile,tempfile,hashlib,csv,io,copy
from pathlib import Path
from collections import Counter
from datetime import date
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from django.utils import timezone
from app.models import Record,IssueDisposition,ActionTask,AnalysisModel,MetricVersion,Topic,TopicView,TopicSnapshot,ImportBatch
from app import coordination_hub as hub,targets,analysis_engine,metric_registry
from app.coordination_hub_views import FIELDS
connection.cursor().execute('PRAGMA query_only=ON')
backup=ROOT/'data/backups/motor-backup-20261005-052715.zip'
result={'synthetic':True,'baseline':str(backup),'tables':{},'files_preserved':0}
with zipfile.ZipFile(backup) as z,tempfile.TemporaryDirectory() as tmp:
    prior=Path(tmp)/'before.sqlite3';prior.write_bytes(z.read('data/platform.sqlite3'))
    for f in json.loads(z.read('manifest.json'))['files']:
        if f['path'].startswith(('data/imports/','data/device_files/')):
            assert hashlib.sha256((ROOT/f['path']).read_bytes()).hexdigest()==f['sha256'];result['files_preserved']+=1
    with sqlite3.connect(prior) as old,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as now:
        names=lambda db:{r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names(old)==names(now)
        for table in sorted(names(old)-{'sqlite_sequence','django_session'}):
            before=old.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall();after=now.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
            if table=='app_auditevent':
                assert after[:len(before)]==before
                extra=after[len(before):];result['audit_additions']=dict(Counter(r[1] for r in extra))
                assert result['audit_additions']=={'coordination_hub.export':2},result['audit_additions']
            elif table=='auth_user':
                # The authenticated source-link probe updates only admin last_login.
                columns=[r[1] for r in now.execute('PRAGMA table_info(auth_user)')]
                login_column=columns.index('last_login');name_column=columns.index('username')
                assert len(before)==len(after)
                changes=[]
                for prior_user,current_user in zip(before,after):
                    changed=[i for i in range(len(columns)) if prior_user[i]!=current_user[i]]
                    if changed:
                        assert current_user[name_column]=='demo_admin' and changed==[login_column]
                        assert current_user[login_column]>prior_user[login_column]
                        changes.append({'username':current_user[name_column],'field':'last_login','before':prior_user[login_column],'after':current_user[login_column]})
                result['authentication_metadata_changes']=changes
            else:assert before==after,table
            result['tables'][table]={'before':len(before),'after':len(after),'prior_rows_unchanged':before==after[:len(before)]}
def normalize(x):return json.loads(json.dumps(x,ensure_ascii=False,default=str))
def projection(r):
    d=copy.deepcopy(r);d.pop('metric_receipt',None)
    for k in ['pivot','scatter']:
        if d.get(k):d[k].pop('revision',None)
    return normalize(d)
admin=User.objects.get(username='demo_admin');baseline=json.loads((ROOT/'data/assembly_plans_before.json').read_text())
for mid,expected in baseline['models'].items():
    m=AnalysisModel.objects.get(pk=mid);assert projection(analysis_engine.run_analysis(admin,m.dataset,m.definition))==projection(expected),mid
assert {r['id']:normalize(r) for r in targets.Targets(admin).rows.values()}=={r['id']:r for r in baseline['targets']}
result['existing_results_preserved']={'models':len(baseline['models']),'targets':len(baseline['targets'])}
metric=MetricVersion.objects.get(metric__key='DELIVERY_OTIF',version=8,status='published')
assert metric.calculation_hash==metric_registry.calculation_hash(metric.metric.dataset)=='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
result['published_metric_unchanged']={'version':8,'hash':metric.calculation_hash}
today=timezone.localdate();notes=list(IssueDisposition.objects.values());tasks=list(ActionTask.objects.values())
assert (len(notes),len(tasks))==(19,1)
terminals={'已核验','演练已核验','演练已核对','演练已核查','演练已复查'}
independent=[]
for r in notes:
    independent.append({'id':'note:'+str(r['id']),'prefix':r['key'].split(':')[0],'done':r['status'] in terminals,'due':r['due_date'],'key':r['key']})
for r in tasks:
    independent.append({'id':'task:'+str(r['id']),'prefix':'action-tasks','done':r['state']=='closed','due':r['due_date'],'key':str(r['id'])})
for r in independent:
    days=(today-r['due']).days if r['due'] else None
    r['bucket']='done' if r['done'] else 'no_due' if days is None else 'overdue' if days>0 else 'today' if days==0 else 'next7' if days>=-7 else 'later'
actual=hub.Hub(admin);counts=Counter(r['bucket'] for r in independent)
assert {r['id']:r['bucket'] for r in independent}=={r['id']:r['bucket'] for r in actual.rows}
assert all(r['source_state']=='present' for r in actual.rows)
result['independent_counts']={'as_of_date':today.isoformat(),'total':len(independent),'open':sum(not r['done'] for r in independent),**counts}
assert actual.board(hub.params({}),1)['summary']['open']==result['independent_counts']['open']
role_excludes={'admin':set(),'analyst':set(),'finance':{'workforce','target'},'operations':{'ar','ap','target'},'quality':{'ar','ap','target','workforce'},'viewer':{'ar','ap','target','workforce'}}
result['role_counts']={}
for role,exclude in role_excludes.items():
    user=User.objects.get(username='demo_'+role);d=hub.Hub(user)
    expected={r['id'] for r in independent if r['prefix'] not in exclude}
    assert set(d.objects)==expected,(role,set(d.objects)^expected)
    result['role_counts'][role]=len(expected)
    assert {x['id'] for x in d.board(hub.params({}),1)['domains']}=={r['domain'] for r in d.rows}
for r in actual.rows:
    d=actual.detail(r['id'],1);source=d['source'];assert source is not None
    record=Record.objects.get(dataset=source['dataset'],business_key=source['key']);assert source['values']==record.values
    assert source['row']==record.source_row.row_number and source['file']==record.source_row.batch.filename
    if r['type']=='note':assert d['history_total']==r['version'],r['key']
    else:assert d['history_total']==6
result['source_and_history_checks']=len(actual.rows)
result['browser_exports']={}
for name,filters in [('全部',{}),('逾期',{'bucket':'overdue'})]:
    path=ROOT/f'outputs/跨部门跟进_{name}.csv';rows=list(csv.reader(io.StringIO(path.read_text(encoding='utf-8-sig'))));selected=actual.selected(hub.params(filters))
    assert rows[3]==[label for _,label in FIELDS]+['期限分类','主体资料状态']
    text=lambda v:'' if v is None else str(v)
    assert rows[4:]==[[text(r.get(k)) for k,_ in FIELDS]+[hub.BUCKETS[r['bucket']],r['source_state']] for r in selected]
    assert {row[0] for row in rows[4:]}=={r['id'] for r in independent if name=='全部' or r['bucket']=='overdue'}
    result['browser_exports'][name]={'rows':len(selected),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
result['counts']={'records':Record.objects.count(),'datasets':Record.objects.values('dataset').distinct().count(),'workbooks':ImportBatch.objects.exclude(status='superseded').count(),'models':AnalysisModel.objects.count(),'topics':Topic.objects.count(),'views':TopicView.objects.count(),'snapshots':TopicSnapshot.objects.count()}
assert tuple(result['counts'].values())==(116867,79,22,52,21,6,4)
(ROOT/'data/coordination_hub_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in result.items() if k!='tables'},ensure_ascii=False))
