"""Compare this workflow increment with its pre-migration backup; read-only."""
import os,sys,json,hashlib,sqlite3,zipfile,tempfile
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app import action_tasks as tasks,metric_registry
from app.models import ActionTask,ActionTaskEvent,TopicSnapshot,Record
connection.cursor().execute('PRAGMA query_only=ON')
backup=ROOT/'data/backups/motor-backup-20261004-131607.zip'
report={'backup':str(backup),'scope':'Synthetic workflow exercise; imported business facts are read-only'}
def tables(db):return {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
def rows(db,name):return db.execute('select * from "'+name+'" order by rowid').fetchall()
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp)/'before.sqlite3'
 with zipfile.ZipFile(backup) as z:p.write_bytes(z.read('data/platform.sqlite3'))
 with sqlite3.connect(p) as old,sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as new:
  before,after=tables(old),tables(new)
  assert after-before=={'app_actiontask','app_actiontaskevent','app_actiontasklock'}
  special={'auth_user','django_session','django_migrations','django_content_type','auth_permission','app_auditevent','sqlite_sequence'}
  checked=[]
  for name in sorted(before-special):assert rows(old,name)==rows(new,name),name;checked.append(name)
  fields=[r[1] for r in old.execute('pragma table_info(auth_user)')];login=fields.index('last_login');exclude=lambda row:row[:login]+row[login+1:]
  assert [exclude(r) for r in rows(old,'auth_user')]==[exclude(r) for r in rows(new,'auth_user')]
  additions={}
  for name in ['django_migrations','django_content_type','auth_permission','app_auditevent']:
   a,b=rows(old,name),rows(new,name);assert b[:len(a)]==a,name;additions[name]=b[len(a):]
  assert len(additions['django_migrations'])==1 and additions['django_migrations'][0][2]=='0014_action_tasks'
  assert {x[2] for x in additions['django_content_type']}=={'actiontask','actiontaskevent','actiontasklock'}
  assert len(additions['auth_permission'])==12
  ctypes={x[0] for x in additions['django_content_type']}
  permission_fields=[x[1] for x in new.execute('pragma table_info(auth_permission)')]
  assert all(x[permission_fields.index('content_type_id')] in ctypes for x in additions['auth_permission'])
  actions=Counter(x[1] for x in additions['app_auditevent']);assert all(k.startswith('action_task.') or k=='auth.login' for k in actions)
  report.update(unchanged_tables=checked,accounts_unchanged_except_login=True,added_model_metadata=3,added_default_permission_definitions=12,assigned_permissions_unchanged=True,audit_additions=dict(actions))
t=ActionTask.objects.get(pk='d932e0ab-dc1e-4afd-9d22-2bb95d1e9384');admin=User.objects.get(username='demo_admin');d=tasks.detail(admin,t.pk)
assert t.state=='closed' and t.version==6 and t.cycle==1
history=list(t.events.order_by('sequence'));assert [e.action for e in history]==['create','confirm','assign','start','submit','close']
for previous,next_event in zip(history,history[1:]):assert previous.after==next_event.before
assert len({e.request_id for e in history})==6
assert t.assignee.username=='demo_quality' and t.reviewer.username=='demo_operations'
assert t.submission['submitted_by']!=history[-1].actor_id
for source in [t.source_snapshot,t.submission['origin'],*t.submission['evidence']]:
 assert source['receipt']==tasks.source(admin,source['dataset'],source['key'],t.classification)['receipt']
assert [e['key'] for e in t.submission['evidence']]==['TS260921-000023-01','TS260921-000023-02']
assert [e['values']['result'] for e in t.submission['evidence']]==['不合格','合格']
old=json.loads((ROOT/'data/pivot_comparison_runtime_probe.json').read_text());now=json.loads((ROOT/'data/action_task_runtime_probe.json').read_text())
assert old['models']==now['models'];assert old['originals']==now['originals']
changes=[k for k,v in now['apis'].items() if old['apis'].get(k)!=v];assert changes==['/api/catalog'],changes
report.update(task={'id':str(t.pk),'state':t.state,'version':t.version,'events':len(history),'source':t.business_key,'evidence_results':['不合格','合格'],'independent_reviewer':True},business_records=Record.objects.count(),models_and_originals_preserved=True,api_changes=changes,metric_calculation_hash=metric_registry.calculation_hash('bi_order_lines'),snapshots=[{'id':str(s.pk),'hash':s.payload_hash} for s in TopicSnapshot.objects.all()],tests='966 passed; data/action_task_full_tests.log')
(ROOT/'data/action_task_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
