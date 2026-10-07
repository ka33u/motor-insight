#!/usr/bin/env python3
"""Trusted local demo recovery: stdlib bootstrap, offline dependencies, new targets only.

Hashes detect damage, not authenticity. Restore only bundles from a trusted source.
No shell, source-system writes, pip network access, or automatic service startup.
"""
import argparse
import base64
from contextlib import closing
from datetime import datetime, timezone
import email
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unicodedata
import uuid
import zipfile

FORMAT='motor-platform-recovery'
VERSION=1
PYTHON=(3,12)
CHUNK=1024*1024
MAX_FILES=10000
MAX_BYTES=4*1024**3
MAX_MANIFEST=4*1024**2
ROOT=Path(__file__).resolve().parents[1]
RUNTIME_DIRS=('app','config','static','templates','scripts','tests','docs')
REQUIRED={'manage.py','config/settings.py','config/urls.py','app/views.py','app/schema.py',
          'templates/index.html','static/app.js','static/app.css','scripts/serve.py','scripts/recovery.py',
          'README.md','requirements.txt','requirements.lock','data/platform.sqlite3','data/bi_design.json',
          'outputs/BI需求与呈现方案.html'}
EXPECTED_PACKAGES={'django','asgiref','sqlparse','openpyxl','et-xmlfile'}

COLLECTOR_FIXTURES={'data/device_inbox/'+name for name in (
 'fixture_manifest.json','DS-PC-2026-001/首测.csv','DS-PC-2026-001/首测_copy.csv',
 'DS-PC-2026-001/复测.csv','DS-PC-2026-001/线索错位.csv','DS-PC-2026-001/设备交接说明.txt',
 'DS-PC-2026-001/临时.csv.part','DS-PC-2026-001/过大.csv','DS-PC-2026-002/模拟空目录.keep')}
class RecoveryError(Exception):
    pass

def now():
    return datetime.now(timezone.utc).isoformat()

def dump(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(CHUNK),b''):h.update(chunk)
    return h.hexdigest()

def canonical_name(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value or any(ord(c)<32 for c in value):
        raise RecoveryError('Unsafe member name')
    p=PurePosixPath(value)
    if p.is_absolute() or str(p)!=value or any(c in ('','..','.') for c in value.split('/')):
        raise RecoveryError('Unsafe member path: '+value)
    return unicodedata.normalize('NFC',value).casefold()

def allowed_member(name):
    parts=PurePosixPath(name).parts
    if any(p.startswith('.') or p=='__pycache__' for p in parts):return False
    if parts[0] in RUNTIME_DIRS:return len(parts)>1 and not name.endswith('.pyc')
    if name in COLLECTOR_FIXTURES:return True
    if name in REQUIRED or name in ('启动数据平台.command','outputs/BI一页概览.html'):return True
    if len(parts)==3 and parts[:2] in (('data','imports'),('data','device_files'),('data','recovery-wheels')):
        return name.endswith({'imports':'.xlsx','device_files':'.bin','recovery-wheels':'.whl'}[parts[1]])
    return len(parts)==3 and parts[0]=='outputs' and name.endswith('.xlsx')

def quote(name):
    return '"'+name.replace('"','""')+'"'

def connect_readonly(path):
    con=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    con.execute('PRAGMA trusted_schema=OFF')
    return con

def database_inventory(path):
    """All application/auth/migration tables, normalizing only import location."""
    with closing(connect_readonly(path)) as con:
        if con.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:
            raise RecoveryError('SQLite integrity check failed')
        if con.execute('PRAGMA foreign_key_check').fetchone():
            raise RecoveryError('SQLite foreign key check failed')
        schema=con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        tables={}
        for typ,name,_,_ in schema:
            if typ!='table':continue
            columns=con.execute('PRAGMA table_info('+quote(name)+')').fetchall()
            names=[c[1] for c in columns]
            keys=[c[1] for c in sorted(columns,key=lambda c:c[5]) if c[5]] or names
            h=hashlib.sha256(dump(names).encode());count=0
            for raw in con.execute('SELECT * FROM '+quote(name)+' ORDER BY '+','.join(map(quote,keys))):
                row=list(raw)
                if name=='app_importbatch':
                    row[names.index('file_path')]='data/imports/'+str(uuid.UUID(row[names.index('id')]))+'.xlsx'
                values=[{'base64':base64.b64encode(v).decode()} if isinstance(v,bytes) else v for v in row]
                h.update(dump(values).encode());h.update(b'\n');count+=1
            tables[name]={'rows':count,'sha256':h.hexdigest()}
        return {'schema_sha256':hashlib.sha256(dump(schema).encode()).hexdigest(),'tables':tables}

def original_refs(db):
    refs={}
    with closing(connect_readonly(db)) as con:
        try:
            for key,path,sha in con.execute('SELECT id,file_path,file_hash FROM app_importbatch'):
                refs['data/imports/'+str(uuid.UUID(key))+'.xlsx']={'sha256':sha,'stored_path':path}
            for key,sha,size in con.execute('SELECT id,file_hash,size FROM app_devicefile'):
                refs['data/device_files/'+str(uuid.UUID(key))+'.bin']={'sha256':sha,'size':size}
        except (sqlite3.DatabaseError,ValueError) as e:
            raise RecoveryError('Missing or invalid source-reference tables') from e
    if any(not re.fullmatch('[0-9a-f]{64}',v['sha256'] or '') for v in refs.values()):
        raise RecoveryError('Invalid original-file digest')
    return refs

def check_originals(root,db,path_root=None):
    refs=original_refs(db)
    for name,expected in refs.items():
        p=root/name
        if not p.is_file() or p.is_symlink() or sha_file(p)!=expected['sha256']:
            raise RecoveryError('Missing or damaged original: '+name)
        if 'size' in expected and p.stat().st_size!=expected['size']:
            raise RecoveryError('Original size mismatch: '+name)
        if path_root is not None and 'stored_path' in expected:
            if Path(expected['stored_path']).resolve()!=(path_root/name).resolve():
                raise RecoveryError('Original path does not belong to this installation: '+name)
    return len(refs)

def lock_entries(root):
    result={}
    for line in (root/'requirements.lock').read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        m=re.fullmatch(r'([A-Za-z0-9_.-]+)==([0-9A-Za-z.+-]+) --hash=sha256:([0-9a-f]{64})',line)
        if not m:raise RecoveryError('Dependency lock must contain exact versions and hashes only')
        name=re.sub(r'[-_.]+','-',m[1]).lower()
        if name in result:raise RecoveryError('Duplicate locked dependency')
        result[name]={'version':m[2],'sha256':m[3]}
    if set(result)!=EXPECTED_PACKAGES:raise RecoveryError('Runtime dependency set is incomplete or unexpected')
    return result

def check_wheels(root):
    expected=lock_entries(root);found=set()
    for wheel in sorted((root/'data/recovery-wheels').glob('*.whl')):
        if wheel.is_symlink() or not wheel.name.endswith('-none-any.whl'):
            raise RecoveryError('Only local pure-Python wheels are supported')
        digest=sha_file(wheel)
        with zipfile.ZipFile(wheel) as z:
            meta=[i for i in z.infolist() if i.filename.endswith('.dist-info/METADATA')]
            if len(meta)!=1 or meta[0].file_size>CHUNK:raise RecoveryError('Invalid wheel metadata')
            m=email.message_from_bytes(z.read(meta[0]))
        name=re.sub(r'[-_.]+','-',m.get('Name','')).lower()
        if name in found or name not in expected or expected[name]!={'version':m.get('Version'),'sha256':digest}:
            raise RecoveryError('Wheel does not match dependency lock: '+wheel.name)
        found.add(name)
    if found!=set(expected):raise RecoveryError('Missing offline dependency wheels')
    return expected

def check_collector_fixtures(root):
    # Only these generated synthetic examples are portable; never glob a PC path.
    manifest=root/'data/device_inbox/fixture_manifest.json'
    if not manifest.exists():
        if any((root/name).exists() for name in COLLECTOR_FIXTURES):raise RecoveryError('Incomplete collector fixtures')
        return set()
    if manifest.is_symlink() or manifest.parent.is_symlink():raise RecoveryError('Linked collector fixture manifest')
    try:
        value=json.loads(manifest.read_text())
        if value.get('synthetic') is not True or value.get('business_facts_changed') is not False:raise ValueError()
        rows=value['files'];members={'data/device_inbox/'+r['path'] for r in rows}
        expected=COLLECTOR_FIXTURES-{'data/device_inbox/fixture_manifest.json'}
        if len(rows)!=len(expected) or members!=expected:raise ValueError()
        for item in rows:
            name='data/device_inbox/'+item['path'];canonical_name(name);p=root/name
            if any(x.is_symlink() for x in (p, p.parent,p.parent.parent)):raise ValueError()
            if not p.is_file() or p.stat().st_size!=item['size'] or sha_file(p)!=item['sha256']:raise ValueError()
    except (OSError,ValueError,KeyError,TypeError):raise RecoveryError('Missing, linked or damaged collector fixture')
    return set(COLLECTOR_FIXTURES)
def pack_files(root,snapshot):
    files={'data/platform.sqlite3':snapshot}
    for folder in RUNTIME_DIRS:
        for p in (root/folder).rglob('*'):
            if '__pycache__' in p.parts or p.name=='.DS_Store' or p.suffix=='.pyc':continue
            if p.is_symlink():raise RecoveryError('Runtime symlink is not portable: '+str(p))
            if p.is_file():files[p.relative_to(root).as_posix()]=p
    for name in ['manage.py','README.md','requirements.txt','requirements.lock','启动数据平台.command',
                 'data/bi_design.json','outputs/BI需求与呈现方案.html','outputs/BI一页概览.html']:
        p=root/name
        if p.exists():files[name]=p
    for pattern in ['data/imports/*.xlsx','data/recovery-wheels/*.whl','outputs/*/*.xlsx']:
        for p in root.glob(pattern):files[p.relative_to(root).as_posix()]=p
    for name in original_refs(snapshot):files[name]=root/name
    for name in check_collector_fixtures(root):files[name]=root/name
    if not REQUIRED<=files.keys():raise RecoveryError('Missing runtime files: '+', '.join(sorted(REQUIRED-files.keys())))
    seen=set()
    for name,p in files.items():
        key=canonical_name(name)
        if not allowed_member(name):raise RecoveryError('Unexpected runtime file: '+name)
        if key in seen:raise RecoveryError('Ambiguous member names')
        seen.add(key)
        if p.is_symlink() or not p.is_file():raise RecoveryError('Missing or linked file: '+name)
    return files

def publish_file(source,dest):
    """Atomic no-overwrite publication, within one local filesystem."""
    os.link(source,dest)
    os.chmod(dest,0o600)

def pack(root,output):
    root=root.resolve();output=output.absolute()
    output.parent.mkdir(parents=True,exist_ok=True)
    sidecar=Path(str(output)+'.sha256');bootstrap=output.with_name(output.stem+'-recover.py')
    if any(p.exists() or p.is_symlink() for p in (output,sidecar,bootstrap)):
        raise RecoveryError('Output exists; select a new bundle name')
    dependencies=check_wheels(root)
    with tempfile.TemporaryDirectory(prefix='.motor-pack-',dir=output.parent) as temp:
        work=Path(temp);db=work/'snapshot.sqlite3'
        with closing(connect_readonly(root/'data/platform.sqlite3')) as src,closing(sqlite3.connect(db)) as dst:
            src.backup(dst,pages=512,sleep=.05)
        inventory=database_inventory(db)
        originals=check_originals(root,db,path_root=root)
        files=pack_files(root,db);entries=[];stats={}
        bundle=work/'bundle.zip'
        with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for name,p in sorted(files.items()):
                before=p.stat();stats[p]=(before.st_size,before.st_mtime_ns)
                h=hashlib.sha256();size=0
                with p.open('rb') as source,z.open(name,'w',force_zip64=True) as target:
                    for chunk in iter(lambda:source.read(CHUNK),b''):
                        target.write(chunk);h.update(chunk);size+=len(chunk)
                entries.append({'path':name,'size':size,'sha256':h.hexdigest()})
            expected=original_refs(db)
            for item in entries:
                e=expected.get(item['path'])
                if e and (item['sha256']!=e['sha256'] or ('size' in e and item['size']!=e['size'])):
                    raise RecoveryError('Original changed during packaging: '+item['path'])
            manifest={'format':FORMAT,'version':VERSION,'created_at':now(),
                      'runtime':{'python':list(PYTHON),'implementation':'CPython','source_python':platform.python_version(),'source_os':platform.system(),'scope':'Local SQLite demo; CPython 3.12 on macOS/Linux; not production deployment'},
                      'dependencies':dependencies,'database':inventory,'original_references':originals,'files':entries}
            z.writestr('manifest.json',dump(manifest))
        for p,signature in stats.items():
            s=p.stat()
            if signature!=(s.st_size,s.st_mtime_ns):raise RecoveryError('Source changed while packaging; retry: '+str(p))
        digest=sha_file(bundle)
        (work/'digest').write_text(digest+'  '+output.name+'\n')
        shutil.copyfile(root/'scripts/recovery.py',work/'recover.py')
        for src,dest in [(bundle,output),(work/'digest',sidecar),(work/'recover.py',bootstrap)]:publish_file(src,dest)
    return {'archive':str(output),'sha256':digest,'checksum_file':str(sidecar),'bootstrap':str(bootstrap),
            'files':len(entries),'original_references':originals,'tables':len(inventory['tables']),'bytes':output.stat().st_size}

def expected_checksum(archive,expected=None):
    if expected is None:
        sidecar=Path(str(archive)+'.sha256')
        if not sidecar.is_file() or sidecar.stat().st_size>4096:
            raise RecoveryError('Provide --sha256 from a trusted source or the matching .zip.sha256 file')
        parts=sidecar.read_text().split();expected=parts[0] if parts else ''
    if not re.fullmatch('[0-9a-f]{64}',expected):raise RecoveryError('Invalid expected SHA-256')
    if sha_file(archive)!=expected:raise RecoveryError('Archive SHA-256 mismatch; no files restored')
    return expected

def unpack_verified(archive,stage,expected=None):
    digest=expected_checksum(archive,expected)
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist();seen=set();by_name={};total=0
        if not 1<len(infos)<=MAX_FILES:raise RecoveryError('Invalid archive member count')
        for i in infos:
            key=canonical_name(i.filename)
            if i.filename!='manifest.json' and not allowed_member(i.filename):raise RecoveryError('Unexpected bundle member: '+i.filename)
            if key in seen:raise RecoveryError('Duplicate or ambiguous archive member')
            seen.add(key);by_name[i.filename]=i;total+=i.file_size
            mode=stat.S_IFMT(i.external_attr>>16)
            if i.is_dir() or mode not in (0,stat.S_IFREG) or i.flag_bits&1:
                raise RecoveryError('Archive must contain regular, unencrypted files only')
            if i.file_size<0 or total>MAX_BYTES:raise RecoveryError('Archive expansion limit exceeded')
        if 'manifest.json' not in by_name or by_name['manifest.json'].file_size>MAX_MANIFEST:
            raise RecoveryError('Missing or oversized manifest')
        manifest=json.loads(z.read('manifest.json'))
        if not isinstance(manifest,dict) or manifest.get('format')!=FORMAT or manifest.get('version')!=VERSION:
            raise RecoveryError('Unsupported recovery format')
        entries=manifest.get('files')
        if not isinstance(entries,list) or len(entries)!=len(infos)-1:raise RecoveryError('Manifest file coverage mismatch')
        names=set()
        for e in entries:
            if not isinstance(e,dict) or set(e)!={'path','size','sha256'}:raise RecoveryError('Invalid manifest entry')
            name=e['path'];canonical_name(name)
            if name in names or name=='manifest.json' or name not in by_name:raise RecoveryError('Manifest member mismatch')
            if type(e['size']) is not int or e['size']!=by_name[name].file_size or not re.fullmatch('[0-9a-f]{64}',str(e['sha256'])):
                raise RecoveryError('Invalid manifest size or digest')
            names.add(name)
        if names!=set(by_name)-{'manifest.json'} or not REQUIRED<=names:
            raise RecoveryError('Incomplete runtime or uncovered archive members')
        # The fresh staging directory is never shared with an existing installation.
        for e in entries:
            dest=stage/e['path'];dest.parent.mkdir(parents=True,exist_ok=True)
            h=hashlib.sha256();size=0
            with z.open(e['path']) as source,dest.open('xb') as target:
                for chunk in iter(lambda:source.read(CHUNK),b''):
                    size+=len(chunk)
                    if size>e['size']:raise RecoveryError('Expanded member exceeds declared size')
                    h.update(chunk);target.write(chunk)
            if size!=e['size'] or h.hexdigest()!=e['sha256']:raise RecoveryError('Member digest mismatch: '+e['path'])
    if check_wheels(stage)!=manifest.get('dependencies'):raise RecoveryError('Dependency manifest mismatch')
    db=stage/'data/platform.sqlite3'
    if database_inventory(db)!=manifest.get('database'):raise RecoveryError('Database content or schema mismatch')
    if check_originals(stage,db)!=manifest.get('original_references'):raise RecoveryError('Original reference count mismatch')
    check_collector_fixtures(stage)
    return manifest,digest

def verify(archive,expected=None):
    with tempfile.TemporaryDirectory(prefix='motor-verify-') as temp:
        manifest,digest=unpack_verified(archive,Path(temp),expected)
    return {'verified':True,'sha256':digest,'created_at':manifest['created_at'],
            'files':len(manifest['files']),'original_references':manifest['original_references'],
            'database':manifest['database'],'runtime':manifest['runtime']}

def runtime_check(manifest):
    if os.name!='posix' or platform.python_implementation()!='CPython' or tuple(sys.version_info[:2])!=PYTHON:
        raise RecoveryError('Restore requires CPython 3.12 on macOS/Linux; Python itself is not bundled')
    if manifest.get('runtime',{}).get('python')!=list(PYTHON):raise RecoveryError('Unsupported bundle Python version')

def clean_environment():
    # No inherited PYTHONPATH, VIRTUAL_ENV, pip configuration, or database override.
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','LANG','LC_ALL','SYSTEMROOT')}
    env.update(PYTHONNOUSERSITE='1',PIP_CONFIG_FILE=os.devnull,PIP_DISABLE_PIP_VERSION_CHECK='1',MOTOR_DEBUG='1')
    return env

def run_checked(args,root,log,timeout=180):
    result=subprocess.run(args,cwd=root,env=clean_environment(),stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout)
    with log.open('a') as f:f.write('$ '+' '.join(map(str,args))+'\n'+result.stdout+'\n')
    if result.returncode:raise RecoveryError('Runtime check failed; see '+str(log))
    return result.stdout

def rebase_imports(root):
    db=root/'data/platform.sqlite3'
    with closing(sqlite3.connect(db)) as con:
        con.execute('PRAGMA trusted_schema=OFF')
        changes=[(str(root/'data/imports'/(str(uuid.UUID(key))+'.xlsx')),key) for (key,) in con.execute('SELECT id FROM app_importbatch')]
        with con:con.executemany('UPDATE app_importbatch SET file_path=? WHERE id=?',changes)
    return len(changes)

def install_runtime(root):
    log=root/'data/recovery-install.log'
    run_checked([sys.executable,'-I','-m','venv',str(root/'.venv')],root,log)
    py=root/'.venv/bin/python'
    run_checked([str(py),'-I','-m','pip','--isolated','install','--no-index','--no-cache-dir','--no-deps','--require-hashes',
                 '--find-links',str(root/'data/recovery-wheels'),'-r',str(root/'requirements.lock')],root,log)
    expected=lock_entries(root)
    probe="import importlib.metadata as m,sys,json; from pathlib import Path; e=json.loads(sys.argv[1]); root=Path(sys.prefix).resolve(); assert sys.prefix!=sys.base_prefix; assert all(m.version(n)==v['version'] and Path(m.distribution(n).locate_file('')).resolve().is_relative_to(root) for n,v in e.items()); print('All locked dependencies resolve inside the new virtual environment')"
    run_checked([str(py),'-I','-c',probe,dump(expected)],root,log)
    run_checked([str(py),str(root/'manage.py'),'check'],root,log)
    run_checked([str(py),str(root/'manage.py'),'migrate','--check'],root,log)
    return str(py)

def restore(archive,target,expected=None):
    target=target.absolute()
    if target.exists() or target.is_symlink():raise RecoveryError('Target already exists; restoration never overwrites a directory')
    if not target.parent.is_dir():raise RecoveryError('Target parent must already exist')
    # Canonical parent avoids alternate symlink locations in stored import paths.
    target=target.parent.resolve()/target.name
    with tempfile.TemporaryDirectory(prefix='.motor-restore-',dir=target.parent) as temp:
        stage=Path(temp);manifest,digest=unpack_verified(archive,stage,expected);runtime_check(manifest)
        target.mkdir(mode=0o700) # Atomic reservation. A concurrently created target is refused.
        marker=target/'.restore-in-progress';marker.write_text(dump({'started_at':now(),'archive_sha256':digest}))
        try:
            for p in stage.iterdir():shutil.move(str(p),str(target/p.name))
            changed=rebase_imports(target)
            if database_inventory(target/'data/platform.sqlite3')!=manifest['database']:
                raise RecoveryError('Business/configuration rows changed during path migration')
            check_originals(target,target/'data/platform.sqlite3',path_root=target)
            python=install_runtime(target)
            for p in target.glob('*.command'):p.chmod(0o700)
            result={'status':'ready','restored_at':now(),'archive':str(archive.resolve()),'archive_sha256':digest,
                    'target':str(target),'python':python,'files':len(manifest['files']),
                    'import_paths_rebased':changed,'original_references':manifest['original_references'],
                    'all_database_tables_preserved':manifest['database'],'dependencies':manifest['dependencies'],
                    'scope':'Isolated local SQLite demo. Existing accounts and audit history preserved. No service started.',
                    'start_command':f'{python} scripts/serve.py start --port 8766'}
            (target/'data/recovery-manifest.json').write_text(dump(manifest))
            (target/'data/recovery-restore.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            marker.unlink()
            return result
        except BaseException as e:
            # Retain this new isolated directory for diagnosis; never delete other work.
            marker.write_text(dump({'status':'failed','failed_at':now(),'error':str(e),'archive_sha256':digest}))
            raise

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    packing=commands.add_parser('pack');packing.add_argument('--root',type=Path,default=ROOT);packing.add_argument('--output',type=Path)
    for name in ['verify','restore']:
        p=commands.add_parser(name);p.add_argument('archive',type=Path);p.add_argument('--sha256')
        if name=='restore':p.add_argument('--target',type=Path,required=True)
    a=parser.parse_args(argv)
    try:
        if a.command=='pack':
            dest=a.output or a.root/'data/recovery-packages'/('motor-full-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.zip')
            result=pack(a.root,dest)
        elif a.command=='verify':result=verify(a.archive,a.sha256)
        else:result=restore(a.archive,a.target,a.sha256)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (RecoveryError,OSError,ValueError,KeyError,TypeError,sqlite3.DatabaseError,zipfile.BadZipFile,subprocess.SubprocessError) as e:
        print('RECOVERY FAILED: '+str(e),file=sys.stderr);return 1

if __name__=='__main__':
    raise SystemExit(main())
