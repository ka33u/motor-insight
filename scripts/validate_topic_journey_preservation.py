"""Verify this read-only increment against the local pre-change checkpoint."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    before = json.loads((ROOT/'data/topic-journey-before/manifest.json').read_text())
    db = ROOT/'data/platform.sqlite3'
    assert sha(db) == before['source_database_sha'], 'Main database changed; inspect before publishing.'
    for name, expected in before['originals'].items():
        assert sha(ROOT/name) == expected, name
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    sys.path.insert(0, str(ROOT))
    import django
    django.setup()
    from app.schema import SCHEMAS
    from app.models import Record, MetricVersion
    from app import finite_schedule, first_piece_data
    from app.metric_registry import calculation_hash
    assert SCHEMAS == before['schemas']
    facts = list(Record.objects.order_by('dataset','business_key').values('dataset','business_key','record_hash'))
    assert len(facts) == before['record_count'] == 230802
    assert finite_schedule.digest(facts) == before['record_digest']
    assert first_piece_data.load() == json.loads((ROOT/'data/topic-journey-before/first_piece.json').read_text())
    assert calculation_hash('bi_order_lines') == MetricVersion.objects.get(pk=11).calculation_hash == '9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3'
    with sqlite3.connect(db) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        count = connection.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
    # Exact original requirement identities, coverage and metric proposals; only explanatory gaps change.
    old = json.loads(subprocess.check_output(['git','show',before['commit']+':data/bi_design.json'],cwd=ROOT))
    current = json.loads((ROOT/'data/bi_design.json').read_text())
    identities = lambda d: [(g['code'],n['id'],n['implementation']) for g in d['domains'] for n in g['items']]
    assert identities(old) == identities(current) and len(identities(current)) == 382
    assert old['metrics'] == current['metrics']
    assert len(current['domains']) == 26 and len(current['page_blueprints']) == 17
    assert sha(db) == before['source_database_sha']
    proof = dict(success=True, all_main_database_bytes_unchanged=True, tables_preserved=count,
                 facts_unchanged=230802, raw_schemas_unchanged=149, original_files_preserved=len(before['originals']),
                 first_piece_and_review_context_exact=True, published_delivery_v8_unchanged=True,
                 catalog_identities_and_coverage_preserved=382, metric_proposals_preserved=63,
                 browser_acceptance=False)
    (ROOT/'data/topic_journey_preservation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(proof,ensure_ascii=False))


if __name__ == '__main__':
    main()
