"""One explicit MSA pilot; inherited asset grain is replaced by trial grain."""
import copy
from msa_requirement_before import BASE_NEED
from refine_bi_spc import counts
MARKER=' 测量试验增量说明：'
STATUS='第35份模拟Excel新增11个试验、141个显式成员、930条重复观测。完成交叉单元核对、保留交互的随机效应ANOVA、原始负方差保留及呈现值截零、方差/研究变异/公差占用分开、全部观测CSV与逐行Excel来源。4个完整试验可试算，7个异常试验暂停；不删重复、不补缺测、不自动换单位。真实工况、代表性、随机独立性、MSA资格、置信区间、偏倚/线性/稳定性、嵌套及破坏性分析仍待建设；不作合格判定，不改终检/SPC或发布指标。浏览器、手机与实际下载未验收。'
CONTRACT=dict(revision='msa-crossed-trial-20261007',needs=['P-06'],href='#msa',rule_version='MSA-CROSSED-FULL-TRIAL.01',
 raw_datasets=['msa_studies','msa_members','msa_observations'],studies=11,members=141,observations=930,
 grain='试验×样件成员×操作员成员×重复轮次；实际登记序号、原读数与单位独立保存',
 source='独立试验方案＋样件/SN与操作员工号声明＋逐次重复读数＋规范版本＋仪器/校准登记',
 figures='采样完整性矩阵、分类计数、类别交互均值及全部读数、分开的方差/研究变异百分比、ANOVA/方差分量详表、逐点来源',
 constraints='只支持平衡交叉连续量随机效应全交互模型；不按P值合并交互，不生成合格阈值、ndc、Cp/Cpk或真实证书结论',
 evidence='源行身份、资料/规则摘要、截止和账号绑定；凭据600秒，资料变化后重新读取；图形和导出使用完整试验',
 status=STATUS)
ROW=dict(name='测量系统交叉采样',question='重复测量数据是否完整，重复性、人员和交互变异各有多少？',content=CONTRACT['figures'],
 action='确认采样计划→核对全部交叉单元→检查适用条件→复算与追查来源→设计真实试验',href='#msa',status=STATUS)
def refined_need():
 n=copy.deepcopy(BASE_NEED);n.update(implementation='模拟部分覆盖',gap=BASE_NEED['gap']+MARKER+STATUS,verified_trial=copy.deepcopy(CONTRACT),
  source=CONTRACT['source'],grain=CONTRACT['grain'],readiness='已导入合成独立试验；真实采样及资格待审定',
  prerequisite='先确认样件代表性、操作员范围、可重复测量与模型；声明同单位/方法、规范和校准时间窗口，完整交叉采样并保留重复/缺测',
  frequency='每次独立试验；按试验开始/结束及登记截止读取',dimensions='试验、产品配置、特性/单位、样件/SN、操作员工号、重复轮次、方法与方案版本、仪器及所引校准登记',
  acceptance='对照独立采样计划抽查全部样件×操作员×重复轮次；核对平方和、自由度与方差估计，区分三类百分比，验证缺测/重复/单位/零变异暂停；逐点追到原Excel行，翻页与全量CSV同范围；真实试验和资格须另行审定')
 dims=['试验','配置','特性/单位','样件/SN','操作员','重复轮次','方法版本','仪器/校准登记']
 time='固定试验开始/结束与业务截止；登记时间可核对，不使用通用交易日期筛选'
 evidence=n['grain']+' → 原测量读数与成员声明 → 方案/规范/校准版本 → Excel行与归档原件'
 n['display_design'].update(dimensions=dims,object_and_evidence=evidence,date_contract=time,availability='前提未满足时保留全部读数及缺口，不删行或补零生成平衡结果')
 n['decision_spec'].update(object_grain=n['grain'],evidence_source=n['source'],time=time,data_gate=n['prerequisite'],acceptance=n['acceptance'],implementation=n['implementation'])
 n['presentation_contract'].update(object_grain=n['grain'],dimensions=dims,data_gate=n['prerequisite'],evidence=evidence,validation=n['acceptance'],mobile_task='候选手机任务：查试验、样件、操作员与采样轮次；移动交互待验收')
 n['delivery_proposal'].update(first_scope='先独立定义采样计划、成员与重复观测，核对模型及时间适用；合成试算后再设计真实试验',evidence_to_verify=n['prerequisite'],acceptance_task=n['acceptance'])
 return n
def refine_msa(d):
 for g in d['domains']:
  for i,n in enumerate(g['items']):
   if n['id']=='P-06':g['items'][i]=refined_need()
 for p in d['page_blueprints']:
  if p['id'] in ('P05','P10'):p['status']=p['status'].split(MARKER)[0]+MARKER+STATUS
 d['framework']['msa_trial']=copy.deepcopy(CONTRACT);d['framework']['surfaces']=[s for s in d['framework']['surfaces'] if s['href']!='#msa']+[copy.deepcopy(ROW)];counts(d);return d
def remove_exact_msa(d):
 assert d['framework']['msa_trial']==CONTRACT and [s for s in d['framework']['surfaces'] if s['href']=='#msa']==[ROW]
 d['framework'].pop('msa_trial');d['framework']['surfaces']=[s for s in d['framework']['surfaces'] if s['href']!='#msa']
 for g in d['domains']:
  for i,n in enumerate(g['items']):
   if n['id']=='P-06':assert n==refined_need();g['items'][i]=copy.deepcopy(BASE_NEED)
 for p in d['page_blueprints']:
  if p['id'] in ('P05','P10'):
   suffix=MARKER+STATUS;assert p['status'].endswith(suffix);p['status']=p['status'][:-len(suffix)]
 counts(d);return d
