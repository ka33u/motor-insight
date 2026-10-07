"""Reversible partial coverage of synthetic file-discovery declarations."""
from collections import Counter
MARKER='设备文件清单：'
STATUS='新增设备来源、扫描批次与文件发现三类标准Excel来源；本地设备目录与待采集页面按声明截止查看当前扫描或全部历史，区分无扫描、未执行、失败、未完整、完整空扫描及完整有文件。文件记录保留读取状态、指纹、字节数、修改/发现时间、格式、会话和SN线索；同内容多次发现与声明唯一内容分开统计，缺指纹不参与去重。按当前账号本人私有原件核对实际字节与元数据，已归档结构化/人工核对/解析异常分开；会话线索进入现有原件工作台逐项核对，文件名不决定订单归属。支持来源/批次/状态/关键词/截止、每页25条、完整同范围CSV、Excel行来源及扫描历史；权限、声明或原件内容变化需重新读取。12模拟来源、17扫描登记、196发现记录经正常导入演练，无设备PC自动访问或后台采集代理、真实采集回执、设备登录信息管理、自动文件稳定性检测、解析转换与重试队列。所有记录均为合成数据；来源登记不能证明真实设备覆盖完整。原有命名模板绑定全目录契约，已用原模拟样例通过原生API重新表头核对并启用v2；v1内容与历史保留，仅启用状态被新版本替代，不放宽校验规则，无真实业务审批。U8/MES、浏览器/手机/实际下载未验收。'
ROW=['设备文件发现与待采集','哪些设备资料尚未发现、未归档或无法对应检测对象？','来源覆盖 → 当前或历史扫描 → 文件队列 → 本人归档内容核对 → 会话线索与Excel来源 → 原件工作台',STATUS]
SURFACE=dict(href='#device-intake',name='设备目录与待采集',audience='数据负责人、管理员、质量岗位',question=ROW[1],content='来源覆盖、扫描结论、文件读取与归档状态、指纹去重、会话线索及Excel来源',action='核对目录声明，补充文件清单，到原件工作台逐项核对会话',status=STATUS)
def counts(d):
 c=dict(Counter(n['implementation'] for dom in d['domains'] for n in dom['items']));d['planning_summary']['implementation_counts']=c;d['planning_summary']['presentation_design']['coverage_counts']=c
def refine_device_intake(d):
 for dom in d['domains']:
  for n in dom['items']:
   if n['id']=='W-21':n['implementation']=n['decision_spec']['implementation']='模拟部分覆盖';n['gap']=STATUS
 for p in d['page_blueprints']:
  if p['id']=='P15':p['status']=p['status'].split(' '+MARKER)[0]+' '+MARKER+STATUS
 f=d['framework'];f['presentation']=[r for r in f['presentation'] if r[0]!=ROW[0]]+[list(ROW)];f['surfaces']=[s for s in f['surfaces'] if s['href']!=SURFACE['href']]+[dict(SURFACE)];counts(d);return d
def remove_exact_increment(d):
 for dom in d['domains']:
  for n in dom['items']:
   if n['id']=='W-21':
    assert n['gap']==STATUS and n['implementation']==n['decision_spec']['implementation']=='模拟部分覆盖'
    n['implementation']=n['decision_spec']['implementation']='待建设';n['gap']='新增候选设计，尚未完成采集、计算、页面或业务验收。'
 for p in d['page_blueprints']:
  if p['id']=='P15':
   suffix=' '+MARKER+STATUS;assert p['status'].endswith(suffix);p['status']=p['status'][:-len(suffix)]
 f=d['framework'];assert [r for r in f['presentation'] if r[0]==ROW[0]]==[ROW];f['presentation']=[r for r in f['presentation'] if r[0]!=ROW[0]]
 assert [s for s in f['surfaces'] if s['href']==SURFACE['href']]==[SURFACE];f['surfaces']=[s for s in f['surfaces'] if s['href']!=SURFACE['href']];counts(d);return d
