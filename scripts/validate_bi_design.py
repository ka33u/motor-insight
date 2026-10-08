import argparse,json,sys,copy,hashlib
parser=argparse.ArgumentParser(description="Validate the current catalog and offline artifacts; local historical checkpoints are version-specific.")
parser.add_argument("--current-only",action="store_true",help="Check current public artifacts without replaying older local recovery checkpoints.")
args=parser.parse_args()
from pathlib import Path
from collections import Counter
from html.parser import HTMLParser
root=Path.cwd();sys.path.insert(0,str(root/'scripts'))
from refine_bi_catalog import refine
p=root/'data/bi_design.json';d=json.loads(p.read_text())
items=[x for dom in d['domains'] for x in dom['items']]
assert (len(d['domains']),len(items),len(d['metrics']),len(d['page_blueprints']))==(26,382,63,17)
assert len({x['id'] for x in items})==len(items)
assert len({x['need'] for x in items})==len(items)
assert refine(copy.deepcopy(d))==d
assert len(d['coverage_groups'])==8
assert Counter(c for g in d['coverage_groups'] for c in g['domains'])==Counter(x['code'] for x in d['domains'])
assert len(d['framework']['definition_contract'])==12
assert len(d['framework']['display_channels'])==8
assert d['planning_summary']['requirements']==len(items)
pageids={x['id'] for x in d['page_blueprints']};domainids={x['code'] for x in d['domains']};metricids={x['id'] for x in d['metrics']}
needids={x['id'] for x in items}
assert len(d['framework']['bi_layers'])==6
assert len(d['framework']['decision_playbooks'])==6
assert d['planning_summary']['new_v5']==27
assert d['planning_summary']['new_v6']==16
assert len(d['framework']['presentation_choices'])==8
assert d['version']==9
assert d['planning_summary']['new_v9']==43
assert d['planning_summary']['decision_specs']==len(items)
assert len(d['framework']['definition_objects_v9'])==6
assert len(d['framework']['presentation_plan_v9'])==9
assert len(d['framework']['metric_definition_v9'])==10
assert len(d['framework']['page_pattern_v9'])==7
assert len(d['framework']['config_contract_v9'])==8
assert len(d['framework']['conditional_review_v9'])==6
assert len(d['framework']['mvp_decisions_v9'])==4
execution=d['framework']['execution_design']
packages={x['id']:x for x in execution['packages']}
assert set(packages)=={'B0','B1','B2','B3','B4'}
mapped=[nid for x in packages.values() for nid in x['need_ids']]
assert Counter(mapped)==Counter(needids)
assert all(x['candidate_count']==len(x['need_ids']) for x in packages.values())
for dom in d['domains']:
 session=dom['decision_session']
 assert session['need_ids']==[n['id'] for n in dom['items']]
 assert all(session[k] for k in ['question','cadence','content','start','blindspot','review_owner'])
 for n in dom['items']:
  proposal=n['delivery_proposal'];package=packages[proposal['package_id']]
  assert n['id'] in package['need_ids'] and proposal['package_name']==package['name']
  assert proposal['evidence_to_verify']==n['prerequisite']
  assert proposal['scope_to_verify']==n['applicability']
  assert proposal['acceptance_task']==n['acceptance']
  if n['priority']=='按条件启用':assert proposal['package_id']=='B3'
  if n['priority']=='条件成熟后':assert proposal['package_id']=='B4'
for page in d['page_blueprints']:
 focus=page['content_focus']
 assert 1<=len(focus['result_metric_ids'])<=3
 assert set(focus['result_metric_ids']+focus['driver_metric_ids']+focus['guardrail_metric_ids'])<=metricids
 assert all(focus[k] for k in ['mode','reading_path','boundary','empty_state','status_note'])
assert len(d['framework']['model_library'])==14
assert len(d['framework']['chart_selection'])==14
assert len(d['framework']['configurable_objects'])==7
assert len(d['framework']['completeness_axes'])==8
assert len(d['framework']['presentation_states'])==15
assert len({x['id'] for x in d['framework']['presentation_states']})==15
assert len(d['framework']['component_contracts'])==16
assert len(d['framework']['number_display_rules'])==12
assert len(d['framework']['filter_library'])==15
assert len(d['framework']['page_definition_fields'])==10
assert len(d['framework']['factory_dimension_library'])==8
filters={x['id'] for x in d['framework']['filter_library']}
for dom in d['domains']:
 assert dom['presentation_design']['content_count']==len(dom['items'])
 assert dom['presentation_design']['dimensions']
 for n in dom['items']:
  assert n['display_design']['dimensions']
  assert n['display_design']['visual']==n['view']
  assert n['display_design']['object_and_evidence'].endswith(n['action'])
  assert n['display_design']['scope_note']
for page in d['page_blueprints']:
 spec=page['display_spec']
 assert set(spec['filters'])<=filters
 assert spec['metric_ids']==page['metrics']
 assert spec['requirement_ids']==[n['id'] for dom in d['domains'] for n in dom['items'] if page['id'] in n['page_ids']]
 assert len(spec['detail_columns'])==5
 assert all(spec[k] for k in ['time_semantics','default_sort','mobile','privacy','filter_rule','interaction'])
for m in d['framework']['model_library']:
 assert m['example_need_id'] in needids
 assert set(m['metric_ids'])<=metricids
 assert set(m['domains'])<=domainids
 assert all(m.get(k) for k in ['id','name','question','grain','visual','drill','guardrail','collection_gate','status'])
assert {x['code'] for x in d['framework']['domain_data_contracts']}==domainids
for spec in d['framework']['domain_data_contracts']:
 assert all(spec.get(k) for k in ['key','fields','clock','approach','source_status','acceptance'])
for spec in d['framework']['presentation_choices']:
 assert set(spec['pages'])<=pageids
 assert all(spec.get(k) for k in ['id','name','reader','question','density','cards','visual','detail','action','avoid','mobile'])
for b in d['framework']['decision_playbooks']:
 assert set(b['needs'])<=needids and set(b['pages'])<=pageids,b['id']
 assert len(b['columns'])==len(b['example']) and len(b['cards'])==4,b['id']
 assert all(b.get(k) for k in ['owner','question','source','definition','gate','path','action']),b['id']
for x in items:
 assert all(x.get(k) for k in ['definition','view','action','owner','source','grain','priority','prerequisite','applicability','acceptance','gap','implementation','page_ids']),x['id']
 assert set(x['page_ids'])<=pageids
 assert x['decision_spec']['object_grain']==x['grain']
 assert x['decision_spec']['implementation']==x['implementation']
 assert x['decision_spec']['action']==x['action']
 assert all(x['decision_spec'].values())
for x in d['page_blueprints']:
 assert set(x['domains'])<=domainids and set(x['metrics'])<=metricids
 assert all(x.get(k) for k in ['question','reader','cards','visual','detail','drill','decision','gate','status'])
for x in d['metrics']:
 assert all(x.get(k) for k in ['formula','grain','clock','source','owner','refresh','pitfalls','implementation']),x['id']
class Inspect(HTMLParser):
 def __init__(self):super().__init__();self.ids=[];self.refs=[];self.assets=[];self.classes=Counter();self.script=[];self.in_script=False
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if 'id' in a:self.ids.append(a['id'])
  if a.get('href','').startswith('#'):self.refs.append(a['href'][1:])
  if tag in ('script','img','link') and ('src' in a or 'href' in a):self.assets.append(a.get('src',a.get('href')))
  self.classes.update(a.get('class','').split())
  if tag=='script':self.in_script=True
 def handle_endtag(self,tag):
  if tag=='script':self.in_script=False
 def handle_data(self,data):
  if self.in_script:self.script.append(data)
html=(root/'outputs/BI需求与呈现方案.html').read_text();v=Inspect();v.feed(html)
assert len(v.ids)==len(set(v.ids)),[x for x,n in Counter(v.ids).items() if n>1]
assert not(set(v.refs)-set(v.ids)),set(v.refs)-set(v.ids)
assert not v.assets,v.assets
assert v.classes['need']==len(items) and v.classes['metric']==len(d['metrics']) and v.classes['blueprint']==len(d['page_blueprints'])
Path('/tmp/bi-offline-inline.js').write_text('\n'.join(v.script))
plain=(root/f'outputs/BI完整{len(items)}项需求清单.txt').read_text()
concept=(root/f'outputs/BI定义与呈现构思_v{d["version"]}.txt').read_text()
supplement=(root/'outputs/BI建设分层与页面内容_实施补充.txt').read_text()
for package_entry in execution['packages']:
 assert package_entry['id']+' '+package_entry['name'] in supplement
 assert package_entry['gate'] in supplement
for dom in d['domains']:
 for key in ['question','cadence','content','start','blindspot']:
  assert dom['decision_session'][key] in supplement
for page in d['page_blueprints']:
 for key in ['reading_path','boundary','empty_state']:
  assert page['content_focus'][key] in supplement
for n in items:
 assert n['id']+' '+n['need']+'｜'+n['delivery_proposal']['package_id'] in supplement
 assert '建议建设包：'+n['delivery_proposal']['package_id']+' '+n['delivery_proposal']['package_name'] in plain
for key in ['definition_objects_v9','metric_definition_v9','presentation_plan_v9','page_pattern_v9','config_contract_v9','conditional_review_v9','mvp_decisions_v9']:
 for row in d['framework'][key]:
  assert '｜'.join(row) in plain,(key,row[0])
  assert '｜'.join(row) in concept,(key,row[0])
for m in d['framework']['model_library']:
 for key in ['name','question','grain','visual','drill','guardrail']:
  assert m[key] in plain,(m['id'],key)
for row in d['framework']['chart_selection']:
 assert '｜'.join(row) in plain
for s in d['framework']['presentation_states']:
 for key in ['name','label','render','boundary']:assert s[key] in plain
for row in d['framework']['component_contracts']+d['framework']['number_display_rules']+d['framework']['page_definition_fields']+d['framework']['factory_dimension_library']:
 assert '｜'.join(row) in plain
for x in items:
 assert x['id']+' · '+x['need'] in plain
 for key in ['definition','owner','view','source','grain','action','applicability','prerequisite','gap','acceptance']:
  assert x[key] in plain,(x['id'],key)
 assert ' / '.join(x['display_design']['dimensions']) in plain,x['id']
for x in d['metrics']:
 assert x['id']+' · '+x['name'] in plain
 for key in ['formula','grain','clock','source','pitfalls','implementation']:
  assert x[key] in plain,(x['id'],key)
for x in d['page_blueprints']:
 assert x['id']+' · '+x['name'] in plain
 for key in ['question','reader','visual','detail','drill','decision','gate','status']:
  assert x[key] in plain,(x['id'],key)
 for key in ['time_semantics','default_sort','mobile','filter_rule','privacy']:
  assert x['display_spec'][key] in plain,(x['id'],key)
evidence=dict(version=d['version'],domain_count=len(d['domains']),requirement_count=len(items),metric_count=len(d['metrics']),page_count=len(d['page_blueprints']),conditional_modules=len(d['framework']['conditional_modules']),implementation_counts=dict(Counter(x['implementation'] for x in items)),idempotent=True,broken_internal_links=[],external_assets=[],catalog_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),offline_sha256=hashlib.sha256(html.encode()).hexdigest(),scope='Validates design metadata and offline structure; implementation labels must be backed by separate feature tests and data evidence.')
evidence['plain_text_coverage']={'requirements':len(items),'metrics':len(d['metrics']),'pages':len(d['page_blueprints']),'sha256':hashlib.sha256(plain.encode()).hexdigest()}
evidence['execution_design']=d['planning_summary']['execution_design']
evidence['supplement_sha256']=hashlib.sha256(supplement.encode()).hexdigest()
baseline=root/'data/backups/bi-execution-before/manifest.json'
evidence['historical_checkpoint_check'] = 'explicitly_skipped_current_only' if args.current_only else 'available_local_checkpoint' if baseline.exists() else 'not_available'
if baseline.exists() and not args.current_only:
 before=json.loads(baseline.read_text());old=before['catalog']
 # Presentation additions have their own exact before-catalog/DB preservation
 # check. Strip only those named fields for the older implementation checkpoint.
 if d['framework'].get('presentation_design'):
  from validate_bi_presentation import validate,verify_prior_archive_increment
  evidence['presentation_design']=validate()
  comparison=copy.deepcopy(d)
  if 'method_workshop' in comparison['framework']:
   from refine_bi_methods import remove_exact_increment as remove_methods
   remove_methods(comparison)
  from refine_bi_topic_linkage import ROW as LINK_ROW,remove_exact_increment as remove_links
  if any(row[0]==LINK_ROW[0] for row in comparison['framework']['presentation']):remove_links(comparison)
  from refine_bi_device_transform import ROW as TRANSFORM_ROW,remove_exact_increment as remove_transform
  if any(row[0]==TRANSFORM_ROW[0] for row in comparison['framework']['presentation']):remove_transform(comparison)
  from refine_bi_device_collector import ROW as COLLECTOR_ROW,remove_exact_increment as remove_collector
  if any(row[0]==COLLECTOR_ROW[0] for row in comparison['framework']['presentation']):remove_collector(comparison)
  from refine_bi_device_intake import ROW as DEVICE_ROW,remove_exact_increment as remove_device
  if any(row[0]==DEVICE_ROW[0] for row in comparison['framework']['presentation']):remove_device(comparison)
  from refine_bi_field_catalog import ROW as FIELD_ROW,remove_exact_increment as remove_fields
  if any(row[0]==FIELD_ROW[0] for row in comparison['framework']['presentation']):remove_fields(comparison)
  from refine_bi_card_summary import ROW as SUMMARY_ROW,remove_exact_increment as remove_summary
  if any(row[0]==SUMMARY_ROW[0] for row in comparison['framework']['presentation']):remove_summary(comparison)
  from refine_bi_issue_workspace import ROW as ISSUE_ROW,remove_exact_increment as remove_issues
  if any(row[0]==ISSUE_ROW[0] for row in comparison['framework']['presentation']):remove_issues(comparison)
  from refine_bi_import_templates import ROW
  if any(row[0]==ROW[0] for row in comparison['framework']['presentation']):
   from refine_bi_import_templates import remove_exact_increment as remove_templates
   remove_templates(comparison)
  if any(s['href']=='#imports' for s in comparison['framework']['surfaces']):
   from refine_bi_import_mapping import remove_exact_increment as remove_mapping
   remove_mapping(comparison)
  if any(s['href']=='#metrology-evidence' for s in comparison['framework']['surfaces']):
   from refine_bi_metrology_evidence import remove_exact_increment
   remove_exact_increment(comparison)
  comparison['framework'].pop('presentation_design')
  comparison['planning_summary'].pop('presentation_design')
  for dom in comparison['domains']:
   for n in dom['items']:n.pop('presentation_contract')
  for page in comparison['page_blueprints']:page.pop('reading_contract')
 else:comparison=d
 metrology=root/'data/metrology_preservation.json'
 has_metrology=metrology.exists() and any(s['href']=='#metrology' for s in d['framework']['surfaces'])
 if has_metrology:
  from refine_bi_metrology import NEEDS,PAGES,STATUS
  metrology_proof=json.loads(metrology.read_text())
  assert metrology_proof['all_old_sql_rows_unchanged'] and metrology_proof['old_sql_tables']==40 and metrology_proof['new_register_rows']==44253
  assert metrology_proof['models_unchanged']==52 and metrology_proof['targets_unchanged']==33 and not metrology_proof['new_metric_publication']
  if metrology_proof['database_sha256']!=hashlib.sha256((root/'data/platform.sqlite3').read_bytes()).hexdigest():
   assert d['framework'].get('presentation_design'),'No matching source preservation checkpoint'
   evidence['prior_archive_increment']=verify_prior_archive_increment()
 assert d['metrics']==old['metrics']
 for current,previous in zip(comparison['domains'],old['domains']):
  assert {k:v for k,v in current.items() if k not in ('decision_session','items')}=={k:v for k,v in previous.items() if k!='items'}
  assert len(current['items'])==len(previous['items'])
  for current_need,previous_need in zip(current['items'],previous['items']):
   if has_metrology and current_need['id'] in NEEDS:
    assert current_need['implementation']=='模拟部分覆盖'
    assert current_need['gap']==previous_need['gap']+'\n计量登记：'+STATUS
    assert {k:v for k,v in current_need['decision_spec'].items() if k!='implementation'}=={k:v for k,v in previous_need['decision_spec'].items() if k!='implementation'}
    ignored={'delivery_proposal','gap','implementation','decision_spec'}
    assert {k:v for k,v in current_need.items() if k not in ignored}=={k:v for k,v in previous_need.items() if k not in ignored},current_need['id']
   else:assert {k:v for k,v in current_need.items() if k!='delivery_proposal'}==previous_need,current_need['id']
 for current,previous in zip(comparison['page_blueprints'],old['page_blueprints']):
  if has_metrology and current['id'] in PAGES:
   assert current['status']==previous['status']+' 计量登记：'+STATUS
   assert {k:v for k,v in current.items() if k not in ['content_focus','status']}=={k:v for k,v in previous.items() if k!='status'},current['id']
  else:assert {k:v for k,v in current.items() if k!='content_focus'}==previous,current['id']
 if not has_metrology:assert hashlib.sha256((root/'data/platform.sqlite3').read_bytes()).hexdigest()==before['database_sha256']
 protected={name:sha for name,sha in before['files'].items() if name.startswith('app/')}
 for name,sha in protected.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==sha,name
 evidence['preservation']={'original_requirements':382,'original_metric_definitions':63,'original_page_fields':17,'original_domain_fields':26,'database_unchanged':not has_metrology,'calculation_files_unchanged':list(protected)}
 if has_metrology:evidence['preservation']['authorized_increment']={'need_coverage_updates':sorted(NEEDS),'page_status_updates':sorted(PAGES),'new_synthetic_register_rows':44253,'all_old_sql_rows_unchanged':True,'evidence':'data/metrology_preservation.json'}
(root/f'data/bi_v{d["version"]}_validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
print(json.dumps(evidence,ensure_ascii=False,indent=2))
