import argparse,hashlib,json,shutil,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--revision',choices=['v1','v2'],default='v1');a=parser.parse_args()
 p=OUT/'BI深化设计_20261007_离线资料包.zip';before=ROOT/('data/backups/bi-design-before-finite-schedule' if a.revision=='v1' else 'data/backups/bi-design-before-finite-schedule-v2');sidecar=Path(str(p)+'.sha256')
 if before.exists():assert sha(p.read_bytes())==sha((before/p.name).read_bytes()) and sidecar.read_bytes()==(before/sidecar.name).read_bytes(),'Only retry an unchanged failed preparation'
 else:before.mkdir();shutil.copy2(p,before/p.name);shutil.copy2(sidecar,before/sidecar.name)
 shutil.copy2(ROOT/'data/bi_design.json',OUT/'BI需求与定义数据_v9.json');book=ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/36_有限资源试排_模拟.xlsx'
 with zipfile.ZipFile(p) as z:payload={n:z.read(n) for n in z.namelist() if n!='资料清单与SHA256.json'}
 for n in list(payload):
  if not n.startswith('证据/'):payload[n]=(book if n==book.name else OUT/n).read_bytes()
 payload['BI有限资源试排说明_20261007.txt']=(OUT/'BI有限资源试排说明_20261007.txt').read_bytes()
 book=ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/36_有限资源试排_模拟.xlsx';payload[book.name]=book.read_bytes()
 for name,title in [('finite_schedule_release.json','有限资源试排原始导入及旧数据保留'),('finite_schedule_http.json','有限资源试排六岗位原生HTTP_非浏览器'),('finite_schedule_design.json','有限资源试排BI覆盖核对'),('finite_schedule_presentation.json','有限资源试排纯呈现核对_非浏览器')]:
  v=json.loads((ROOT/'data'/name).read_text());assert v['success'];payload['证据/'+title+'.json']=(ROOT/'data'/name).read_bytes()
 if a.revision=='v2':
  v=json.loads((ROOT/'data/finite_schedule_http_v2.json').read_text());assert v['success'];payload['证据/有限资源试排暂停输入导出补验_非浏览器.json']=(ROOT/'data/finite_schedule_http_v2.json').read_bytes()
 manifest=dict(scope='26域382候选/63建议口径/17蓝图/18方法；116模拟部分覆盖，266待建设。有限资源试排的独立模拟资料及核对，不含数据库或凭据，不是应用恢复包。浏览器、手机及实际下载未验收。',files={n:dict(bytes=len(b),sha256=sha(b)) for n,b in payload.items()});payload['资料清单与SHA256.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
 with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
  for n,b in payload.items():z.writestr(n,b)
 with zipfile.ZipFile(p) as z:
  assert not z.testzip() and set(z.namelist())==set(payload)
  for n,b in payload.items():assert z.read(n)==b
 digest=sha(p.read_bytes());sidecar.write_text(digest+'  '+p.name+'\n');proof=dict(success=True,members=len(payload),sha256=digest,archive=str(p),all_members_verified=True,no_database_or_credentials=True,browser_acceptance=False)
 (ROOT/'data/finite_schedule_design_package.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
if __name__=='__main__':main()
