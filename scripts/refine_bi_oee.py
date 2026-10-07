"""Add a verified synthetic OEE surface and clarify the unpublished K18 proposal."""
import copy
from collections import Counter
MARKER=' 班次效率补充：'
STATUS='独立资源位合成采集已提供计划窗口、停止并集、配置理想节拍和首次产出互斥分类，10例123行正常Excel导入；单配置A/P/Q与OEE、损失时间守恒、混配置理想良品时间占比、窗口明细、来源及CSV/JSON。缺节拍、未确认、未闭合、重叠、未来实绩与无窗口暂停；零产出与零分母分开。真实节拍、完整设备采集、全厂汇总、实时连接、浏览器、手机和实际下载未验收；未发布K18或改变质量判定。'
CONTRACT=dict(revision='bi-oee-20261007',definition='在已闭合采集、容量1独立资源位、同配置同单位窗口内，OEE衡量首次良品理想加工时间占计划生产时间的比例，并分别解释可动、速度和首次质量损失。',reading=['明确资源及计划生产窗口','核对闭合、节拍、首次分类和截止','读取主结果与损失时间','按配置窗口展开','核对停机区段与全部报产行','追到Excel及版本','由设备/生产/质量核查后同口径复查'],formula='单配置：A=运行/计划；P=理想节拍×首次经过/运行；Q=首次良品/首次经过；OEE=首次良品×理想节拍/计划。',mixed='每配置窗口分别计算；混配置合计为Σ(首次良品×本配置理想节拍)/Σ计划生产时间，标为理想良品时间占比。不同单位数量不相加，总体A/P/Q不混乘，OEE不简单平均。',time='窗口左闭右开；相邻窗口不重叠，未计划生产时段从分母排除。停止与窗口取交集并集，窗口内换型属于停止。报产登记允许窗口末点但仅靠窗口号归属，不推定单台加工时刻。',zero='闭合且明确声明零报产时，可计算良品时间占比0；零产量Q未定义，零运行P未定义。没有窗口或缺记录不能填零。',visuals='范围与资料状态；1至3主结果；四段损失时间带；配置窗口A/P/Q/OEE表；首次经过/良品/返工/报废/未确认分类；重叠停止时间线；计划外片段；窗口直接依据与全方案Excel；复查下一步。',sources='第38份模拟Excel，5输入表、10独立案例、123行；引用原产品配置与独立资源位，原设备停机、产量、良率及工单未被改写。',permission='六类岗位可读公开效率采集；不显示资源位员工档案参考或产品价格。来源链接仍单独校验原件权限，完整导出带当前范围、规则、来源和摘要，不带活动读取凭据。',state=STATUS,boundary='全部记录为独立合成输入，不代表全设备/全厂实际OEE，不设任意基准目标，速度残差不证明具体因果；无真实采集接口、派工、维修执行或质量批准。',references=['https://www.oee.com/calculating-oee/','https://www.oee.com/oee-factors/'])
OLD_METRIC={'formula':'可用率=运行时间/计划生产时间；性能率=Σ(各配置总产量×理想节拍)/运行时间；质量率=首次良品数/总产量；同一可比范围三者相乘','grain':'设备×配置/可比运行段','source':'设备状态、有效日历、理想节拍、产量及首次良品','pitfalls':'先按配置/可比运行段算，再明确加权汇总口径；全厂OEE不简单平均；性能>100%排查标准，不静默封顶；换型按冻结规则','implementation':'需补充数据或计算能力'}
ROW=dict(name='班次设备效率',question='哪些计划生产时间用于停止、速度残差、首次非良品和首次良品，输入能否闭合？',content=CONTRACT['visuals'],action='窗口和来源核对后，由设备/生产/质量处理并按同口径复查',href='#oee',status=STATUS)
def refine_oee(d):
 for g in d['domains']:
  for n in g['items']:
   if n['id']=='O-05':n['implementation']='模拟部分覆盖';n['decision_spec']['implementation']='模拟部分覆盖';n['gap']=n['gap'].split(MARKER)[0]+MARKER+STATUS
 for p in d['page_blueprints']:
  if p['id']=='P10':p['status']=p['status'].split(MARKER)[0]+MARKER+STATUS
 for m in d['metrics']:
  if m['id']=='K18':m.update(formula=CONTRACT['formula']+' '+CONTRACT['mixed'],grain='容量1独立资源位×配置×计划生产窗口',source='闭合采集、计划窗口、停止区间、配置理想节拍、首次产出分类',pitfalls='首次良品不含返工后合格；停止交集并集不重复；混配置合计必须标明时间口径；性能>100%暂停核对；零分母未定义；节拍和来源未获真实批准。',implementation='独立合成班次模拟部分覆盖，未发布正式指标')
 d['framework']['oee_trial']=copy.deepcopy(CONTRACT);d['framework']['surfaces']=[r for r in d['framework']['surfaces'] if r['href']!='#oee']+[copy.deepcopy(ROW)];d['planning_summary']['implementation_counts']=dict(Counter(n['implementation'] for g in d['domains'] for n in g['items']));return d
def remove_oee(d):
 d['framework'].pop('oee_trial',None);d['framework']['surfaces']=[r for r in d['framework']['surfaces'] if r['href']!='#oee']
 for g in d['domains']:
  for n in g['items']:
   if n['id']=='O-05':n['implementation']='待建设';n['decision_spec']['implementation']='待建设';n['gap']=n['gap'].split(MARKER)[0]
 for p in d['page_blueprints']:
  if p['id']=='P10':p['status']=p['status'].split(MARKER)[0]
 for m in d['metrics']:
  if m['id']=='K18':m.update(OLD_METRIC)
 d['planning_summary']['implementation_counts']={'模拟部分覆盖':117,'待建设':265};return d
def reading_text(d):
 c=d['framework']['oee_trial'];return ['班次设备效率的BI定义与呈现','',c['definition'],'阅读顺序：'+' → '.join(c['reading']),'口径：'+c['formula'],'混配置：'+c['mixed'],'时间：'+c['time'],'零和缺失：'+c['zero'],'展示：'+c['visuals'],'来源：'+c['sources'],'权限与导出：'+c['permission'],'当前范围：'+c['state'],'边界：'+c['boundary'],'方法参考：'+'；'.join(c['references'])]
