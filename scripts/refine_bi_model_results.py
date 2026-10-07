"""An additive current-result reading contract; no coverage promotion."""
import copy
MARKER=' 模型结果阅读说明：';NEEDS=('X-09','X-10')
STATUS='个人模型当前结果新增实际范围/截止/粒度与筛选条件、整范围主度量及有效/缺失样本、柱图/折线/构成/表格/透视/散点、分页分组与当前权限内Excel来源。主度量从全部来源重算，不相加或平均分组；图形和1000组返回限制明确。来源凭据600秒绑定本人卡版本、全部资料、结果与规则/权限；数据、定义、卡版本或权限变化后需重跑；无新事实、结果快照、指标发布或业务动作。浏览器、手机及实际键盘操作仍待验收。'
CONTRACT=dict(revision='private-model-result-reading-20261007',needs=list(NEEDS),href='#model-cards',
 reading=['业务问题与实际范围','业务截止/日期角色/粒度/固定条件','整范围主度量与样本、分子分母','原配置图形与分组明细','所选分组/透视格/散点的来源','原Excel行或语义对象依据'],
 summary='沿用既有整范围摘要；从全部当前授权来源重算所选度量，保留缺失、零分母、无来源、空范围、分位方法和单位暂停',
 visuals='原模型六种图形：柱、折线、非负可加构成、表格、透视、散点；普通图前18组、构成前8组+其余；分组表每页25，API超1000组明确提示',
 evidence='全部范围、精确分组、透视行列及散点身份；每页30条，当前权限核查；原始表追到Excel文件/表/行，语义表显示实际来源对象',
 receipt='600秒绑定本人卡与版本、定义、全部来源、结果、规则和账号；陈旧或不明选择暂停，不回退全部范围',
 boundary='同定义当前资料阅读，不是历史重放；来源不新增导出/原件授权或业务审批；图形不自动判断目标、关系、因果或质量合格',state=STATUS)
ROW=['个人模型当前结果阅读','这个模型的主结果、分组和参与计算的来源如何对应？','范围与样本在主结果旁，技术JSON折叠；分组、透视格和散点可核对当前来源',STATUS]
def refine_results(d):
 for g in d['domains']:
  for n in g['items']:
   if n['id'] in NEEDS:n['gap']=n['gap'].split(MARKER)[0]+MARKER+STATUS
 for p in d['page_blueprints']:
  if p['id']=='P15':p['status']=p['status'].split(MARKER)[0]+MARKER+STATUS
 d['framework']['model_result_reading']=copy.deepcopy(CONTRACT);d['framework']['presentation']=[r for r in d['framework']['presentation'] if r[0]!=ROW[0]]+[copy.deepcopy(ROW)]
 return d
def remove_exact_results(d):
 assert d['framework'].pop('model_result_reading')==CONTRACT and [r for r in d['framework']['presentation'] if r[0]==ROW[0]]==[ROW]
 d['framework']['presentation']=[r for r in d['framework']['presentation'] if r[0]!=ROW[0]];suffix=MARKER+STATUS
 for g in d['domains']:
  for n in g['items']:
   if n['id'] in NEEDS:assert n['gap'].endswith(suffix);n['gap']=n['gap'][:-len(suffix)]
 for p in d['page_blueprints']:
  if p['id']=='P15':assert p['status'].endswith(suffix);p['status']=p['status'][:-len(suffix)]
 return d
