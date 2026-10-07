"""Read-only preservation and exact source checks for the evidence join."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from app import first_piece_data, first_piece, finite_schedule, launch_data, process_quality
from app.models import Record, ImportBatch, MetricVersion
from app.schema import SCHEMAS
from app.metric_registry import calculation_hash


def main():
    before = json.loads((ROOT/'data/first-piece-before/manifest.json').read_text())
    records = list(Record.objects.order_by('dataset', 'business_key').values('dataset', 'business_key', 'record_hash'))
    assert len(records) == before['record_count'] == 230509
    assert finite_schedule.digest(records) == before['record_digest']
    assert SCHEMAS == before['schemas']
    for filename, digest in before['originals'].items():
        assert hashlib.sha256((ROOT/filename).read_bytes()).hexdigest() == digest, filename
    original = json.loads((ROOT/'data/first-piece-before/launch001.json').read_text())
    launch = launch_data.load('LR-261001-001')
    assert launch == original, 'Existing launch computation or source scope changed.'
    pq = process_quality.current(process_quality.filters({}))
    assert pq.summary(pq.selected()) == json.loads((ROOT/'data/first-piece-before/process_summary.json').read_text())
    d = first_piece_data.load()
    r = d['result']
    assert r['summary'] == dict(plans=288, ready=219, waiting=17, future=0, out=19, missing=12, metrology=13, attention=8, work_orders=32, measurements=529)
    assert sum(r['summary'][s] for s in first_piece.STATES) == len(r['rows'])
    for row in r['rows']:
        detail = r['details'][row['id']]
        if row['evidence_state'] == 'ready':
            assert row['latest_state'] == '齐项且范围内' and not row['issues']
            assert detail['measures'] and all(m['metrology']['ready'] for m in detail['measures'])
        for s in detail['sources']:
            assert Record.objects.filter(dataset=s['dataset'], business_key=s['key']).exists(), s
    for n in range(1, 11):
        target = first_piece_data.load(f'LR-261001-{n:03}')['targets']
        assert target['summary'] == dict(rows=66, missing=66, candidates=0, attention=0)
    assert calculation_hash('bi_order_lines') == MetricVersion.objects.get(pk=11).calculation_hash == '9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
    proof = dict(success=True, old_records_exact=len(records), schemas_preserved=len(SCHEMAS), original_files_preserved=len(before['originals']),
                 old_launch_exact=True, old_process_summary_exact=True, first_piece_summary=r['summary'], targets=660, missing_candidates=660,
                 new_business_facts=0, business_records_changed=False, approval_created=False, browser_acceptance=False)
    (ROOT/'data/first_piece_release.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
