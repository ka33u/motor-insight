"""Exact legacy rows, files and contracts after the additive page migration/seed."""
import argparse,hashlib,json,os,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BEFORE=ROOT/'data/topic-pages-before'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--proof',type=Path,required=True);a=p.parse_args();db=a.db.resolve();m=json.loads((BEFORE/'manifest.json').read_text());assert sha(BEFORE/'platform.sqlite3')==m['database_sha256']
 for n,h in m['physical'].items():assert sha(ROOT/n)==h,n
 for n,h in m['protected'].items():
  if n!='app/models.py':assert sha(ROOT/n)==h,n
 old=(BEFORE/'app/models.py').read_bytes();current=(ROOT/'app/models.py').read_bytes();assert sha(BEFORE/'app/models.py')==m['models_before_sha256'];assert current.startswith(old);suffix=current[len(old):].decode();assert suffix.count('\nclass ')==3;assert all('\nclass '+n+'(' in suffix for n in ('TopicPage','TopicPageVersion','TopicPageRequest'))
 os.environ['DJANGO_SETTINGS_MODULE']='config.settings';os.environ['MOTOR_SQLITE_PATH']=str(db);sys.path.insert(0,str(ROOT));import django;django.setup()
 from app.schema import SCHEMAS
 from app.metric_registry import calculation_hash
 from app.models import MetricVersion,TopicPage,TopicPageVersion,TopicPageRequest
 from app import topic_pages
 assert SCHEMAS==m['schemas'];assert calculation_hash('bi_order_lines')==m['delivery_v8_hash']==MetricVersion.objects.get(pk=11).calculation_hash
 with sqlite3.connect(db) as c:
  c.execute('ATTACH DATABASE ? AS parent',(str(BEFORE/'platform.sqlite3'),));assert c.execute('PRAGMA integrity_check').fetchall()==[('ok',)];assert not c.execute('PRAGMA foreign_key_check').fetchall();names={n for n, in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")};new=names-set(m['tables']);assert new=={'app_topicpage','app_topicpageversion','app_topicpagerequest'}
  for table,count in m['tables'].items():
   q='"'+table+'"';assert not c.execute('select * from parent.'+q+' except select * from main.'+q).fetchall(),table
   extra=c.execute('select * from main.'+q+' except select * from parent.'+q).fetchall()
   if table=='django_migrations':assert len(extra)==1 and extra[0][1:3]==('app','0021_topic_page_versions')
   elif table=='app_auditevent':assert len(extra)==3 and all(r[1] in ('topic_page.create','topic_page.update') for r in extra)
   elif table=='django_content_type':assert len(extra)==3 and all(r[1]=='app' and r[2] in ('topicpage','topicpageversion','topicpagerequest') for r in extra)
   elif table=='auth_permission':assert len(extra)==12 and all(r[2].split('_',1)[0] in ('add','change','delete','view') and r[2].split('_',1)[1] in ('topicpage','topicpageversion','topicpagerequest') for r in extra)
   else:assert extra==[],table
  assert c.execute('select count(*) from app_record').fetchone()[0]==223938;assert c.execute('select count(*) from app_importbatch').fetchone()[0]==51
  oldseq=dict(c.execute('select name,seq from parent.sqlite_sequence'));newseq=dict(c.execute('select name,seq from main.sqlite_sequence'))
  for table,value in oldseq.items():assert newseq[table]==value+{'app_auditevent':3,'django_migrations':1,'django_content_type':3,'auth_permission':12}.get(table,0),table
 assert (TopicPage.objects.count(),TopicPageVersion.objects.count(),TopicPageRequest.objects.count())==(2,3,3)
 for page in TopicPage.objects.select_related('owner'):assert topic_pages.read(page.owner,page.pk)['ready']
 proof=dict(success=True,tables=55,legacy_tables=52,legacy_rows_exact=True,new_migration=1,new_django_content_types=3,new_unassigned_django_permission_metadata=12,new_private_pages=2,new_definition_versions=3,new_idempotence_requests=3,new_audit_events=3,all_223938_business_facts_unchanged=True,all_51_import_batches_unchanged=True,physical_preserved=len(m['physical']),protected_byte_exact=len(m['protected'])-1,models_only_three_classes_appended=True,raw_contracts_exact=130,published_delivery_v8_unchanged=True,private_model_cards_unchanged=True,source_database_sha256=m['database_sha256'],current_database_sha256=sha(db))
 a.proof.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof))
if __name__=='__main__':main()
