"""Reversible verified scope for private source-preserving CSV templates."""
from refine_bi_device_collector import STATUS as PRIOR
MARKER='检测CSV字段转换：'
STATUS='保留设备目录覆盖及本地模拟采集；新增私有CSV字段转换工作台：明确编码、分隔符、完整表头与14项字段映射，原始读数/单位和会话/SN/结果身份必须来自原列；设备、规范等固定声明显式保留。同量纲单位换算、秒级本地日期格式和判定码映射可配置，未知码、非有限数值、源列变化、重复结果、缺项或任一当前字段差异阻止生成标准文件。模板自定义编码、草稿、样例核对、启用与被替代版本保留；规则、源原件或业务依据变化需重新核对，启用仅为私有配置，不是业务审批。另存标准CSV保留源文件SHA256、模板/转换版本、原行/原值、变化明细及Excel会话依据；历史转换、当前原件完整性和当前业务变化分别显示，可按同申请重放并导出完整回执。24合成结果行/3会话演练通过，错SN与未知码被阻止。没有新检测、自动关联、授权、放行、订单写回或指标发布；来源仍来自已导入模拟Excel。仅支持已归档CSV和列式字段映射，不支持PDF/OCR、厂商二进制格式、执行脚本、宽表自动转长表、真实设备PC代理、后台巡检或U8/MES；浏览器/手机/实际下载未验收。'
ROW=['检测原件字段转换与依据','不同机台的列名、单位和编号能否核对成同一检测证据？','私有源CSV → 显式字段与转换规则 → 全部会话对照 → 模板版本启用 → 另存标准文件 → 原件/当前业务与历史回执',STATUS]
SURFACE=dict(href='#device-transform',name='检测字段转换',audience='管理员、质量岗位',question=ROW[1],content='实际原列、字段声明、单位/日期/判定码、逐行转换与会话差异、模板沿革及私有原件完整性',action='核对格式及身份差异，启用私有配置，另存标准文件后人工核对关联',status=STATUS)
def refine_device_transform(d):
 for dom in d['domains']:
  for n in dom['items']:
   if n['id']=='W-21':assert n['implementation']==n['decision_spec']['implementation']=='模拟部分覆盖';n['gap']=STATUS
 for p in d['page_blueprints']:
  if p['id'] in ('P05','P06','P15'):p['status']=p['status'].split(' '+MARKER)[0]+' '+MARKER+STATUS
 f=d['framework'];f['presentation']=[r for r in f['presentation'] if r[0]!=ROW[0]]+[list(ROW)];f['surfaces']=[s for s in f['surfaces'] if s['href']!=SURFACE['href']]+[dict(SURFACE)];return d
def remove_exact_increment(d):
 for dom in d['domains']:
  for n in dom['items']:
   if n['id']=='W-21':assert n['gap']==STATUS;n['gap']=PRIOR
 for p in d['page_blueprints']:
  if p['id'] in ('P05','P06','P15'):
   suffix=' '+MARKER+STATUS;assert p['status'].endswith(suffix);p['status']=p['status'][:-len(suffix)]
 f=d['framework'];assert [r for r in f['presentation'] if r[0]==ROW[0]]==[ROW];f['presentation']=[r for r in f['presentation'] if r[0]!=ROW[0]]
 assert [s for s in f['surfaces'] if s['href']==SURFACE['href']]==[SURFACE];f['surfaces']=[s for s in f['surfaces'] if s['href']!=SURFACE['href']];return d
