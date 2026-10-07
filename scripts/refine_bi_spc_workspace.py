"""Add the verified personal SPC increment, preserving the prior coverage count."""
import copy
STATUS='受控试验视角增量：个人编码、显示条件、采样与规范定义有版本；独立快照固定全部观测、派生结果、Excel行身份和规则文本。支持当前资料核对、基线更正/计算依据变化分辨、完整CSV/JSON及按当前权限读取旧归档；专题只列本人关联内容，不采用通用专题日期或联动条件。使用合成试验，浏览器和手机交互待验收；不增加正式MSA、Cp/Cpk或业务批准能力。'
MARKER=' 个人受控试验视角说明：'
NEEDS=('L-06','L-13','X-07','X-08','X-10')
CONTRACT=dict(revision='spc-workspace-20261007',needs=list(NEEDS),href='#spc-workspace',state='已验证个人合成试验定义、冻结来源和当前资料核对',
 definitions='个人唯一编码、名称、试验、固定计划、规范、规则摘要、显示小数及公差开关、可选专题、版本与归档',
 snapshots='创建时全部观测和派生结果；独立原始Excel导入行ID、引用字段与规则文本；不可覆盖，仍按当前访问权读取',
 comparison='同一试验身份；定义变化不作同口径差值，基线更正保留两组控制限，新增/缺失不补零，变化不作因果判断',
 privacy='仅本人读取；专题关联不共享内容或改写共享专题布局，管理员也不能读取他人个人快照',
 restrictions='不支持团队共享、调度订阅、全库历史重放、其他控制图或真实MSA/过程能力；浏览器及手机待验收')
ROW=dict(name='我的受控试验工作簿',question='保存的分析依据和当时结果是什么；当前资料是否更正？',
 content='自定义视角编码、版本、完整试验冻结、历史源行、当前资料核对、CSV/JSON与个人专题关联',
 action='读取固定定义→冻结当时证据→核对当前资料→记录更正依据',href='#spc-workspace',status=STATUS)

def refine_workspace(d):
 for dom in d['domains']:
  for n in dom['items']:
   if n['id'] in NEEDS:n['gap']=n['gap'].split(MARKER)[0]+MARKER+STATUS
 for p in d['page_blueprints']:
  if p['id'] in ('P05','P15'):p['status']=p['status'].split(MARKER)[0]+MARKER+STATUS
 d['framework']['spc_workspace']=copy.deepcopy(CONTRACT)
 d['framework']['surfaces']=[r for r in d['framework']['surfaces'] if r['href']!=ROW['href']]+[copy.deepcopy(ROW)]
 return d

def remove_exact_workspace(d):
 assert d['framework']['spc_workspace']==CONTRACT
 assert [r for r in d['framework']['surfaces'] if r['href']==ROW['href']]==[ROW]
 d['framework'].pop('spc_workspace');d['framework']['surfaces']=[r for r in d['framework']['surfaces'] if r['href']!=ROW['href']]
 suffix=MARKER+STATUS
 for dom in d['domains']:
  for n in dom['items']:
   if n['id'] in NEEDS:assert n['gap'].endswith(suffix);n['gap']=n['gap'][:-len(suffix)]
 for p in d['page_blueprints']:
  if p['id'] in ('P05','P15'):assert p['status'].endswith(suffix);p['status']=p['status'][:-len(suffix)]
 return d
