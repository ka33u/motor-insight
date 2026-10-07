"""Append only the validated overview-observation scope to the existing catalog."""
from collections import Counter
MARKER='首页观察：'
STATUS='本地首页提供经营、生产、质量、财务和业务阅读5种关注点，按6个账号岗位设默认入口，首屏3项原有总览指标，其他指标展开查看；关注点不扩大权限，也不改变六项首页v1口径或已发布指标。9类观察支持产品族/类别/状态/等级/岗位/搜索、服务端每页30条、同范围完整CSV、对象专题、文件/工作表/行号和逐条历史。检测与放行观察复用质量页有效证据规则；工具校准明确全厂范围，观察条数与不同对象数分开，跟进期限按当前日期。15分钟范围核对、版本比较及操作编号重放保护跟进写入，旧无版本处置入口已停用；跟进不是业务批准，岗位文字不自动分派账号。隔离完整副本生成686观察/607对象，所有页与完整CSV编号一致，跟进重放、旧范围拒绝、来源及协同中心回链通过；42项新增边界检查通过。主库43张表、212466事实、442个既有文件和16个核心计算文件未改。仅覆盖交付与质量等已登记观察；现金影响、统一事件去重、全厂风险分级/金额、预算目标、效果复查及自动通知仍待建设。真实岗位适用性、U8/MES、浏览器、手机和实际下载尚未验收。'
ROW=['首页关注点与同范围观察','首页数字怎样进入同产品族的对象、证据与跟进？','关注点只调整阅读优先级；业务截止/跟进日期、观察/对象数分开，9类观察按服务端同范围分页和导出，版本核对后登记跟进，再恢复产品族与类别定位当前对象',STATUS]
IDS={'A-02','X-09'}

def refine_issue_workspace(d):
 for dom in d['domains']:
  for n in dom['items']:
   if n['id'] in IDS:n['gap']=n['gap'].split('\n'+MARKER)[0]+'\n'+MARKER+STATUS
   if n['id']=='A-02':n['implementation']=n['decision_spec']['implementation']='模拟部分覆盖'
 for p in d['page_blueprints']:
  if p['id']=='P01':p['status']=p['status'].split(' '+MARKER)[0]+' '+MARKER+STATUS
 for s in d['framework']['surfaces']:
  if s['href'] in ['#overview','#issues']:s['status']=s['status'].split(' '+MARKER)[0]+' '+MARKER+STATUS
 f=d['framework'];f['presentation']=[r for r in f['presentation'] if r[0]!=ROW[0]]+[list(ROW)]
 d['planning_summary']['implementation_counts']=dict(Counter(n['implementation'] for dom in d['domains'] for n in dom['items']))
 return d

def remove_exact_increment(d):
 for dom in d['domains']:
  for n in dom['items']:
   if n['id'] in IDS:
    suffix='\n'+MARKER+STATUS;assert n['gap'].endswith(suffix);n['gap']=n['gap'][:-len(suffix)]
   if n['id']=='A-02':
    assert n['implementation']==n['decision_spec']['implementation']=='模拟部分覆盖';n['implementation']=n['decision_spec']['implementation']='待建设'
 for p in d['page_blueprints']:
  if p['id']=='P01':
   suffix=' '+MARKER+STATUS;assert p['status'].endswith(suffix);p['status']=p['status'][:-len(suffix)]
 for s in d['framework']['surfaces']:
  if s['href'] in ['#overview','#issues']:
   suffix=' '+MARKER+STATUS;assert s['status'].endswith(suffix);s['status']=s['status'][:-len(suffix)]
 f=d['framework'];assert f['presentation_design']['scope']==NEW_SCOPE;f['presentation_design']['scope']=OLD_SCOPE
 assert [r for r in f['presentation'] if r[0]==ROW[0]]==[ROW];f['presentation']=[r for r in f['presentation'] if r[0]!=ROW[0]]
 counts=dict(Counter(n['implementation'] for dom in d['domains'] for n in dom['items']));d['planning_summary']['implementation_counts']=counts
 if 'presentation_design' in d['planning_summary']:d['planning_summary']['presentation_design']['coverage_counts']=counts
 return d

OLD_SCOPE='保留全部382项候选；每项增加展示交互契约，17页增加阅读任务。需求库可持续扩展，不能保证穷尽未来业务。未改现有63项口径、计算模型或模拟覆盖状态。'
NEW_SCOPE='保留全部382项候选；每项增加展示交互契约，17页增加阅读任务。需求库可持续扩展，不能保证穷尽未来业务。63项建议口径与已有计算模型保留；当前首页观察增量只将A-02新增标为模拟部分覆盖，其他覆盖状态保留，不代表该需求已完整验收。'
def finalize_issue_workspace(d):
 assert d['framework']['presentation_design']['scope'] in (OLD_SCOPE,NEW_SCOPE)
 d['framework']['presentation_design']['scope']=NEW_SCOPE
 return d
