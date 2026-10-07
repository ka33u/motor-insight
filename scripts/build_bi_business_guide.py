"""Current business-readable requirements and presentation, without a web server."""
import json,shutil
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 d=json.loads((ROOT/'data/bi_design.json').read_text());needs=[n for g in d['domains'] for n in g['items']];counts=Counter(n['implementation'] for n in needs)
 lines=['电机制造企业 · BI深化方案（业务阅读版，2026-10-07）','',
 '工厂前提：用友U8、momo MES准备上线（供应商与接口待核实）；约900台/日，全流程自制，品种复杂、小批量定制，预算谨慎、IT人手不足。',
 f'候选库：26领域、{len(needs)}项需求、63项建议指标、17页蓝图、18类方法。当前{counts["模拟部分覆盖"]}项模拟部分覆盖、{counts["待建设"]}项待建设。候选清单可扩展、可裁剪，不能穷尽未来全部需求；部分覆盖不代表真实上线验收。',
 '当前业务数据均为自编Excel导入的合成演示；真实ERP/MES未接入。',
 '', '一、BI怎么定义',
 'BI把来源事实、统一指标口径、分析比较、异常对象、证据和复查组织成可使用的决策信息。每项内容必须回答：谁看？为了决定什么？看哪个对象？按什么日期及截止？来源与算法是什么？下一步做什么？',
 '定义分六层：业务需求→事实与维度→指标→分析模型→专题页面→处理与复查。',
 '指标需写明编码、业务问题、对象粒度、公式/分子分母、单位、日期角色/截止、纳入排除、缺失与不可加性、来源关系、适用维度、责任与版本。',
 '模型需写明使用的方法、配置/规范/单位可比门槛、固定条件与临时范围、样本及解释边界；页面需写明读者、节奏、主结果、解释、对象、来源、导航及复查。',
 '指标/模型版本、页面版本、数据状态、结果快照分别保存。个人说明不会改变计算公式，旧布局不会冻结历史结果。',
 '', '二、信息怎样呈现',
 '统一阅读顺序：范围与可信度→1—3项主结果→解释与可比性→异常或待处理对象→来源及版本→责任与复查。',
 '经营首页：少量已核实结果、趋势、偏差、跨部门协调对象及刷新时间。',
 '岗位工作台：以对象清单为中心，列身份、影响、阻断、下一节点、依据、责任及复查；责任/时限需实际记录支持。',
 '专题分析：趋势、结构/帕累托、分布、透视、关系、同类比较与情景；选中分组追到同范围对象和Excel行。',
 '对象履历：订单、工单、批次、SN、设备、物料等搜索；时间线、确认关系、版本及证据断点。',
 '车间大屏：当班少量结果、关键阻断与更新时间。手机：单对象查询、关键状态、证据和下一节点；独立布局尚待实施验收。',
 '导出/打印：与页面保持筛选、日期角色、截止、单位、分母/样本和权限；分页或图形截取不改变整范围统计。',
 '有证据才设红黄绿；未采集、未知、无权限、无适用规范、空范围、异常或暂停分别显示，不能统一填零或显示正常。',
 '', '三、低预算先围绕五个决定建设',
 '1. 哪些订单不能按期足量交付，缺在哪个工序、材料或证据？',
 '2. 计划能否执行，资源、合格人员、未来窗口与换型有没有冲突？',
 '3. 哪些电机/批次需要质量复查，检测是否齐项且有原件关联？',
 '4. 哪些采购/库存/批次无法支持计划，数量、状态和单位是否可勾稽？',
 '5. 哪些页面目前可信，Excel/纸质/设备文件的缺口由谁补？',
 '先统一订单行—工单—批次—SN身份、主数据与模板，核对日期、单位、版本和来源；业务部门负责口径及资料，IT复用通用采集/编排/查询，不为每张报表重建一套逻辑。',
 '', '四、17页蓝图与阅读任务']
 for page in d['page_blueprints']:
  lines.extend(['',page['id']+' '+page['name'],'读者：'+page['reader'],'问题：'+page['question'],'首屏：'+'｜'.join(page['cards']),'解释：'+page['visual'],'对象：'+page['detail'],'路径：'+page['drill'],'行动：'+page['decision'],'前提：'+page['gate']])
 lines.extend(['','五、26领域、382项候选需求（全部编号保留）'])
 for g in d['domains']:
  lines.extend(['',g['code']+' '+g['name']+'｜'+str(len(g['items']))+'项'])
  for n in g['items']:
   lines.extend([n['id']+' · '+n['need']+'｜'+n['priority']+'｜'+n['implementation'],'问题与规则：'+n['definition'],'来源/粒度：'+n['source']+'；'+n['grain'],'呈现：'+n['view'],'下一步：'+n['action'],'责任与前提：'+n['owner']+'；'+n['prerequisite'],'适用性：'+n['applicability'],'尚缺：'+n['gap']])
 lines.extend(['','六、63项口径建议（实际发布逐项确认）'])
 for m in d['metrics']:
  lines.extend(['',m['id']+' '+m['name'],'公式：'+m['formula'],'粒度/日期：'+m['grain']+'；'+m['clock'],'来源/责任：'+m['source']+'；'+m['owner'],'解释边界：'+m['pitfalls'],'状态：'+m['implementation']])
 lines.extend(['','七、个人专题页面的呈现增量',d['framework']['topic_page_composition']['state'],
 '交付示例：PAGE.DELIVERY.DAILY.0001，demo_analyst本人，当前页面v2、v1保留，沿用DELIVERY_OTIF v8。',
 '质量示例：PAGE.QUALITY.DAILY.0001，demo_admin本人，页面v1，整机/首检/会话/处置四种对象与日期分别展示。',
 '版本只保存阅读布局，结果快照另存；完整导航不兼容即暂停，另可明确开始新范围。',
 '', '八、当前验证与仍需验收',
 '个人专题页面前轮完整回归2,378项通过；班次设备效率当前检查结果见随包的独立验证记录。',
 '所有旧事实、原件、旧模型/专题、目标、发布指标及个人口径卡按独立保留检查核对；新配置采用预览与追加版本服务。',
 '浏览器实际渲染、手机、键盘与下载未验收；真实U8/MES接口、正式生产规范与业务批准仍待核实。',
 '网页打不开时直接读本TXT或《BI完整382项需求清单.txt》；离线HTML内含样式脚本，不需要启动平台服务。',
 '《BI个人专题页面编排说明_20261007.txt》说明页面入口与版本边界。设计ZIP不含数据库/凭据；应用恢复包独立保存。'])
 if d['framework'].get('topic_journey'):
  c=d['framework']['topic_journey'];lines.extend(['','跨专题探索增量',c['state'],c['boundary']])
 if d['framework'].get('oee_trial'):
  from refine_bi_oee import reading_text
  lines.extend(['','九、班次设备效率新增实例',*reading_text(d),'','完整单配置合成案例：计划420分钟，停止60分钟，运行360分钟；首次经过160台、首次良品150台、需返工6台、报废4台。理想节拍假设90秒每台。OEE=150×90÷(420×60)=53.5714%；四段损失为停止60分钟、速度残差120分钟、首次非良品理想时间15分钟、首次良品理想时间225分钟。数字仅用于预演。','呈现时先看闭合与同类范围，再看1—3个主结果和四段时间，点窗口看原始数量及停止，并追到Excel。不给混配置总性能/总质量率，也不以85%等通用宣传数值作本厂目标。'])
 out=ROOT/'outputs/BI深化方案_业务阅读版_20261007.txt';out.write_text('\n'.join(lines)+'\n');shutil.copyfile(out,ROOT/'docs/BI深化方案_业务阅读版.txt');print(str(out))
if __name__=='__main__':main()
