"""Read-only verification against the preserved demo, including historical evidence."""
import os,sys,json,hashlib,sqlite3,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.db import connection
from django.contrib.auth.models import User
from app import topic_workspace as ws,topic_snapshots as ss,metric_registry
from app.models import TopicView,TopicSnapshot
connection.cursor().execute('PRAGMA query_only=ON')
before=json.loads((ROOT/'data/pivot_comparison_before.json').read_text());after={}
with sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True) as db:
 for (name,) in db.execute("select name from sqlite_master where type='table' order by name"):
  rows=db.execute('select * from "'+name+'" order by rowid').fetchall()
  after[name]={'rows':len(rows),'sha256':hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()}
changed=[name for name in after if before.get(name)!=after[name]]
assert set(changed)<= {'django_session'},changed
admin=User.objects.get(username='demo_admin');view=TopicView.objects.get(pk=4);ctx=ws.context(admin,view.topic_id)
assert not ws.view_info(view,ctx)['stale']
r=ws.run(admin,view.topic_id,{'context_token':ctx['context_token'],'config':view.config});c=r['cards'][0];comp=c['comparison'];assert not comp['blocked']
total=comp['matrix']['grand_total'];values={x['key']:x for x in total['values']}
assert (total['primary_rows'],total['reference_rows'])==(101,100)
assert math.isclose(values['d0']['delta'],61719702/1530/100-59940113/1485/100,abs_tol=1e-10)
assert values['d2']['delta_unit']=='百分点' and values['d2']['relative_pct'] is None
assert all(v['delta'] is None for cell in comp['matrix']['cells'] for v in cell['values'])
rows,_=ws.export_rows(admin,view.topic_id,{'context_token':ctx['context_token'],'facts_token':r['facts_token'],'config':view.config,'slot':0})
assert len(rows)==55 and all(len(row)==len(rows[0]) for row in rows)
snapshot_checks=[]
for snapshot in TopicSnapshot.objects.all():
 ss.verify(snapshot)
 if snapshot.topic_id==view.topic_id:
  previous=snapshot.payload_hash;check=ss.compare_current(admin,view.topic_id,snapshot.pk);assert not check['blocked']
  for card in check['cards']:
   assert not card['comparison']['blocked']
   assert all(v['delta'] in (None,0) for v in card['comparison']['matrix']['grand_total']['values'])
  snapshot.refresh_from_db();assert snapshot.payload_hash==previous;ss.verify(snapshot)
  snapshot_checks.append({'id':str(snapshot.pk),'sha256':previous,'current_comparison_zero_when_data_unchanged':True})
a=json.loads((ROOT/'data/accounts_runtime_probe.json').read_text());b=json.loads((ROOT/'data/pivot_comparison_runtime_probe.json').read_text())
assert a['models']==b['models'] and a['originals']==b['originals']
api_changes=[k for k in b['apis'] if a['apis'].get(k)!=b['apis'][k]]
assert api_changes==['/api/catalog'],api_changes
report={'scope':'Synthetic imported Excel only; read-only main database verification', 'tables_checked':len(after),'table_changes':changed,
        'business_facts_unchanged':after['app_record'],'models_and_originals_equal_to_previous_probe':True,'api_changes':api_changes,
        'published_calculation_hash':metric_registry.calculation_hash('bi_order_lines'),'saved_view_still_current':True,
        'primary_reference_rows':[101,100],'unit_cost_difference':values['d0'],'cost_share_difference':values['d2'],
        'export_data_rows':len(rows)-1,'historical_snapshots':snapshot_checks,'test_log':'data/pivot_comparison_full_tests.log'}
(ROOT/'data/pivot_comparison_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
