"""Capture the current verified MSA parent before adding model definition cards."""
import hashlib,json,shutil,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];dest=ROOT/'data/model-cards-before'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 assert not dest.exists();dest.mkdir();parent=json.loads((ROOT/'data/msa_phase_release.json').read_text());db=ROOT/'data/platform.sqlite3';assert sha(db)==parent['main_database_sha256'];shutil.copy2(db,dest/'platform.sqlite3')
 old=json.loads((ROOT/'data/msa-before/manifest.json').read_text());physical={name:sha(ROOT/name) for name in old['physical']}
 release=json.loads((ROOT/'data/msa_release.json').read_text());name='data/imports/'+release['batch_id']+'.xlsx';physical[name]=sha(ROOT/name);name='outputs/01a0f580-2480-7820-bc97-8ca293421c39/35_测量系统交叉采样_模拟.xlsx';physical[name]=sha(ROOT/name)
 protected={name:sha(ROOT/name) for name in old['protected']}
 runtime=['app/models.py','app/views.py','config/urls.py','static/app.js','templates/index.html','data/bi_design.json','scripts/refine_bi_catalog.py']
 for name in runtime:
  p=dest/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,p)
 with sqlite3.connect(db) as c:tables={name:c.execute('SELECT count(*) FROM "'+name+'"').fetchone()[0] for name, in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
 result=dict(database_sha256=sha(db),physical=physical,protected=protected,table_counts=tables,parent_evidence='data/msa_phase_release.json',raw_facts=214523,delivery_v8_hash='9d9a5af3d45172eca16790d628a36bc6acbe18d1e2a811a66a5b5fbff7037fe3')
 (dest/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dict(success=True,tables=len(tables)-1,physical=len(physical),protected=len(protected),database_sha256=result['database_sha256'])))
if __name__=='__main__':main()
