"""Validate additive design metadata, complete offline coverage and preservation."""
import copy
import hashlib
import json
import sys
import sqlite3
import uuid
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from refine_bi_catalog import refine
from refine_bi_presentation import REVISION, NOTICE


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_prior_archive_increment():
    """Bridge the older metrology receipt through its explicit original archive job.

    That job did not import its new certificate source tables. Require every old
    SQL row to remain, only the exact 259 files/audits to be added, and bytes to
    match the independent archive manifest. Never treat a new DB hash as enough.
    """
    if (ROOT/'data/metrology_evidence_actual_import.json').exists():
        from validate_metrology_evidence_preservation import verify_increment
        proof=verify_increment()
        saved=json.loads((ROOT/'data/metrology_evidence_preservation.json').read_text())
        assert saved['database_sha256']==proof['database_sha256']
        assert saved['models_unchanged']==52 and saved['targets_unchanged']==33
        assert saved['new_metric_publication'] is False
        return proof
    source=ROOT/'data/metrology-evidence-before/platform.sqlite3'
    manifest=json.loads((ROOT/'data/metrology-evidence-before/manifest.json').read_text())
    archives=json.loads((ROOT/'data/metrology_evidence_scenario_build.json').read_text())['archives']
    assert source.exists() and len(archives)==259
    db=sqlite3.connect('file:'+str(ROOT/'data/platform.sqlite3')+'?mode=ro',uri=True)
    try:
        db.execute('ATTACH DATABASE ? AS previous',('file:'+str(source)+'?mode=ro',))
        names=[r[0] for r in db.execute("SELECT name FROM previous.sqlite_master WHERE type='table' AND name!='sqlite_sequence'")]
        assert len(names)==40
        added={}
        for name in names:
            q='"'+name.replace('"','""')+'"'
            assert db.execute(f'SELECT * FROM previous.{q} EXCEPT SELECT * FROM main.{q} LIMIT 1').fetchone() is None,name
            count=db.execute(f'SELECT count(*) FROM main.{q}').fetchone()[0]-db.execute(f'SELECT count(*) FROM previous.{q}').fetchone()[0]
            if count:added[name]=count
        assert added=={'app_devicefile':259,'app_auditevent':259},added
        byid={uuid.UUID(x['id']).hex:x for x in archives}
        new=db.execute('SELECT id,filename,file_hash,owner_id FROM app_devicefile WHERE id NOT IN (SELECT id FROM previous.app_devicefile)').fetchall()
        assert {r[0] for r in new}==set(byid)
        for key,filename,digest,owner_id in new:
            expected=byid[key]
            assert filename==expected['filename'] and digest==expected['sha256']
            assert db.execute('SELECT username FROM auth_user WHERE id=?',(owner_id,)).fetchone()[0]==expected['owner']
            assert sha(ROOT/'data/device_files'/f'{uuid.UUID(key)}.bin')==digest
        events=db.execute('SELECT action,object_id,detail FROM app_auditevent WHERE id NOT IN (SELECT id FROM previous.app_auditevent)').fetchall()
        assert Counter(uuid.UUID(e[1]).hex for e in events)==Counter(byid.keys())
        for action,key,detail in events:
            expected=byid[uuid.UUID(key).hex];detail=json.loads(detail)
            assert action=='device_file.archive' and detail['business_facts_changed'] is False
            assert detail['sha256']==expected['sha256'] and detail['filename']==expected['filename']
        # Pre-existing physical files from the same before-archive snapshot.
        assert len(manifest['files'])==182
        for name,digest in manifest['files'].items():assert sha(ROOT/name)==digest,name
        for name,digest in manifest['protected'].items():assert sha(ROOT/name)==digest,name
        assert db.execute('SELECT count(*) FROM app_record').fetchone()[0]==manifest['records_before']==211942
        assert db.execute("SELECT count(*) FROM app_record WHERE dataset IN ('metrology_certificates','metrology_certificate_links')").fetchone()[0]==0
        return {'all_old_sql_rows_unchanged':True,'old_sql_tables':40,'new_originals':259,
                'new_archive_audits':259,'exact_archive_ids_verified':True,'new_original_bytes_verified':True,
                'old_physical_files_unchanged':182,'original_business_records_unchanged':211942,
                'certificate_source_rows_imported':False}
    finally:db.close()


def validate():
    before=json.loads((ROOT/'data/backups/bi-presentation-before/manifest.json').read_text())
    d=json.loads((ROOT/'data/bi_design.json').read_text())
    restored=copy.deepcopy(d)
    if 'method_workshop' in restored['framework']:
        from refine_bi_methods import remove_exact_increment as remove_methods
        remove_methods(restored)
    from refine_bi_topic_linkage import ROW as LINK_ROW,remove_exact_increment as remove_links
    if any(row[0]==LINK_ROW[0] for row in restored['framework']['presentation']):
        remove_links(restored)
        assert restored==json.loads((ROOT/'data/topic-linkage-before/manifest.json').read_text())['catalog']
        from validate_topic_linkage_preservation import verify
        verify()
    from refine_bi_device_transform import ROW as TRANSFORM_ROW,remove_exact_increment as remove_transform
    if any(row[0]==TRANSFORM_ROW[0] for row in restored['framework']['presentation']):
        remove_transform(restored)
        assert restored==json.loads((ROOT/'data/device-transform-before/manifest.json').read_text())['catalog']
        from validate_device_transform_preservation import verify_increment as verify_transform
        transform_proof=verify_transform()
    from refine_bi_device_collector import ROW as COLLECTOR_ROW,remove_exact_increment as remove_collector
    if any(row[0]==COLLECTOR_ROW[0] for row in restored['framework']['presentation']):
        remove_collector(restored)
        assert restored==json.loads((ROOT/'data/device-collector-before/manifest.json').read_text())['catalog']
        from validate_device_collector_preservation import verify_increment as verify_collector
        collector_proof=verify_collector()
    from refine_bi_device_intake import ROW as DEVICE_ROW,remove_exact_increment as remove_device
    has_device=any(row[0]==DEVICE_ROW[0] for row in d['framework']['presentation'])
    if has_device:
        remove_device(restored)
        assert restored==json.loads((ROOT/'data/device-intake-before/manifest.json').read_text())['catalog']
        from validate_device_intake_preservation import verify_increment as verify_device
        device_proof=verify_device()
        rehearsal=json.loads((ROOT/'data/device_intake_import_rehearsal.json').read_text())
        assert rehearsal['all_page_and_csv_keys_match'] and rehearsal['independent_current_scan_keys_match']
    from refine_bi_field_catalog import ROW as FIELD_ROW,remove_exact_increment as remove_fields
    has_fields=any(row[0]==FIELD_ROW[0] for row in d['framework']['presentation'])
    if has_fields:
        remove_fields(restored)
        assert restored==json.loads((ROOT/'data/field-catalog-before/manifest.json').read_text())['catalog']
        from validate_field_catalog_preservation import verify as verify_fields
        verify_fields()
        field_proof=json.loads((ROOT/'data/field_catalog_validation.json').read_text())
        assert field_proof['all_field_pages_and_csv_keys_match'] and field_proof['filtered_json_metadata_same_dataset']
        assert len(field_proof['field_role_profiles'])==6 and field_proof['original_group_results_unchanged']
    from refine_bi_card_summary import ROW as SUMMARY_ROW,remove_exact_increment as remove_summary
    has_summary=any(row[0]==SUMMARY_ROW[0] for row in d['framework']['presentation'])
    if has_summary:
        remove_summary(restored)
        assert restored==json.loads((ROOT/'data/card-summary-before/manifest.json').read_text())['catalog']
        from validate_card_summary_preservation import verify as verify_summary
        verify_summary()
        summary_proof=json.loads((ROOT/'data/card_summary_validation.json').read_text())
        assert summary_proof['models_checked']==52 and summary_proof['topics_checked']==21
        assert summary_proof['original_group_results_unchanged'] and summary_proof['published_snapshot_capture_and_idempotency']
    from refine_bi_issue_workspace import ROW as ISSUE_ROW,remove_exact_increment as remove_issues
    has_issues=any(row[0]==ISSUE_ROW[0] for row in d['framework']['presentation'])
    if has_issues:
        remove_issues(restored)
        assert restored==json.loads((ROOT/'data/issue-workspace-before/manifest.json').read_text())['catalog']
        from validate_issue_workspace_preservation import verify as verify_issues
        verify_issues()
        proof=json.loads((ROOT/'data/issue_workspace_validation.json').read_text())
        assert proof['all_pages_unique_and_complete'] and proof['full_scope_csv_matches_all_pages'] and proof['old_scope_export_rejected']
    from refine_bi_import_templates import ROW
    has_templates=any(row[0]==ROW[0] for row in d['framework']['presentation'])
    template_proof=None
    if has_templates:
        from refine_bi_import_templates import remove_exact_increment as remove_templates
        remove_templates(restored)
        assert restored==json.loads((ROOT/'data/import-templates-before/manifest.json').read_text())['catalog']
        from validate_import_templates_preservation import verify_increment as verify_templates
        template_proof=verify_templates()
        rehearsal=json.loads((ROOT/'data/import_templates_validation.json').read_text())
        assert rehearsal['two_immutable_versions'] and rehearsal['normal_full_stage_commit_replay']
    has_mapping=any(s['href']=='#imports' for s in d['framework']['surfaces'])
    if has_mapping:
        from refine_bi_import_mapping import remove_exact_increment as remove_mapping
        remove_mapping(restored)
        proof=json.loads((ROOT/'data/import_mapping_validation.json').read_text())
        expected_hash=template_proof['before_main_database_sha256'] if has_templates else sha(ROOT/'data/platform.sqlite3')
        assert proof['main_database_sha256']==expected_hash
        assert proof['all_main_sql_tables_unchanged']==40 and proof['all_formal_records_preserved']==212466
        assert proof['isolated_api_stage_commit_and_replay'] and proof['mapping_audit_is_header_review_only']
    if any(s['href']=='#metrology-evidence' for s in d['framework']['surfaces']):
        from refine_bi_metrology_evidence import remove_exact_increment
        remove_exact_increment(restored)
    restored['framework'].pop('presentation_design')
    restored['planning_summary'].pop('presentation_design')
    for dom in restored['domains']:
        for n in dom['items']:n.pop('presentation_contract')
    for p in restored['page_blueprints']:p.pop('reading_contract')
    assert restored==before['catalog'],'Only named presentation fields and enumerated certificate/mapping increments may change'
    assert refine(copy.deepcopy(d))==d,'Refinement must be idempotent'
    items=[n for dom in d['domains'] for n in dom['items']]
    assert (len(d['domains']),len(items),len(d['metrics']),len(d['page_blueprints']))==(26,382,63,17)
    ids={n['id'] for n in items};pageids={p['id'] for p in d['page_blueprints']};metricids={m['id'] for m in d['metrics']}
    f=d['framework']['presentation_design']
    assert f['revision']==REVISION and f['status']==NOTICE
    assert len(f['definition_objects'])==8 and len(f['formats'])==12 and len(f['journeys'])==12
    assert len({x['id'] for x in f['formats']})==12
    assert len({j['id'] for j in f['journeys']})==12
    from bi_reader_guide import build_reader_guide,reader_guide_text
    assert f['reading_guide']==build_reader_guide(d)
    guide=f['reading_guide']
    assert len(guide['first_questions'])==5 and len(guide['primary_metrics'])==3
    assert sum(x['count'] for x in guide['domain_index'])==382
    assert {x['code'] for x in guide['domain_index']}=={dom['code'] for dom in d['domains']}
    for q in guide['first_questions']:
        assert q['page_id'] in pageids and set(q['needs'])<=ids
    quick=(ROOT/'outputs/BI定义与呈现_快速阅读版.txt').read_text()
    assert quick==(ROOT/'docs/BI定义与呈现_快速阅读版.txt').read_text()=='\n'.join(reader_guide_text(d))+'\n'
    assert {x['code'] for x in f['domain_comparison']}=={dom['code'] for dom in d['domains']}
    for j in f['journeys']:
        assert set(j['need_ids'])<=ids and set(j['page_ids'])<=pageids
        assert j['status']==NOTICE
    for n in items:
        c=n['presentation_contract']
        assert c['revision']==REVISION and c['status']==NOTICE
        assert c['primary_visual']==n['view'] and c['object_grain']==n['grain']
        assert c['dimensions']==n['display_design']['dimensions']
        assert c['data_gate']==n['prerequisite'] and c['validation']==n['acceptance']
        assert c['evidence']==n['display_design']['object_and_evidence']
        assert n['action'] in c['action_boundary'] and all(c.values())
    for p in d['page_blueprints']:
        c=p['reading_contract']
        assert c['revision']==REVISION and c['status']==NOTICE
        assert c['result_metric_ids']==p['content_focus']['result_metric_ids']
        assert set(c['result_metric_ids'])<=metricids and 1<=len(c['result_metric_ids'])<=3
        assert len(c['zones'])==6 and len(c['visible_context'])==6
    summary=d['planning_summary']['presentation_design']
    assert summary['requirement_contracts']==382 and summary['page_reading_contracts']==17
    assert summary['coverage_counts']==dict(Counter(n['implementation'] for n in items))
    assert summary['coverage_counts']==({'模拟部分覆盖':111,'待建设':271} if has_device else {'模拟部分覆盖':110,'待建设':272} if has_issues else {'模拟部分覆盖':109,'待建设':273} if has_mapping else {'模拟部分覆盖':108,'待建设':274})
    plain=(ROOT/'outputs/BI完整382项需求清单.txt').read_text()
    companion=(ROOT/'outputs/BI展示内容与交互设计_完善版.txt').read_text()
    assert companion==(ROOT/'docs/BI展示内容与交互设计说明.txt').read_text()
    for n in items:
        assert n['id']+' · '+n['need'] in plain and n['id']+' '+n['need']+'｜' in companion
        for key in ['definition','owner','view','source','grain','action','prerequisite','gap','acceptance']:
            assert n[key] in plain,(n['id'],key)
        for key in ['question','compare_gate','context_binding','detail_contract','mobile_task','permissions','export_contract','action_boundary']:
            assert n['presentation_contract'][key] in plain,(n['id'],key)
        assert n['presentation_contract']['compare_gate'] in companion
    for p in d['page_blueprints']:
        for key in ['first_task','default_reading','exit_decision','empty_state']:
            assert p['reading_contract'][key] in companion,(p['id'],key)
    for m in d['metrics']:
        assert m['id']+' · '+m['name'] in plain
        for key in ['formula','grain','clock','source','pitfalls']:assert m[key] in plain,(m['id'],key)
    for x in f['formats']:assert x['content'] in companion and x['density'] in companion
    for j in f['journeys']:assert j['question'] in companion and j['path'] in companion

    class Inspect(HTMLParser):
        def __init__(self):super().__init__();self.ids=[];self.refs=[];self.assets=[];self.classes=Counter();self.scripts=[];self.in_script=False
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
            if self.in_script:self.scripts.append(data)
    for name,out in [('BI需求与呈现方案.html','bi-presentation-offline.js'),('BI一页概览.html','bi-presentation-overview.js')]:
        html=(ROOT/'outputs'/name).read_text();v=Inspect();v.feed(html)
        assert len(v.ids)==len(set(v.ids)),name
        assert not(set(v.refs)-set(v.ids)),name
        assert not v.assets,(name,v.assets)
        assert REVISION in html and 'renderBiPresentationDesign' in html
        if name=='BI需求与呈现方案.html':
            assert v.classes['need']==382 and v.classes['metric']==63 and v.classes['blueprint']==17
            embedded=html.split('const designCatalog=',1)[1].split(';\n',1)[0]
            assert json.loads(embedded)==d,'Portable document must embed the current catalog'
        Path('/tmp',out).write_text('\n'.join(v.scripts))
    database_unchanged=sha(ROOT/'data/platform.sqlite3')==before['database_sha256']
    increment=None
    if not database_unchanged:
        increment=verify_prior_archive_increment()
    protected={n:s for n,s in before['files'].items() if n.startswith('app/')}
    assert len(protected)==16
    for name,s in protected.items():assert sha(ROOT/name)==s,name
    report={
        'revision':REVISION,'domains':26,'requirements':382,'metrics':63,'pages':17,
        'new_presentation_contracts':382,'new_page_reading_contracts':17,'formats':12,'journeys':12,
        'original_catalog_fields_unchanged':increment is None and not has_mapping,'original_coverage_states_unchanged':not has_mapping and not has_issues,
        'enumerated_mapping_scope':{'need_coverage_updates':['W-12'],'page_status_updates':['P15'],'evidence':'data/import_mapping_validation.json'} if has_mapping else None,
        'enumerated_template_scope':template_proof,
        'enumerated_device_intake_scope':device_proof if has_device else None,
        'enumerated_field_scope':{'need_gap_updates':['W-04','X-09','X-28'],'page_status_updates':['P15'],'surface':'#field-catalog','coverage_states_changed':False,'evidence':'data/field_catalog_validation.json','preservation':'data/field_catalog_preservation.json'} if has_fields else None,
        'enumerated_summary_scope':{'need_gap_updates':['X-07','X-09','X-10'],'page_status_updates':['P15'],'source_scope':'existing_topics_only','coverage_states_changed':False,'evidence':'data/card_summary_validation.json','preservation':'data/card_summary_preservation.json'} if has_summary else None,
        'enumerated_overview_scope':{'need_coverage_updates':['A-02'],'gap_scope_updates':['A-02','X-09'],'page_status_updates':['P01'],'evidence':'data/issue_workspace_validation.json','preservation':'data/issue_workspace_preservation.json'} if has_issues else None,
        'original_metric_and_page_definitions_unchanged':True,
        'database_unchanged':database_unchanged,'database_sha256':sha(ROOT/'data/platform.sqlite3'),
        'design_does_not_write_business_database':True,'authorized_source_increment':increment,
        'original_catalog_fields_unchanged_except_enumerated_source_status':True,
        'reader_guide_sha256':sha(ROOT/'outputs/BI定义与呈现_快速阅读版.txt'),
        'protected_files_unchanged':list(protected),'idempotent':True,'complete_text_coverage':True,
        'offline_embedded_catalog_equal':True,'external_runtime_assets':[],
        'catalog_sha256':sha(ROOT/'data/bi_design.json'),
        'companion_sha256':sha(ROOT/'outputs/BI展示内容与交互设计_完善版.txt'),
        'browser_rendered_verified':False,'mobile_interaction_verified':False,'actual_download_verified':False,
    }
    (ROOT/'data/bi_presentation_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':validate()
