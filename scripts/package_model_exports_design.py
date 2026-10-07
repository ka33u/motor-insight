import hashlib,json,shutil,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 p=OUT/'BI深化设计_20261007_离线资料包.zip';before=ROOT/'data/backups/bi-design-before-model-exports';before.mkdir();shutil.copy2(p,before/p.name);sidecar=Path(str(p)+'.sha256');shutil.copy2(sidecar,before/sidecar.name);shutil.copy2(ROOT/'data/bi_design.json',OUT/'BI需求与定义数据_v9.json')
 with zipfile.ZipFile(p) as z:payload={n:z.read(n) for n in z.namelist() if n!='资料清单与SHA256.json'}
 for name in list(payload):
  if not name.startswith('证据/'):payload[name]=(OUT/name).read_bytes()
 payload['BI模型当前结果导出说明_20261007.txt']=(OUT/'BI模型当前结果导出说明_20261007.txt').read_bytes()
 examples=json.loads((ROOT/'data/model_exports_examples.json').read_text());assert examples['success']
 for x in examples['examples']:
  b=(OUT/x['name']).read_bytes();assert sha(b)==x['sha256'];payload[x['name']]=b
 payload['证据/模型当前结果导出样例核对.json']=(ROOT/'data/model_exports_examples.json').read_bytes()
 for name,title in [('model_exports_rehearsal.json','模型结果导出52模型与主库保留核对'),('model_exports_http_validation.json','模型结果导出原生HTTP核对_非浏览器'),('model_exports_design_validation.json','模型结果导出设计覆盖核对')]:
  proof=json.loads((ROOT/'data'/name).read_text());assert proof['success'];payload['证据/'+title+'.json']=(ROOT/'data'/name).read_bytes()
 manifest=dict(scope='26域382候选/63建议口径/17蓝图/18方法；模型当前结果导出的设计与模拟核对。不含数据库或凭据，不是应用恢复包；浏览器、手机与实际下载未验收。',files={n:dict(bytes=len(b),sha256=sha(b)) for n,b in payload.items()});payload['资料清单与SHA256.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
 with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
  for name,b in payload.items():z.writestr(name,b)
 with zipfile.ZipFile(p) as z:
  assert not z.testzip() and set(z.namelist())==set(payload)
  for name,b in payload.items():assert z.read(name)==b
 digest=sha(p.read_bytes());sidecar.write_text(digest+'  '+p.name+'\n');proof=dict(success=True,members=len(payload),sha256=digest,archive=str(p),crc_and_member_bytes_verified=True,no_database_or_credentials=True,browser_acceptance=False)
 (ROOT/'data/model_exports_design_package.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
if __name__=='__main__':main()
