"""Add the current-result export contract without promoting requirement coverage."""
import copy
MARKER=' 模型结果导出说明：';NEEDS=('X-09','X-10')
STATUS='个人口径卡可导出本次当前结果CSV/JSON：实际范围、固定条件、粒度、日期角色、业务截止、整范围主度量/单位/有效与缺失样本/分子分母、原登记和实际计算定义、指标与分组版本、全部分组及来源/计算摘要。普通分组超过页面1000组上限时沿用既有聚合和排序完整重算，先核对已查看前缀及比率/派生依据，再导出全部；透视保留空格与独立重算的行列/总计，散点保留未绘点及原因。600秒凭据校验本人、卡版本、全部资料、结果及现权限；更正/失权/过期需重跑。CSV文本防公式执行，数值不转成防护文本；每次成功文件响应留审计，失败不新增导出审计。没有新增业务事实或冻结结果；文件不新增原件/分享权限，已下载副本不能撤回。浏览器、手机及实际下载未验收。'
CONTRACT=dict(revision='private-model-current-result-export-20261007',needs=list(NEEDS),href='#model-cards',
 reading=['先按登记定义运行','查看实际范围、主结果与样本','选择本次结果CSV或JSON','核对全部分组、口径与摘要','资料变动后重新运行'],
 content='原登记与实际计算定义、实际范围/条件/粒度/日期角色/业务截止、当前整范围摘要、全部分组、单位契约、比率/分位与派生依据、指标/固定分组版本、来源及计算摘要；不嵌入有效范围凭据',
 completeness='完整导出全部普通分组；沿用既有聚合与排序并核对页面前缀，页面1000组上限不截断文件；透视格和边际独立保留、散点未绘点不删除',
 permission='600秒已查看结果凭据；当前本人卡、来源模型、指标、字段、资料与账号权限再次核查；不接受新增筛选或组选项；失败不降级范围',
 csv='UTF-8 BOM；缺失空单元格与数值零区分；保留完整数值；公式形态文本含前导空白加防护前缀，负数保持数值',
 boundary='当前结果文件不是服务器冻结快照或历史事实重放，不新增事实、批准、原件、团队共享或下载后撤回能力；成功文件响应有审计',state=STATUS)
ROW=['个人模型当前结果同范围导出','怎样带走刚查看的结果而不遗漏分组或改变口径？','从当前结果准备CSV/JSON；范围、主结果、全部分组、单位、版本和摘要同行，资料变化后重跑',STATUS]
def refine_exports(d):
 for group in d['domains']:
  for need in group['items']:
   if need['id'] in NEEDS:need['gap']=need['gap'].split(MARKER)[0]+MARKER+STATUS
 for page in d['page_blueprints']:
  if page['id']=='P15':page['status']=page['status'].split(MARKER)[0]+MARKER+STATUS
 d['framework']['model_result_export']=copy.deepcopy(CONTRACT)
 d['framework']['presentation']=[x for x in d['framework']['presentation'] if x[0]!=ROW[0]]+[copy.deepcopy(ROW)]
 return d
def remove_exact_exports(d):
 assert d['framework'].pop('model_result_export')==CONTRACT and [x for x in d['framework']['presentation'] if x[0]==ROW[0]]==[ROW]
 d['framework']['presentation']=[x for x in d['framework']['presentation'] if x[0]!=ROW[0]];suffix=MARKER+STATUS
 for group in d['domains']:
  for need in group['items']:
   if need['id'] in NEEDS:assert need['gap'].endswith(suffix);need['gap']=need['gap'][:-len(suffix)]
 for page in d['page_blueprints']:
  if page['id']=='P15':assert page['status'].endswith(suffix);page['status']=page['status'][:-len(suffix)]
 return d
