"""Create vendor-protocol examples from facts already imported through Excel."""
import csv,hashlib,io,json,os,sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app import device_files as files

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def generate():
 before=sha(ROOT/'data/platform.sqlite3');out=ROOT/'outputs/device_transform_samples';out.mkdir(exist_ok=True);manifest=out/'manifest.json'
 if manifest.exists():
  d=json.loads(manifest.read_text());assert d['synthetic'] and not d['business_facts_changed']
  for f in d['files']:assert sha(out/f['filename'])==f['sha256']
  return d
 eq='SB-08-01';sessions=list(Record.objects.filter(dataset='test_sessions',values__equipment_id=eq,values__complete=True,values__voided=False).order_by('business_key')[:3]);assert len(sessions)==3
 aliases=['试验会话号','电机标识','制造工单','配置编码','检测机台','测量时刻','检验版次','测量结果号','规范项目号','原始读数','原始计量单位','机台标准读数','机台标准单位','判定代码'];rows=[];sources={};standard=[]
 for s in sessions:
  t=files.target(s.business_key);sources.update(t['sources'])
  for m in t['measurements']:
   row={**{k:t[k] for k in files.HEADERS[:7]},'measurement_id':m['id'],**{k:m[k] for k in files.HEADERS[8:]}};standard.append(row)
   vendor=dict(row);vendor['tested']=datetime.fromisoformat(row['tested']).strftime('%Y/%m/%d %H:%M:%S');vendor['result']={'合格':'PASS','不合格':'FAIL','不完整':'MISS'}[row['result']]
   if vendor['unit']=='Ω':vendor['value']=format(Decimal(str(vendor['value']))*1000,'f');vendor['unit']='mΩ'
   rows.append(dict(zip(aliases,[str(vendor[k]) for k in files.HEADERS])))
 bad=[dict(r) for r in rows];bad[0]['电机标识']='M260921999999';bad[0]['判定代码']='UNKNOWN'
 items=[]
 for name,content,purpose in [('01_模拟厂商机台_分号与毫欧.csv',rows,'正确标准内容，需显式换算/日期/判定码'),('02_模拟厂商机台_错SN与未知判定.csv',bad,'身份及判定差异阻止转换')]:
  stream=io.StringIO();w=csv.DictWriter(stream,aliases,delimiter=';');w.writeheader();w.writerows(content);file=out/name
  with file.open('xb') as target:target.write(stream.getvalue().encode('gb18030'))
  items.append(dict(filename=name,sha256=sha(file),size=file.stat().st_size,purpose=purpose))
 spec=dict(encoding='gb18030',delimiter=';',headers=aliases,fields={k:dict(column=h) for k,h in zip(files.HEADERS,aliases)},result_map={'PASS':'合格','FAIL':'不合格','MISS':'不完整'},tested_format='%Y/%m/%d %H:%M:%S',conversions=['mΩ→Ω'])
 result=dict(synthetic=True,derived_from='当前已经由Excel导入的合成事实；这是模拟协议导出，不是真实检测证据',business_facts_changed=False,definition=spec,sessions=[s.business_key for s in sessions],rows=len(rows),standard_expected=standard,excel_sources=sources,files=items)
 manifest.write_text(json.dumps(result,ensure_ascii=False,indent=2));assert sha(ROOT/'data/platform.sqlite3')==before;return result
if __name__=='__main__':
 d=generate();print(json.dumps(dict(synthetic=True,files=len(d['files']),rows=d['rows'],sessions=d['sessions']),ensure_ascii=False))
