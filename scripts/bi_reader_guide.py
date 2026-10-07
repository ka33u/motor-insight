"""Business-first entry to the existing exhaustive candidate design catalog."""
REVISION='bi-reader-guide-20261006'


def build_reader_guide(d):
    return dict(
        revision=REVISION,
        definition='BI是把业务事实转换为统一口径、可比较结果和可追溯证据，并按岗位组织成可处理、可复查的分析服务。它同时包含数据模型、指标定义、分析方法、页面和协作规则。',
        factory_focus='对小批量定制电机工厂，分析主线是订单行→工单→定转子批次/装配件包→单台SN→检测→发运。配置、工艺和试验规范版本决定哪些对象能够比较。',
        decision_chain=['明确决定与责任岗位','确认来源、编码和关系','定义粒度、单位和日期','定义指标及分析方法','选择页面与下钻','核对原始证据','处理问题并按同一范围复查'],
        first_questions=[
            dict(question='哪些订单可能不能按期交付？',page_id='P02',needs=['C-01','C-02'],content='原承诺与当前承诺、未交数量、影响对象、阻断节点和责任',action='逐单核对承诺及阻断，再组织计划、采购和质量协调'),
            dict(question='工单缺什么，批次停在哪里？',page_id='P03',needs=['F-03','G-02'],content='开工条件、物料竞争、在制位置与份额、资源和试验队列',action='明确补料或资源安排；自然停留与实际工时分开'),
            dict(question='哪些单台漏检、首检失败或尚无放行依据？',page_id='P05',needs=['M-01','M-02'],content='应检集合、覆盖、首检/复检、适用规范、原文件和原结论',action='定位SN与项目，交由质量岗位补证和处理'),
            dict(question='一台电机用了哪些批次，证据能否完整对应？',page_id='P06',needs=['N-01','N-03'],content='确认关系、身份断点、版本、批次影响及原始文件',action='补齐真实关系；候选影响与确认影响分别复核'),
            dict(question='这张表是否足够可信，哪些资料还缺？',page_id='P15',needs=['W-04','W-15'],content='来源更新时间、缺失、重复、未关联、单位和版本冲突',action='按来源及数据责任人形成补录或核查清单'),
        ],
        primary_metrics=[
            ['交付结果','K01','必须确定按原始还是当前承诺，以及订单行、发运或签收日期；取消和部分交付有明确规则'],
            ['质量结果','K04','从首次完整适用检测计算；复检另列，不用复测替换首次失败'],
            ['质量护栏','K03','应检对象和必检项目由计划及适用规范确认；无记录不能算合格'],
        ],
        budget_rule='先用交付、质量试验、对象追溯和数据可信度四类页面形成闭环；计划/在制作为交付解释入口。成本与现金等来源核实后逐步加入。不把382项需求一次性排成开发任务。',
        domain_index=[dict(code=x['code'],name=x['name'],count=len(x['items']),examples=' / '.join(n['need'] for n in x['items'][:3])) for x in d['domains']],
        definition_rules=[
            ['需求','岗位、使用时机、问题、决定、责任人；没有后续决定的内容可先不建'],
            ['事实与维度','一行的业务对象、主键、单位、关联基数、日期角色、配置和版本；一对多连接避免放大数量'],
            ['指标','公式、分子分母、粒度、时间、排除规则、聚合、缺失、来源、更新频率、责任与版本'],
            ['分析模型','同类比较、趋势、结构、分布、透视、关系、追溯及情景；样本量与可比边界随结果展示'],
            ['专题','围绕一个问题组织主结果、解释、对象、证据和行动；每页主结果通常1—3项'],
            ['发布与复查','样例核对→业务评审→受控发布→变更记录；数据快照、指标版本和页面版本分别保存'],
        ],
        display_rules=[
            ['经营总览','少量已核实结果、趋势、偏差及跨部门协调入口'],
            ['岗位工作台','优先显示异常对象清单、影响、责任、下一节点；可用数据决定是否显示时限'],
            ['专题分析','配置与规范筛选、可比样本、趋势/帕累托/分布/透视，点击进入对象和来源'],
            ['对象履历','订单/工单/批次/SN搜索，时间线、版本、确认关系和证据断点'],
            ['手机','查号或扫码后显示单个对象、少量关键状态、证据及下一节点'],
            ['车间大屏','本班进度、关键阻断及更新时间；深入调查回到工作台'],
        ],
        innovations=[
            ['配置可比视图','先核对产品配置、规范、单位和工况，再允许比较；混合总体与同类总体分别呈现'],
            ['从异常到订单影响','异常工序、批次或检测可反查已确认SN和订单；未知关系单列'],
            ['数字变化说明','保留范围、口径、数据和权限版本，让使用者区分业务变化、补录和定义变化'],
            ['双时间阅读','区分事情何时发生和资料何时登记；只对具备版本依据的来源开放历史重述'],
            ['数据缺口工作台','缺字段、未关联、未读原件作为需处理对象展示；数据不足不填零或自动显示正常'],
            ['情景比较','共同基线下比较插单、批量、日期或资源假设；试算不自动改变正式计划'],
        ],
        boundary='这是可裁剪、可扩展的候选需求库，不能穷尽未来需求；具体功能以逐项实施状态和验证证据为准。所有当前业务记录为模拟数据。上述设计不代表真实U8/MES已接入、指标已全部发布、手机或浏览器交互已验收。',
    )


def reader_guide_text(d):
    g=d['framework']['presentation_design']['reading_guide']
    metric={m['id']:m for m in d['metrics']}
    lines=['电机制造企业：BI定义与呈现方案 · 快速阅读版',g['revision'],'',g['definition'],g['factory_focus'],
        '范围：26领域、382项候选需求、63项建议指标、17页蓝图；逐项正文见《BI完整382项需求清单.txt》。',
        '', '一、BI从问题到复查',' → '.join(g['decision_chain']),'', '二、先围绕五个问题建设']
    for x in g['first_questions']:
        lines.extend(['',x['question']+'｜'+x['page_id'],'首屏：'+x['content'],'处理：'+x['action']])
    lines.extend(['',g['budget_rule'],'','三、经营首页先选两项结果、一项护栏'])
    for label,key,note in g['primary_metrics']:
        m=metric[key]
        lines.extend(['',label+'：'+key+' '+m['name'],'建议计算：'+m['formula'],'时间与粒度：'+m['clock']+'；'+m['grain'],'需确认：'+note])
    lines.extend(['','没有真实可比历史前不设凭空的红黄绿目标；实测基线、管理目标和试算假设分开。',
        '', '四、26个领域全景索引（示例非完整条目）'])
    lines.extend(x['code']+' '+x['name']+'｜'+str(x['count'])+'项｜例如：'+x['examples'] for x in g['domain_index'])
    for title,key in [('五、定义哪些对象','definition_rules'),('六、怎样呈现','display_rules'),('七、值得预留的创新方向','innovations')]:
        lines.extend(['',title]);lines.extend('｜'.join(x) for x in g[key])
    lines.extend(['','统一页面顺序：范围与可信度 → 主结果 → 解释与可比性 → 异常对象 → 来源及版本 → 责任与复查。',
        '完整定义、全部需求及页面阅读路径见《BI展示内容与交互设计_完善版.txt》及《BI完整382项需求清单.txt》。',
        '',g['boundary']])
    if d['framework'].get('method_workshop'):
        from refine_bi_methods import method_reading_note
        lines.extend(['',method_reading_note()])
    if d['framework'].get('model_cards'):
        c=d['framework']['model_cards']
        lines.extend(['','八、分析模型的业务口径与版本','模型口径卡登记“为什么看、看谁、怎么解释”，再绑定实际分析定义。',c['objects'],c['presentation'],c['boundaries'],c['privacy'],c['time'],'演示入口 #model-cards；操作见《BI个人模型口径卡说明_20261007.txt》。'])
    if d['framework'].get('model_result_reading'):
        c=d['framework']['model_result_reading']
        lines.extend(['','九、从模型口径直接读当前结果',' → '.join(c['reading']),c['summary'],c['visuals'],c['evidence'],c['receipt'],c['boundary'],'操作与验收边界见《BI模型结果阅读与来源说明_20261007.txt》。'])
    if d['framework'].get('model_result_export'):
        c=d['framework']['model_result_export']
        lines.extend(['','十、带同一口径导出本次当前结果',' → '.join(c['reading']),c['content'],c['completeness'],c['permission'],c['csv'],c['boundary'],'操作与验收边界见《BI模型当前结果导出说明_20261007.txt》。'])
    if d['framework'].get('finite_schedule_trial'):
        c=d['framework']['finite_schedule_trial']
        lines.extend(['','十一、生产计划怎样做有限资源试排',' → '.join(c['reading']),c['definition'],c['measures'],c['method'],c['visuals'],c['boundary'],'模拟输入、结果与验收边界见《BI有限资源试排说明_20261007.txt》。'])
    if d['framework'].get('crew_schedule_trial'):
        c=d['framework']['crew_schedule_trial']
        lines.extend(['','十二、设备可用但合格人员不可用时，BI怎样说明',' → '.join(c['reading']),c['definition'],c['measures'],c['method'],c['visuals'],c['boundary'],'模拟输入、结果与验收边界见《BI资源人员联立试排说明_20261007.txt》。'])
    if d['framework'].get('topic_page_composition'):
        c=d['framework']['topic_page_composition']
        lines.extend(['','十三、按业务问题编排自己的工作页',' → '.join(c['reading']),c['definition'],c['layout'],c['navigation'],c['versions'],c['permission'],c['boundary'],'操作及验收边界见《BI个人专题页面编排说明_20261007.txt》。'])
    if d['framework'].get('oee_trial'):
        from refine_bi_oee import reading_text
        lines.extend(['','十四、按配置和独立资源位解释设备效率',*reading_text(d)])
    return lines
