"""Consistent SQLite snapshot plus immutable import sources and metadata."""
import sqlite3,zipfile,json,hashlib
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'data/backups';folder.mkdir(exist_ok=True)
stamp=datetime.now().strftime('%Y%m%d-%H%M%S');snapshot=folder/f'snapshot-{stamp}.sqlite3'
with sqlite3.connect(ROOT/'data/platform.sqlite3') as source,sqlite3.connect(snapshot) as target:source.backup(target)
dest=folder/f'motor-backup-{stamp}.zip';pending=dest.with_suffix('.zip.partial');manifest=[]
with zipfile.ZipFile(pending,'w',zipfile.ZIP_DEFLATED) as z:
    files=[(snapshot,'data/platform.sqlite3')]
    files += [(p,str(p.relative_to(ROOT))) for p in (ROOT/'data/imports').glob('*.xlsx')]
    files += [(p,str(p.relative_to(ROOT))) for p in [ROOT/'data/bi_design.json'] if p.exists()]
    expected_device={}
    with sqlite3.connect(snapshot) as captured:
        if captured.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_devicefile'").fetchone():
            import uuid
            for key,sha,size in captured.execute('SELECT id,file_hash,size FROM app_devicefile'):
                name='data/device_files/'+str(uuid.UUID(key))+'.bin';expected_device[name]=(sha,size);files.append((ROOT/name,name))
    for path,name in files:
        raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        if name in expected_device and (sha,len(raw))!=expected_device[name]:raise RuntimeError('Device original integrity mismatch: '+name)
        z.writestr(name,raw);manifest.append({'path':name,'sha256':sha,'size':len(raw)})
    z.writestr('manifest.json',json.dumps({'created':stamp,'files':manifest},ensure_ascii=False,indent=2))
pending.replace(dest)
print(dest)
