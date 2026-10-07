"""Named, reversible topic summary presentation increment; no KPI redefinition."""
MARKER='整范围摘要：'
STATUS='既有部门专题在分组图形上方展示所选度量的整范围摘要，按完整已授权且已筛选来源重算，不合计或平均分组显示值。比率展示分子/分母，去重数跨组去重，分位数使用完整样本，派生式保留单位换算；原模型、分组结果与已发布指标定义不变。来源未采集、范围为空、缺失样本、未知/混合单位和零分母分开说明；一侧不完整、定义/算法/单位不符或文本结果暂停差值，百分比差值用百分点。新增独立的同范围摘要CSV，图形分组上限不截断整范围摘要；摘要凭据核对范围、来源、算法和账号权限。新结果快照冻结摘要并核对保存来源，旧快照没有摘要时不补造历史数字。已发布指标的发布时间可保存为JSON，新客户端保存同时核对摘要凭据；旧申请兼容重算保存语义。37项新增检查与完整模拟副本核查通过；全库事实、已有模型/目标/快照、原文件和16个核心引擎未改。未形成跨卡合计、自动达标判断、因果解释、真实经营评审、U8/MES接入或浏览器/手机/实际下载验收。'
ROW=['专题所选度量整范围摘要','分组结果背后的整体数值是多少，当前与对照是否可比？','按整范围来源重算 → 显示单位/样本/分子分母 → 同定义描述性差值 → 来源和算法 → 摘要导出及个人快照',STATUS]
IDS={'X-07','X-09','X-10'}
def refine_card_summary(d):
 for dom in d['domains']:
  for n in dom['items']:
   if n['id'] in IDS:n['gap']=n['gap'].split('\n'+MARKER)[0]+'\n'+MARKER+STATUS
 for p in d['page_blueprints']:
  if p['id']=='P15':p['status']=p['status'].split(' '+MARKER)[0]+' '+MARKER+STATUS
 for s in d['framework']['surfaces']:
  if s['href']=='#topics':s['status']=s['status'].split(' '+MARKER)[0]+' '+MARKER+STATUS
 f=d['framework'];f['presentation']=[r for r in f['presentation'] if r[0]!=ROW[0]]+[list(ROW)]
 return d

def remove_exact_increment(d):
 for dom in d['domains']:
  for n in dom['items']:
   if n['id'] in IDS:
    suffix='\n'+MARKER+STATUS;assert n['gap'].endswith(suffix);n['gap']=n['gap'][:-len(suffix)]
 for p in d['page_blueprints']:
  if p['id']=='P15':
   suffix=' '+MARKER+STATUS;assert p['status'].endswith(suffix);p['status']=p['status'][:-len(suffix)]
 for s in d['framework']['surfaces']:
  if s['href']=='#topics':
   suffix=' '+MARKER+STATUS;assert s['status'].endswith(suffix);s['status']=s['status'][:-len(suffix)]
 f=d['framework'];assert [r for r in f['presentation'] if r[0]==ROW[0]]==[ROW];f['presentation']=[r for r in f['presentation'] if r[0]!=ROW[0]]
 return d
