"""A concise, source-derived entry to the comprehensive BI design catalog."""
from collections import Counter
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LENSES=[
 ('经营与客户','能接什么订单，承诺如何兑现，客户问题如何反馈？','ABCU'),
 ('研发与制造','用什么配置与工艺，怎样安排和完成生产？','DEFGH'),
 ('供应与物料','什么时候有可用物料，库存与外部协同是否可靠？','IJKV'),
 ('质量与能力','证据是否齐全，人机工装是否合格且可用？','LMNOPQ'),
 ('价值与保障','利润、现金、能源安环和投资是否有依据？','RSTZ'),
 ('数据与分析','数据能否相信，定义能否复用，判断能否复查？','WXY'),
]
DEFINITIONS=[
 ['业务问题','谁在何时，对哪个对象作什么决定？','REQ.C-04：哪些订单需要协调交期？'],
 ['业务对象','保留原始编号，建立主键、别名和有效关系。','订单行→工单→定转子批次→SN→检测会话'],
 ['事实模型','一行的粒度、事件日期、状态时点、关联基数。','一条发货行与一个SN分别建事实，防止连接后重复计数'],
 ['维度','分类/层级/版本、生效期、未知组及允许筛选。','产品族→配置；车间→工序→资源位；客户→订单行'],
 ['指标','公式、单位、分子分母、纳入排除、日期和聚合。','K01交付率按计划行计数，汇总后重新计算比率'],
 ['分析模型','方法、样本、可比条件、参数、解释边界。','趋势、贡献、分布、透视、关系、追溯、约束试算'],
 ['专题与页面','一个决定对应一组结果、解释、对象和证据。','P02交付专题；经营首页仅展示其中的关键结果'],
 ['处理与复查','对象、依据、责任、期限、状态、结果及复核。','BI记录协调，正式放行、改期和派工走授权流程'],
 ['发布','定义版本、数据截止、结果快照、权限和变更影响。','页面布局版本与指标算法版本分别保存'],
]
PAGE_LAYERS=[
 ['范围','岗位、期间/日期角色、截止、配置、来源新鲜度。','所有卡片声明适用筛选；不适用时直接提示'],
 ['结果','1—3个主要结果，带单位、分母/样本、目标依据。','无基线时先看趋势，不自行设置目标或红黄绿'],
 ['解释','趋势、贡献、分布、比较条件和未知资料。','结构变化、数据更正与经营变化分别解释'],
 ['对象','订单/工单/批次/SN、差距、阻断、影响和下一节点。','汇总点击后进入同范围对象，保留排序和返回上下文'],
 ['证据','有效版本、完整明细、Excel文件/工作表/行、原件。','未关联与无权读取分别展示，候选关联不冒充确认关系'],
 ['复查','责任、措施、期限、审批入口、结果及复核。','异常关闭需有证据；建议与实际执行分别留痕'],
]
FORMATS=[
 ['经营总览','总经理日看异常、周月复盘','目标条＋趋势＋跨部门异常摘要'],
 ['岗位工作台','计划/质量/采购/仓库每天处理对象','优先对象清单＋阻断矩阵＋下一节点'],
 ['专题探索','工艺、工程师与分析人员查差异','帕累托、分布、散点、透视、同类对照'],
 ['对象履历','查一单、一台、一批、一项原件','关系树＋时间线＋版本和证据断点'],
 ['资源时间视图','生产、设备、人事核对时段约束','甘特＋负荷热图＋资格/停机/窗口'],
 ['对账与数据缺口','财务、仓储、数据责任人核验','数量/金额桥＋差异队列＋来源依赖'],
 ['现场手机与大屏','手机查单扫码；大屏看当班阻断','手机单对象单列；大屏少量大字与更新时间'],
 ['例会、导出与情景','记录共同范围、假设、决定和事后结果','冻结快照、受控报表、共同基线方案对照'],
]
FACTORY_RULES=[
 ['配置可比','机座、功率、极数、电压、频率、工作制、安装、防护、绝缘、效率及冷却；再核对BOM/路线/规范版本。'],
 ['制造粒度','冲片卷料与模次、铁芯/转子批次、绕组、浸漆固化批次、装配SN、终检会话分别统计；拆合批有数量份额。'],
 ['任务可比','定制复杂度、批量、换型、路线、返工和授权标准工时；不能仅用每天台数评价所有班组。'],
 ['检测可比','特性、方法、单位、负载点、环境、仪器及规范版本；首测失败与复测通过并列。'],
 ['业务时间','下单、承诺、发货、签收、装配、检测、记账、结账、登记和生效日期不混用；迟到资料可重述。'],
 ['可信状态','已知零、未采集、未关联、部分覆盖、冲突、过期、无权限和无适用规范分别呈现。'],
]
INNOVATIONS=[
 ['交付条件地图','订单行横向展示物料、资料、人员/设备、工序、检测、放行与发货条件；点击阻断反查依据。'],
 ['对象优先阅读','先查订单、SN或批次，再展开相关指标；同一证据服务多个部门。'],
 ['可比性说明','在比较图旁直接写明配置、工况和规范差异；小批新产品保留逐件值与样本量。'],
 ['数字变化解释','并列数据更正、定义调整、结构变化、权限变化与事实事件，避免把重算误作改善。'],
 ['证据缺口队列','订单/检测/设备文件未关联进入可核对队列；补齐责任和成本可见。'],
 ['共同基线试算','同一截止与输入下比较插单、批量、资源与未来到料；假设有来源，不自动下达。'],
]

def refine_reading(d):
    needs=[n for domain in d['domains'] for n in domain['items']]
    counts=dict(Counter(n['implementation'] for n in needs))
    d['planning_summary']['implementation_counts']=counts
    d['planning_summary']['presentation_design']['coverage_counts']=counts.copy()
    d['framework']['decision_reading']={
        'revision':'bi-decision-reading-20261007',
        'definition':'BI是把分散的业务事实，按统一身份和口径组织成指标、分析、对象证据与复查，帮助各岗位持续作出有依据的决定的一套数据服务。',
        'positioning':'本厂以订单交付和单台电机履历为主线，统一配置、工序、材料、人机工装、检测、成本与现金的关联。',
        'lenses':[dict(name=a,question=b,domains=list(c)) for a,b,c in LENSES],
        'definition_fields':DEFINITIONS,'page_layers':PAGE_LAYERS,'formats':FORMATS,
        'factory_rules':FACTORY_RULES,'innovations':INNOVATIONS,
        'first_pages':['P02','P05','P06','P15'],
        'model_patterns':['趋势与期间比较','构成与贡献分解','帕累托与重点对象','直方图/箱线/分位数','同条件样本对照','透视与层级下钻','相关关系探索','谱系与影响反查','状态/数量/金额对账','时间与约束试算','过程稳定性适用评估','预测及辅助问数（后续）'],
        'template':'目的与读者→对象粒度→来源与关系→日期/截止→指标与聚合→比较条件→呈现/交互→权限→处理/复查→验收/版本',
        'scope':'覆盖现有全部候选的阅读入口；需求库可扩展，不代表一次建设全部项目。定义和展示为设计建议，当前业务记录全部为模拟。',
    }
    return d

def render_reading(d,table,section):
    b=d['framework'].get('decision_reading')
    if not b:return ''
    h=html.escape
    domains={v['code']:v for v in d['domains']}
    groups=[[g['name'],g['question'],'；'.join(domains[c]['name'] for c in g['domains'])] for g in b['lenses']]
    return section('decision-reading','先读这一页：BI的定义与展示',
        '<blockquote>'+h(b['definition'])+'</blockquote><p>'+h(b['positioning'])+'</p>'
        +'<h3>从六类决定找到全部需求</h3>'+table(['决策','问题','覆盖领域'],groups)
        +'<h3>九类可复用定义</h3>'+table(['定义对象','写清什么','示例'],b['definition_fields'])
        +'<h3>同一页按六层阅读</h3>'+table(['层次','展示内容','交互规则'],b['page_layers'])
        +'<h3>按岗位选择呈现方式</h3>'+table(['入口','使用场景','推荐呈现'],b['formats'])
        +'<h3>本厂的比较条件</h3>'+table(['条件','核对内容'],b['factory_rules'])
        +'<p>首期页面：P02交付、P05质量、P06履历、P15数据可信度；之后按痛点启用计划、物料、设备人员、成本资金等专题。</p>'
        +'<p>'+h(b['scope'])+'</p>')

def export_text(d):
    b=d['framework']['decision_reading'];domains={g['code']:g for g in d['domains']}
    needs=[i for g in d['domains'] for i in g['items']]
    out=ROOT/'outputs';out.mkdir(exist_ok=True)
    lines=['MotorInsight · BI决策与展示阅读指南','2026-10-07；设计建议；所有业务记录为合成演示。','',b['definition'],b['positioning'],'',
           '一、全部需求如何找：六类决定覆盖26个领域']
    for g in b['lenses']:
        lines.extend(['',g['name']+'：'+g['question']])
        for code in g['domains']:
            v=domains[code];lines.append(f'{code} {v["name"]}（{len(v["items"])}项）：'+'；'.join(i['need'] for i in v['items']))
    for title,key in [('二、BI定义对象与编码','definition_fields'),('三、一页怎样呈现','page_layers'),('四、不同岗位和终端','formats'),('五、定制电机比较条件','factory_rules'),('六、创新设计候选','innovations')]:
        lines.extend(['',title]);lines.extend('｜'.join(r) for r in b[key])
    lines.extend(['','七、分析模型库','；'.join(b['model_patterns']),'','八、每项需求的定义模板',b['template'],'','九、首期页面'])
    for p in d['page_blueprints']:
        if p['id'] in b['first_pages']:lines.extend([p['id']+' '+p['name']+'：'+p['question'],'首屏：'+'；'.join(p['cards']),'来源前提：'+p['gate'],'处理：'+p['decision']])
    lines.extend(['','十、63项建议指标（公式原样来自当前目录；待业务审定）'])
    for m in d['metrics']:lines.extend([m['id']+' '+m['name'],'公式：'+m['formula'],'粒度：'+m['grain']+'；时间：'+m['clock'],'来源：'+m['source']+'；注意：'+m['pitfalls']])
    lines.extend(['','十一、17页完整蓝图'])
    for p in d['page_blueprints']:lines.extend([p['id']+' '+p['name']+'｜'+p['reader'],'问题：'+p['question'],'呈现：'+p['visual'],'对象：'+p['detail'],'下钻：'+p['drill'],'处理：'+p['decision'],'前提：'+p['gate']])
    lines.extend(['',b['scope'],'参考：少量重点结果、独立事实/维度模型、同范围钻取借鉴下列官方文档；工厂业务定义和创新设计由本项目制定。',
                  'https://learn.microsoft.com/en-us/power-bi/create-reports/service-dashboards-design-tips',
                  'https://learn.microsoft.com/en-us/power-bi/guidance/star-schema',
                  'https://www.metabase.com/docs/latest/dashboards/interactive'])
    text='\n'.join(lines)+'\n';(out/'BI决策与展示_阅读指南.txt').write_text(text);(ROOT/'docs/BI决策与展示_阅读指南.txt').write_text(text)
    index=['MotorInsight · 全部BI候选需求简明索引',f'{len(d["domains"])}领域，{len(needs)}项；原编号、实施状态与优先级保留。','模拟部分覆盖不代表完整上线或真实数据就绪；其余详细定义见当前BI方案。','']
    for domain in d['domains']:
        index.extend(['',domain['code']+' '+domain['name']])
        for n in domain['items']:index.extend([n['id']+' '+n['need']+'｜'+n['priority']+'｜'+n['implementation'],'判断：'+n['definition'],'呈现：'+n['view']+'；处理：'+n['action'],'前提：'+n['prerequisite']])
    (out/'BI需求全景_简明索引.txt').write_text('\n'.join(index)+'\n')

if __name__=='__main__':
    path=ROOT/'data/bi_design.json';d=refine_reading(json.loads(path.read_text()));path.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');export_text(d)
