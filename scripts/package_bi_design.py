"""Package the same verified catalog and label previous screenshots honestly."""
import json,hashlib,zipfile,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'
catalog=json.loads((ROOT/'data/bi_design.json').read_text());count=sum(len(x['items']) for x in catalog['domains'])
version=catalog['version']
assert (version,count)==(9,382)
shutil.copyfile(ROOT/'data/bi_design.json',OUT/f'BI需求与定义数据_v{version}.json')
archive=OUT/f'BI设计_v{version}_离线资料包.zip'
backup=ROOT/'data/backups/bi-v9-before';backup.mkdir(exist_ok=True)
if archive.exists() and not (backup/archive.name).exists():shutil.copyfile(archive,backup/archive.name)
names=['BI展示内容与定义总览.txt',f'BI完整{count}项需求清单.txt',f'BI定义与呈现构思_v{version}.txt','BI需求与呈现方案.html','BI一页概览.html',f'BI需求与定义数据_v{version}.json',f'BI方案阅读说明_v{version}.txt']
if catalog['framework'].get('execution_design'):
    names.append('BI建设分层与页面内容_实施补充.txt')
if catalog['framework'].get('presentation_design'):
    names.append('BI展示内容与交互设计_完善版.txt')
    names.append('BI定义与呈现_快速阅读版.txt')
if (OUT/'首页关注点与业务观察说明.txt').exists():names.append('首页关注点与业务观察说明.txt')
if (OUT/'专题整范围摘要与快照说明.txt').exists():names.append('专题整范围摘要与快照说明.txt')
if (OUT/'BI字段字典与建模口径说明.txt').exists():names.append('BI字段字典与建模口径说明.txt')
if (OUT/'设备目录与待采集说明.txt').exists():names.append('设备目录与待采集说明.txt')
if (OUT/'本地设备文件采集与BI回执说明.txt').exists():names.append('本地设备文件采集与BI回执说明.txt')
if (OUT/'检测CSV字段转换与BI依据说明.txt').exists():names.append('检测CSV字段转换与BI依据说明.txt')
if (OUT/'专题点选联动与范围一致说明.txt').exists():names.append('专题点选联动与范围一致说明.txt')
files={name:{'bytes':(OUT/name).stat().st_size,'sha256':hashlib.sha256((OUT/name).read_bytes()).hexdigest()} for name in names}
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for name in names:z.write(OUT/name,name)
with zipfile.ZipFile(archive) as z:
    assert not z.testzip() and set(z.namelist())==set(names)
    for name in names:assert z.read(name)==(OUT/name).read_bytes()
report={'version':version,'archive':str(archive),'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'crc_verified':True,'files':files,
        'scope':'Design proposals with 382 needs, 63 candidate metric definitions and 17 page blueprints, A-02 is additionally marked partially covered by the verified homepage observation increment; other synthetic coverage labels are retained. Adds 382 presentation contracts, 17 reading tasks, 12 presentation formats and 12 cross-department journeys. Existing topic selected-measure summaries recompute complete authorized populations; frozen summaries preserve source and definition bindings. This increment retains all requirement coverage states. Adds read-only field documentation, permission-scoped metadata search and matching CSV/JSON exports; unit hints do not extend formula permissions. No new published metric, business fact, source-system integration or approval action. Structural/text/syntax and existing design-draft server tests passed; browser rendering, mobile interaction and actual downloads remain unverified. No screenshots from older revisions are presented as current. This is not an application recovery package.'}
report['execution_design']=catalog['planning_summary'].get('execution_design')
report['device_intake_scope']='W-21由待建设改为模拟部分覆盖：新增三类标准Excel来源，225合成登记行，经正常导入。原文件、109旧数据集和52模型/33目标/v8发布不改。全目录契约变化后使用原模拟样例通过原生API重新核对并启用模板v2；v1原内容留存，状态被替代。无实际设备扫描、自动采集或浏览器验收。覆盖合计111模拟部分覆盖、271待建设。'
report['scope']='26业务域、382项候选需求、63项指标定义建议、17页蓝图及对应阅读、定义与呈现契约。既有摘要、字段字典和问题清单说明保留。新增设备发现清单的225条模拟来源登记，W-21仅标为模拟部分覆盖；原业务事实、模型、目标及已发布指标不改。命名模板v2由原模拟样例重新表头核对，未作真实业务审批。所有浏览器、手机及实际下载验收状态保持未验收。离线包不是应用恢复包。'
report['presentation_design']=catalog['planning_summary'].get('presentation_design')
report['device_collector_scope']='W-21维持模拟部分覆盖，新增白名单本地模拟文件的两次稳定观察、冻结清单、私有归档复用、历史回执与当前完整性、失败重试。主库7观察/5文件/4新原件，原业务事实不改，无自动关联、授权或放行。真实设备PC代理、持续采集、U8/MES及浏览器/手机/实际下载未验收。111部分/271待建设不变。'
report['device_transform_scope']='私有CSV字段模板、显式单位/时间/判定码、24行3会话全部核对、另存标准文件与逐行回执；来源仍是Excel导入模拟事实。仅扩充W-21/P05/P06/P15范围，111模拟部分覆盖/271待建设不变；无新检测、关联、授权、放行或指标发布。浏览器、手机、实际下载与真实源接口未验收。'
report['topic_linkage_scope']='7类直接身份条件的双侧交集、逐卡字段/暂停、来源/摘要/CSV/个人视角/新快照同范围；主库未写入，111部分/271待建设不变。27新增及2053全套测试通过，模拟Excel来源与隔离副本验证；浏览器、手机、实际键盘操作与下载未验收。'
(ROOT/f'data/bi_v{version}_delivery_package.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='files'},ensure_ascii=False))
