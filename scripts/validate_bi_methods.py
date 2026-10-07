"""Reconcile BI design additions with immutable facts and the previous catalog."""
import copy
import hashlib
import json
import math
import sqlite3
import statistics
import sys
import uuid
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from refine_bi_catalog import refine


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    before=ROOT/'data/bi-depth-before'
    old=json.loads((before/'data/bi_design.json').read_text())
    d=json.loads((ROOT/'data/bi_design.json').read_text())
    projected=copy.deepcopy(d)
    projected['framework'].pop('method_workshop')
    for dom in projected['domains']:
        for n in dom['items']:
            n.pop('analysis_methods');n.pop('analysis_method_note')
    for page in projected['page_blueprints']:
        page.pop('analysis_methods')
    assert projected==old, 'Only declared method-planning fields may change'
    assert refine(copy.deepcopy(d))==d, 'Catalog regeneration must be idempotent'
    ids={n['id'] for dom in d['domains'] for n in dom['items']}
    methods={m['id']:m for m in d['framework']['method_workshop']['methods']}
    assert len(ids)==382 and len(methods)==18
    page_methods={i for p in d['page_blueprints'] for i in p['analysis_methods']}
    assert page_methods==set(methods), 'All method proposals have a page example'
    items={n['id']:n for dom in d['domains'] for n in dom['items']}
    for n in items.values():
        assert n['analysis_methods'] and set(n['analysis_methods'])<=set(methods)
        assert len(n['analysis_methods'])==len(set(n['analysis_methods']))
    for m in methods.values():
        assert set(m['example_need_ids'])<=ids
        assert all(m['id'] in items[i]['analysis_methods'] for i in m['example_need_ids'])
    sample=json.loads((ROOT/'data/bi_method_readiness_sample.json').read_text())
    manifest=json.loads((before/'manifest.json').read_text())
    assert sha(ROOT/'data/platform.sqlite3')==manifest['database_sha256']==sample['database_sha256']
    for group in ('physical','protected'):
        for name,digest in manifest[group].items():
            assert sha(ROOT/name)==digest, name
    with sqlite3.connect((ROOT/'data/platform.sqlite3').as_uri()+'?mode=ro',uri=True) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        raw={}
        for ds,v in conn.execute('SELECT dataset,"values" FROM app_record WHERE dataset IN (?,?,?,?,?)',
                                 ('measurements','test_sessions','test_specs','units','products')):
            r=json.loads(v);raw.setdefault(ds,{})[r['id']]=r
        for source in sample['source_manifest']:
            actual=conn.execute('SELECT r.revision,r.record_hash,b.id,b.filename,b.file_hash,s.sheet,s.row_number FROM app_record r JOIN app_importrow s ON r.source_row_id=s.id JOIN app_importbatch b ON s.batch_id=b.id WHERE r.dataset=? AND r.business_key=?',
                                (source['dataset'],source['key'])).fetchone()
            expected=tuple(source[k] for k in ('revision','record_hash','batch_id','filename','file_hash','sheet','row'))
            expected=expected[:2]+(uuid.UUID(expected[2]).hex,)+expected[3:]
            assert actual==expected
    seen=set();values=[]
    for r in sample['observations']:
        assert r['id'] not in seen;seen.add(r['id'])
        m=raw['measurements'][r['id']];s=raw['test_sessions'][r['session_id']]
        u=raw['units'][r['unit_id']];sp=raw['test_specs'][r['spec_id']]
        assert not s['voided'] and s['tested']<=sample['business_cutoff']
        assert m['session_id']==s['id'] and s['unit_id']==u['id']
        assert u['product_id']==sp['product_id']==sample['product_id']
        assert sp['id']==sample['spec_id'] and s['spec_version']==sample['version']
        assert s['equipment_id']==sample['equipment_id'] and s['tested']==r['tested']
        assert m['unit']==r['unit']==sp['unit'] and m['value']==r['value']
        assert math.isfinite(m['value']);values.append(m['value'])
    # Independent calculation from source values, not chart statistics.
    assert len(values)==68 and len({r['unit_id'] for r in sample['observations']})==68
    assert math.isclose(statistics.mean(values),sample['stats']['mean'],abs_tol=1e-15)
    assert statistics.median(values)==sample['stats']['median']
    sp=raw['test_specs'][sample['spec_id']]
    outside=sum((sp['lsl'] is not None and v<sp['lsl']) or (sp['usl'] is not None and v>sp['usl']) for v in values)
    assert outside==sample['stats']['outside']==3
    times=Counter(r['tested'] for r in sample['observations'])
    ties=sum(n for n in times.values() if n>1)
    assert ties==sample['tied_observations']==29
    assert sum(n>1 for n in times.values())==len(sample['time_ties'])==12
    assert sample['cohort_units']==len(values)+sum(sample['excluded'].values())==100
    assert sample['control_limits'] is sample['cp'] is sample['cpk'] is None
    scene=d['framework']['method_workshop']['sample']
    assert scene['observations']==len(values) and scene['outside']==outside
    assert scene['mean']==sample['stats']['mean'] and scene['median']==sample['stats']['median']
    assert scene['lsl']==sp['lsl'] and scene['usl']==sp['usl']
    assert scene['tied_observations']==ties and scene['tied_timestamps']==12
    text=(ROOT/'outputs/BI分析方法与页面预演_20261007.txt').read_text()
    assert all(n['id']+' '+n['need'] in text for n in items.values())
    assert all(p['id']+' '+p['name'] in text for p in d['page_blueprints'])
    assert all(m['id']+' '+m['name'] in text for m in methods.values())
    class Markup(HTMLParser):
        def __init__(self):super().__init__();self.ids=[];self.scripts=[];self.inside=False
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            if 'id' in attrs:self.ids.append(attrs['id'])
            if tag=='script':assert 'src' not in attrs;self.inside=True;self.scripts.append('')
        def handle_data(self,data):
            if self.inside:self.scripts[-1]+=data
        def handle_endtag(self,tag):
            if tag=='script':self.inside=False
    markup=Markup();markup.feed((ROOT/'outputs/BI需求与呈现方案.html').read_text())
    assert len(markup.ids)==len(set(markup.ids))
    assert 'offline-method-workshop' in markup.ids
    syntax=ROOT/'data/bi-method-generated-syntax';syntax.mkdir(exist_ok=True)
    for i,source in enumerate(markup.scripts):(syntax/f'script-{i}.js').write_text(source)
    result=dict(success=True,method_contracts=18,requirements_with_candidate_methods=382,
                page_method_previews=17,old_catalog_fields_preserved=True,regeneration_idempotent=True,
                original_metrics_and_coverage_preserved=True,main_database_byte_exact=True,
                main_database_sha256=sample['database_sha256'],physical_files_preserved=len(manifest['physical']),
                protected_modules_preserved=len(manifest['protected']),source_observations_reconciled=68,
                excel_source_rows_reconciled=len(sample['source_manifest']),
                independently_recomputed_mean_median_and_spec_exceedances=True,
                timestamp_ties_reconciled=29,control_and_capability_values_paused=True,
                browser_and_mobile_acceptance=False,no_real_u8_mes_connection=True)
    (ROOT/'data/bi_method_design_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
