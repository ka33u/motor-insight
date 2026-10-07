"""Refresh the offline BI primary documents; retain explicitly historical companions."""
import hashlib,json,shutil,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'
def sha(value):return hashlib.sha256(value).hexdigest()
def main():
 catalog=json.loads((ROOT/'data/bi_design.json').read_text());shutil.copyfile(ROOT/'data/bi_design.json',OUT/'BI需求与定义数据_v9.json')
 counts=catalog['planning_summary']['implementation_counts'];lines=['电机制造企业BI方案阅读说明','2026-10-07 班次效率增量','',f'26领域、382项候选需求、63项建议指标、17页蓝图、18类方法；当前{counts["模拟部分覆盖"]}项模拟部分覆盖、{counts["待建设"]}项待建设。',
 '主文件《BI深化方案_业务阅读版_20261007.txt》包含BI定义、呈现、17页蓝图、全部382项需求和63项口径。','逐项来源、适用性、责任、展示、验收和缺口另见《BI完整382项需求清单.txt》。','快速阅读见《BI定义与呈现_快速阅读版.txt》；离线HTML内含样式脚本，无须启动平台服务。','班次效率见《BI班次设备效率说明_20261007.txt》和第38份原始模拟Excel，5表123行、10独立案例。','每页按范围与可信度、1至3主结果、解释、异常对象、来源版本、责任与复查呈现。','新增验证记录放在“证据/”中；既有证明及截图是对应较早增量的历史资料，不能作为当前浏览器验收证明。','K18为澄清后的建议口径，未发布正式指标。当前全部业务输入为合成数据，真实U8/MES、浏览器、手机及实际下载未验收。','设计包不含数据库、账号凭据或活动读取凭据；完整应用恢复包独立保存。']
 (OUT/'BI方案阅读说明_v9.txt').write_text('\n'.join(lines)+'\n')
 concise=['BI展示深化简明方案','',lines[3],'',catalog['framework']['presentation_design']['reading_guide']['definition'],'','业务主线：订单行、工单、部件批次、单台SN、检测、发运和签收；配置、BOM、工艺和规范均带版本。','定义：需求、事实维度、指标、分析模型、专题页面、处理与复查分别管理。','呈现：经营总览、岗位工作台、专题分析、对象履历、现场大屏、手机查询、受控导出。','先期问题：订单交付风险、缺料与在制、漏检与首检、单台追溯、数据缺口。','创新：配置可比性门槛、异常反查订单、数字变化解释、双时间复盘、资料缺口队列、明确假设的情景对照。','班次效率新增：损失时间带、配置窗口A/P/Q/OEE、停止并集与计划外片段、首次数量分类、来源及完整导出。混配置标明时间汇总，资料未闭合暂停。','全部需求、指标建议、页面设计见业务阅读版；建议清单持续补充与裁剪，不一次性开发382项。','当前模拟结果不能替代真实经营、工艺判定或正式批准。']
 (OUT/'BI展示深化_简明方案_20261007.txt').write_text('\n'.join(concise)+'\n')
 p=OUT/'BI深化设计_20261007_离线资料包.zip';prior=ROOT/'data/oee-before/outputs'/p.name
 with zipfile.ZipFile(prior) as z:payload={n:z.read(n) for n in z.namelist() if n!='资料清单与SHA256.json'}
 for name in list(payload):
  file=OUT/name
  if not name.startswith('证据/') and file.is_file():payload[name]=file.read_bytes()
 for name in ('BI深化方案_业务阅读版_20261007.txt','BI班次设备效率说明_20261007.txt','BI完整382项需求清单.txt','BI需求与呈现方案.html','BI定义与呈现_快速阅读版.txt','BI需求与定义数据_v9.json','BI方案阅读说明_v9.txt','BI展示深化_简明方案_20261007.txt'):payload[name]=(OUT/name).read_bytes()
 book=OUT/'01a0f580-2480-7820-bc97-8ca293421c39/38_班次设备效率_模拟.xlsx';payload[book.name]=book.read_bytes()
 for name,title in [('oee_release_main.json','班次效率正常导入及旧事实保留'),('oee_http.json','班次效率六岗位原生HTTP_非浏览器'),('oee_design.json','BI完整目录与离线资料核对'),('oee_ui.json','班次效率纯JS结构核对')]:
  file=ROOT/'data'/name;proof=json.loads(file.read_text());assert proof['success'];payload['证据/'+title+'.json']=file.read_bytes()
 manifest=dict(scope='当前主文件覆盖26域382候选、63口径建议、17页蓝图、18方法；118模拟部分覆盖/264待建设。新增班次效率10例123行。历史同伴及截图按原增量保存；浏览器、手机及实际下载未验收。不含数据库或凭据，不是应用恢复包。',primary=['BI方案阅读说明_v9.txt','BI深化方案_业务阅读版_20261007.txt','BI完整382项需求清单.txt','BI班次设备效率说明_20261007.txt'],files={n:dict(bytes=len(b),sha256=sha(b)) for n,b in payload.items()});payload['资料清单与SHA256.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
 with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
  for name,b in payload.items():z.writestr(name,b)
 with zipfile.ZipFile(p) as z:
  assert not z.testzip() and set(z.namelist())==set(payload)
  for name,b in payload.items():assert z.read(name)==b
 digest=sha(p.read_bytes());Path(str(p)+'.sha256').write_text(digest+'  '+p.name+'\n');proof=dict(success=True,members=len(payload),archive=str(p),sha256=digest,crc_and_member_bytes_verified=True,no_database_or_credentials=True,workbook_included=True,browser_acceptance=False);(ROOT/'data/oee_design_package.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
if __name__=='__main__':main()
