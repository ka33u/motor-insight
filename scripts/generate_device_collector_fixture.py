"""Serialize device-protocol fixtures from already Excel-imported synthetic facts."""
import csv,hashlib,io,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app import device_files as files

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def generate():
 before=sha(ROOT/'data/platform.sqlite3');base=ROOT/'data/device_inbox';manifest_path=base/'fixture_manifest.json'
 if manifest_path.exists():
  d=json.loads(manifest_path.read_text());assert d['synthetic'] and d['business_facts_changed'] is False
  for item in d['files']:assert sha(base/item['path'])==item['sha256'] and (base/item['path']).stat().st_size==item['size']
  assert sha(ROOT/'data/platform.sqlite3')==before;return d
 source=Record.objects.get(dataset='device_sources',business_key='DS-PC-2026-001');equipment=source.values['equipment_id']
 retest=Record.objects.filter(dataset='test_sessions',values__equipment_id=equipment,values__attempt=2,values__complete=True,values__voided=False).order_by('business_key').first();assert retest
 first=Record.objects.filter(dataset='test_sessions',values__equipment_id=equipment,values__unit_id=retest.values['unit_id'],values__attempt=1,values__complete=True,values__voided=False).first();assert first
 def raw(r,wrong=False):
  t=files.target(r.business_key);rows=[]
  for m in t['measurements']:
   row={**{k:t[k] for k in files.HEADERS[:7]},'measurement_id':m['id'],**{k:m[k] for k in files.HEADERS[8:]}}
   if wrong:row['unit_id']='M260921999999'
   rows.append(row)
  out=io.StringIO();w=csv.DictWriter(out,files.HEADERS);w.writeheader();w.writerows(rows);return out.getvalue().encode('utf-8-sig'),t['sources']
 good,firstrefs=raw(first);again,retestrefs=raw(retest);bad,badrefs=raw(retest,True)
 data=[('DS-PC-2026-001/首测.csv',good,firstrefs,'完整标准CSV，可核对'),('DS-PC-2026-001/首测_copy.csv',good,firstrefs,'同字节重复路径，复用私有原件'),('DS-PC-2026-001/复测.csv',again,retestrefs,'完整标准CSV，可核对'),('DS-PC-2026-001/线索错位.csv',bad,badrefs,'故意错误SN，内容对照不通过'),('DS-PC-2026-001/设备交接说明.txt',f'仅为本地模拟设备导出，不是真实采集证据。\n会话 {retest.business_key}\nSN {retest.values["unit_id"]}\n人工核对内容；不自动关联或放行。\n'.encode(),[files.source(retest)],'未结构化，人工核对'),('DS-PC-2026-001/临时.csv.part',b'simulation incomplete temporary export',[],'临时格式跳过'),('DS-PC-2026-001/过大.csv',b'0'*(files.MAX_BYTES+1),[],'8MB以上，跳过内容读取'),('DS-PC-2026-002/模拟空目录.keep',b'synthetic local directory marker',[],'隐藏标识，不采集')]
 base.mkdir(exist_ok=True);items=[]
 for name,content,refs,purpose in data:
  p=base/name;p.parent.mkdir(exist_ok=True)
  with p.open('xb') as out:out.write(content)
  os.utime(p,(time.time()-60,time.time()-60));items.append(dict(path=name,sha256=sha(p),size=len(content),purpose=purpose,excel_sources=refs))
 result=dict(synthetic=True,derived_from='已经由Excel导入的模拟事实；设备协议序列化，非真实设备采集',business_facts_changed=False,source=files.source(source),expected=dict(source_001_observations=7,stable_selectable=5,distinct_private_originals=4,duplicates=1,skipped=1,too_big=1),files=items)
 manifest_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');assert sha(ROOT/'data/platform.sqlite3')==before;return result
if __name__=='__main__':
 d=generate();print(json.dumps(dict(synthetic=d['synthetic'],files=len(d['files']),expected=d['expected']),ensure_ascii=False))
