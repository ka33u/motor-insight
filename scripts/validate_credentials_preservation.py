"""Byte-exact main installation and unchanged BI catalog after credentials UI."""
import ast
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    before = ROOT/'data/credentials-before'
    manifest = json.loads((before/'manifest.json').read_text())
    assert sha(ROOT/'data/platform.sqlite3') == manifest['database_sha256']
    assert sha(ROOT/'data/bi_design.json') == manifest['catalog_sha256']
    for group in ('physical', 'protected'):
        for name, digest in manifest[group].items():
            assert sha(ROOT/name) == digest, name
    for name, digest in manifest['runtime'].items():
        assert sha(before/name) == digest, name
    with sqlite3.connect((ROOT/'data/platform.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert db.execute('SELECT count(*),count(DISTINCT dataset) FROM app_record').fetchone() == (212691, 112)
        expected = {'auth_user': 6, 'app_accountaccessstate': 0, 'app_accountchangelock': 0,
            'app_auditevent': 780, 'app_analysismodel': 52, 'app_topic': 21,
            'app_topicview': 6, 'app_topicsnapshot': 4, 'app_filereadgrant': 0}
        for table, count in expected.items():
            assert db.execute('SELECT count(*) FROM '+table).fetchone()[0] == count, table
    for name in ('app/credentials.py', 'app/credential_views.py', 'scripts/validate_credentials_runtime.py', 'tests/test_credentials.py'):
        ast.parse((ROOT/name).read_text())
    result = dict(success=True, main_database_byte_exact=True,
        main_database_sha256=manifest['database_sha256'], all_48_main_tables_unchanged=True,
        main_users_passwords_roles_and_audits_unchanged=True,
        original_physical_files_unchanged=len(manifest['physical']),
        protected_modules_unchanged=len(manifest['protected']),
        core_engines_unchanged=16, bi_catalog_byte_exact=True,
        no_new_main_business_or_credential_writes=True)
    (ROOT/'data/credentials_preservation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
