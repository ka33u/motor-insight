"""Additive BI method-selection contracts; never calculate or certify a model.

Each assignment is a proposal for review. Existing requirements, metrics,
implementation labels and published business definitions remain unchanged.
"""
import copy


def method(code, name, question, inputs, algorithm, view, gate, stop, example):
    return dict(id=code, name=name, question=question, inputs=inputs.split('；'),
                algorithm=algorithm, view=view, gate=gate, stop=stop,
                example_need_ids=example.split('/'),
                status='分析选型与呈现建议；不是已上线算法或已审定业务口径')


METHODS = [
    method('QUEUE', '截止队列与优先事项', '现在应该先处理哪些对象？',
           '唯一业务对象；有效状态事件；约定期限与时区；责任与处理依据',
           '按统一截止重建互斥状态；已知未完成与资料未知分别计数；影响与到期分别排序，不编造综合评分。',
           '3个状态摘要＋期限分布＋条件矩阵＋对象表',
           '完整的应有对象集合和生效状态；截止型结果保留截止时点。',
           '无事件历史不能倒推历史状态；没有期限不称逾期。', 'C-02/M-01/W-02'),
    method('TREND', '趋势与可比期间', '变化发生在何时、是否持续？',
           '事件时间与登记时间；完整业务日历；期间完整度；稳定指标版本',
           '按固定业务日期归期；空记录、真实零、未覆盖三种情况分开；同比环比只用完整且可比期间。',
           '折线与缺失断点＋样本/覆盖条＋变更标记',
           '先明确事件量、余额、到期队列属于哪类时间口径。',
           '五天资料不能填满年度曲线；余额不跨日求和。', 'A-03/G-03/T-01'),
    method('TARGET', '目标与偏差', '结果偏离了哪个已确定目标？',
           '目标对象与版本；上下限或方向；目标期间；同范围实际与依赖版本',
           '同范围比较实际和目标；比例从分子分母重算；总目标不自动按销量分给部门或配置。',
           '实际/目标条＋偏差排序＋版本与覆盖',
           '确认目标来源、批准责任、单位和是否允许提前预警。',
           '无目标显示待设定；假设目标明确标注试算，不生成正式绩效灯色。', 'A-01/A-07/X-20'),
    method('BRIDGE', '差异桥与结构分解', '差额来自量、价、结构还是核算变化？',
           '两侧完整范围；同税价币种单位；成本/价格基准；分解次序和交互项',
           '固定分解顺序并显式保留交互项和未解释差额；各部分与总差额勾稽。',
           '瀑布桥＋配置结构对照＋差额明细',
           '真实收入和成本按同一结账版本核对，估算与实际分列。',
           '分解不是因果证明；没有分摊依据不能把共享费用精确摊到SN。', 'A-09/R-02/T-14'),
    method('FLOW', '流转、等待与资源', '工单或批次卡在哪里，影响哪个订单？',
           '流转事件和位置；拆合批份额；投入产出单位；资源日历及有效占用',
           '按部件层次和单位核对投入、耗用、在制、返工、报废；自然等待与实际作业时长分别汇总。',
           '工序状态矩阵＋位置/等待分布＋资源时间轴',
           '定子、转子、整机分别计量；合箱保留各工单份额。',
           '没有事件不能把计划任务当在制；资源高负荷不直接判定系统瓶颈。', 'G-02/G-09/F-02'),
    method('TRACE', '对象履历与影响反查', '对象从哪里来、还影响谁？',
           '稳定身份；关系依据与有效期；拆换沿革；原件指纹和授权',
           '只沿有证据的关系连接；唯一SN去重；确认影响、候选影响、断点分别呈现。',
           '对象时间线＋有效关系树＋影响清单＋证据抽屉',
           '查号从内部ID映射到显示编码，原件权限独立核验。',
           '名称、时间接近和文件名均不能自动证明订单关联。', 'N-01/N-03/N-12'),
    method('DIST', '同配置分布与裕量', '数值集中在哪里，哪些观测接近规范边界？',
           '配置和规范版本；特性数值与标准单位；会话及复测身份；方法与工况',
           '先按SN选择约定会话，再按方法/设备筛选；从有效原始值重算分位数，展示排除及样本数。',
           '直方图/箱线＋规范限值＋温度/设备分层＋样本表',
           '同配置、特性、规范、单位与方法；首次事件、首次完整及最新结果分别命名。',
           '分布不证明稳定；不同单位和复测择优不能混合；二值项目用计数。', 'M-03/M-09/M-15'),
    method('SPC', '过程稳定性与控制图', '固定过程中的波动是否出现需调查信号？',
           '可核验采样序号或唯一时间；同配置工序特性及测量条件；子组策略；固定基线与规则版本',
           '先确定单值、合理子组或计数模型。单值I图的候选界限为均值±3×平均移动极差/1.128；移动极差须来自真正相邻观测。基线固定，不随筛选重拟合。',
           '基线/监控分区＋I与MR双图＋规则信号＋变更事件＋原观测',
           '测量系统及采样方案核实；同刻无采样顺序、缺失、换型、失准及自相关须先处理。',
           '控制限和产品公差分开；序号不是SN字典排序或Excel行序；有信号是调查线索，无信号不等于稳定已获确认。', 'L-06/L-13/H-01'),
    method('CAPABILITY', '过程能力适用性', '经核实稳定的过程对规范有多大余量？',
           '已核实稳定性；有效规范限值；测量系统证据；独立样本与分布假设及估计方法',
           '双侧规范的Cp=(USL−LSL)/(6σ)，Cpk取两侧标准化余量较小者；声明σ估计依据、期间及不确定性。单侧规范另定，不能虚造另一侧。',
           '适用性门槛＋规范/分布＋估计值及区间＋样本证据',
           '过程、测量和抽样条件确认后才估计；样本方案由质量岗位审定。',
           '无稳定性或分布依据不显示正式Cp/Cpk；不凭统计指数自动放行。', 'L-06/L-13'),
    method('MSA', '测量系统与检验一致性', '差异来自产品、仪器、方法还是判定者？',
           '预设重复测量方案；样件与操作者；仪器/方法版本；随机化和重复次序',
           '按重复性、再现性、偏倚/线性/稳定性或属性一致性选择方案；校准证书与MSA结论分开。',
           '样件×人员×重复矩阵＋变异分解/一致性表＋方案原件',
           '有计划的重复实验与适用公差；普通生产复测不能自动充当GRR研究。',
           '校准有效不等于测量系统能力已验证；无研究方案只显示缺证。', 'P-06/M-13/L-11'),
    method('RELATION', '关联线索与验证假设', '材料或工况差异是否与结果一起变化？',
           '可靠对象关系；双方可比单位；配置、批量与工况；缺失/排除及样本',
           '先分层看散点和分布；记录候选解释、替代解释及需补的验证，不从相关性直接推断原因。',
           '分层散点＋组内样本＋反例＋验证任务',
           '双方有唯一配对或经批准的汇总粒度，不做任意多对多拼接。',
           '记录时间相近不能替代批次关联；没有共同条件不作绩效排名。', 'K-09/U-02/Q-09'),
    method('COHORT', '队列成熟度与可靠性', '不同出厂批次在可比观察期内表现怎样？',
           '有效出厂/质保起算；观察截止；已失效与仍在观察；返修替换关系',
           '按同起点和暴露年龄比较；未成熟与失访分列，必要时采用经审定的删失分析。',
           '队列×观察龄期矩阵＋暴露样本＋故障/失访清单',
           '同配置和使用环境；质保起算及重复故障计数规则核实。',
           '未报修不自动等于无故障；新批次不能直接与多年老批次比失效率。', 'U-03/U-07/U-11'),
    method('RECONCILE', '数量金额与双来源勾稽', '哪一笔差额无法解释，需要谁补证？',
           '两侧对象键；有效截止与单位；核销/撤销记录；差额允许规则',
           '一对多先按事实键汇总；匹配、差额、缺另一侧、未执行分别列出；允许差额有规则版本。',
           '对账通过/未知摘要＋差异矩阵＋两侧记录和原件',
           '采购/入库/发票、库存/实物等各有独立口径与截止。',
           '没有执行对账不算通过；不把库存件数、公斤和金额直接相加。', 'S-04/J-04/W-07'),
    method('FORECAST', '预测与回测', '在有历史证据时，未来区间怎样估计？',
           '足够且可比历史；预测时点可用字段；训练验证切分；基准方法与回测误差',
           '保留滚动时点预测，和简单基准在相同窗口比较；预测区间、覆盖和模型漂移一起呈现。',
           '实际/历史预测对照＋区间带＋误差分层＋失效情形',
           '没有历史或预测时点可用特征时仅作条件假设，不称预测。',
           '五天模拟资料不支持真实需求或交期预测；未来结果不能泄漏到特征。', 'B-06/B-10/C-04'),
    method('SCENARIO', '假设情景与方案对照', '在同一基线下改变条件会怎样？',
           '冻结基线；参数和适用范围；明确约束；收益成本及未知项',
           '只改变声明参数；显示差值、假设、不可行条件与未覆盖内容；实际和试算分开。',
           '参数面板＋方案并排＋差异桥＋约束清单',
           '来源能支持模型关系，假设有版本和责任；不确定因素用范围表达。',
           '试算不自动改计划、报价或执行；缺约束时不宣称可执行或最优。', 'F-06/S-05/R-12'),
    method('OPTIMIZE', '有限资源方案优化', '给定目标和约束，哪些安排值得业务确认？',
           '资源/人员日历；路线先后；物料/换型；目标及罚则；求解边界',
           '先检验可行性，再按声明目标比较；给出求解状态、时间限制、未安排对象和人工覆盖。',
           '基准与方案时间轴＋资源冲突＋目标差异＋未排清单',
           '真实产能和任务约束标定；目标权重由计划与经营确认。',
           '未证明最优只称候选方案；合成900台/日不是工厂产能标定。', 'F-07/F-12/V-07'),
    method('CURVE', '曲线与过程区段', '设备曲线是否覆盖所需负载点或工艺区段？',
           '会话/批次；通道单位与采样时间；完整点序；规范及配方版本',
           '保留原采样间隔及缺失，不用插值掩盖缺点；对齐依据、区段和限值各有版本。',
           '原始曲线＋规范区段＋缺点标识＋同对象来源',
           '文件可解析且通道、订单/SN/炉批关联经过确认。',
           '一条终值不能生成整段温度曲线；不同负载/温度条件不直接叠图排名。', 'H-27/M-11/M-16'),
    method('PARETO', '缺陷与损失结构', '哪类问题影响范围大，先验证哪项改善？',
           '去重问题事件；缺陷分类版本；涉及SN及重复项；量或损失的归属',
           '问题次数、受影响去重SN和损失金额分别计算；互斥分类才做累计贡献。',
           '降序条形＋累计贡献（适用时）＋对象及分类未决项',
           '明确一机多缺陷和同问题重复登记规则，不直接相加当总台数。',
           '没有成本证据不把次数当经济损失；未知原因单列。', 'L-02/O-02/U-05'),
]

DOMAIN_METHODS = {
    'A': ['TARGET', 'BRIDGE'], 'B': ['QUEUE', 'BRIDGE'], 'C': ['QUEUE', 'FLOW'],
    'D': ['QUEUE', 'RECONCILE'], 'E': ['RECONCILE', 'TRACE'], 'F': ['FLOW', 'SCENARIO'],
    'G': ['FLOW', 'TRACE'], 'H': ['DIST', 'FLOW'], 'I': ['QUEUE', 'RECONCILE'],
    'J': ['QUEUE', 'RECONCILE'], 'K': ['DIST', 'TRACE'], 'L': ['PARETO', 'DIST'],
    'M': ['DIST', 'TRACE'], 'N': ['TRACE', 'RECONCILE'], 'O': ['FLOW', 'PARETO'],
    'P': ['QUEUE', 'TRACE'], 'Q': ['FLOW', 'DIST'], 'R': ['BRIDGE', 'RECONCILE'],
    'S': ['RECONCILE', 'QUEUE'], 'T': ['TREND', 'BRIDGE'], 'U': ['QUEUE', 'COHORT'],
    'V': ['FLOW', 'RECONCILE'], 'W': ['RECONCILE', 'QUEUE'], 'X': ['RECONCILE', 'TREND'],
    'Y': ['TARGET', 'SCENARIO'], 'Z': ['TREND', 'SCENARIO'],
}

KEYWORDS = [
    (('SPC', '稳定性'), ['SPC', 'CAPABILITY']),
    (('测量系统', '判定一致性'), ['MSA']),
    (('预测',), ['FORECAST']), (('情景', '模拟', '方案'), ['SCENARIO']),
    (('排程', '排产', '资源冲突', '拼批'), ['OPTIMIZE']),
    (('曲线', '温度过程', '负载点'), ['CURVE']),
    (('裕量', '分布', '特性'), ['DIST']), (('失效率', '质保起算'), ['COHORT']),
    (('目标', '预算'), ['TARGET']), (('趋势', '变化', '同环比'), ['TREND']),
    (('关联', '履历', '追溯', '影响反查'), ['TRACE']),
    (('差异', '分解', '毛利', '盈利'), ['BRIDGE']),
    (('勾稽', '对账', '核对', '守恒'), ['RECONCILE']),
]

PAGE_METHODS = {
    'P01': ['TARGET', 'BRIDGE'], 'P02': ['QUEUE', 'FLOW'],
    'P03': ['FLOW', 'OPTIMIZE'], 'P04': ['FLOW', 'DIST', 'PARETO'],
    'P05': ['DIST', 'SPC', 'CAPABILITY', 'MSA'], 'P06': ['TRACE'],
    'P07': ['RECONCILE', 'TRACE'], 'P08': ['QUEUE', 'RECONCILE'],
    'P09': ['RECONCILE', 'QUEUE'], 'P10': ['FLOW', 'MSA'],
    'P11': ['BRIDGE', 'SCENARIO'], 'P12': ['RECONCILE', 'QUEUE'],
    'P13': ['TREND', 'BRIDGE', 'CURVE'], 'P14': ['COHORT', 'RELATION'],
    'P15': ['RECONCILE', 'TREND'], 'P16': ['SCENARIO', 'FORECAST', 'OPTIMIZE'],
    'P17': ['QUEUE', 'BRIDGE'],
}


def refine_methods(d):
    """Idempotent addition; do not upgrade implementation or definition versions."""
    d['framework']['method_workshop'] = dict(
        revision='bi-method-workshop-20261007',
        definition='BI是一套按岗位提供决策支持的数据服务：把业务事实、统一指标、分析方法、来源证据和处理复查组织在一起。页面是使用入口，口径和模型是可复用定义。',
        scope='18类方法是选型建议。全部382项仍是候选需求，63项指标与17页保留；方法推荐不表示算法已实现、字段已齐、口径已批准或需求已验收。',
        methods=copy.deepcopy(METHODS),
        readiness=[
            dict(id='OBJECT', name='对象与应有范围', check='一行是什么；有哪些对象应被纳入；唯一键与关系依据是否完整', stop='对象或关联未知时，展示待核对清单，不虚分订单数量。'),
            dict(id='MEASURE', name='数值、单位与测量', check='原值、标准值、换算、仪器、方法、工况和有效版本是否一致', stop='混合单位/方法暂停合并；缺项不补零。'),
            dict(id='TIME', name='时间与真实顺序', check='事件、登记、截止、目标期间、采样顺序及迟到修订各指什么', stop='缺事件历史不能回放；同刻无顺序不能自行生成移动极差。'),
            dict(id='POPULATION', name='抽样、复测与可比性', check='首检、首次完整、最新、全部会话如何选；配置、批量与环境能否比较', stop='筛设备后不能将复测重称首检；选择偏差与排除数量显式显示。'),
            dict(id='METHOD', name='模型假设与基线', check='算法适用条件、独立性、基线、规则、训练/回测及不确定性是否有依据', stop='描述性资料只支持描述；稳定性、能力、预测及优化分别核实。'),
            dict(id='USE', name='责任与复查', check='谁读、何时用、下一步怎样查证、谁维护、怎样验收', stop='无使用者与维护责任先保留候选；分析建议不自动执行业务批准。'),
        ],
        screen=dict(
            header='业务问题｜对象粒度｜日期角色/截止｜配置/版本｜权限｜最后成功更新',
            result='1—3个主结果；数量带单位，比率带分子分母，未知与已知零分列',
            explain='一幅主解释图，比较条件、样本及缺失同时显示；模型条件未满足展示缺证',
            objects='同范围完整对象表，先影响/期限，再身份/状态/责任；分页不改变统计',
            evidence='数字→有效原观测/事件→关系依据→Excel工作表/行→获授权原件',
            action='协调与执行分别标记；记录责任、期限、依据及效果复查，返回保留上下文'),
        innovation=[
            ['方法门槛先行', '选择“分布/控制/能力”后立即看采样顺序、测量条件和基线缺口，再决定是否计算。'],
            ['一项需求多种阅读', '经营层看结果、岗位看对象队列、分析骨干看可比组；复用同一指标及事实身份。'],
            ['数字与证据并排', '显示计算范围、分母、排除、未知及版本；鼠标/键盘均可进入来源。'],
            ['决策效果复查', '冻结当时范围与决定，后续区分实际改善、补录和定义变化；不把点击率当经营收益。'],
        ],
        sample=dict(classification='合成Excel资料的冻结预检样例；不代表工厂实测',
                    business_cutoff='2026-10-01T18:00:00', product_id='CP.00008.A',
                    spec_id='JC-CP.00008.A-R-A', equipment_id='SB-08-01',
                    sample='每台首次完整检测；先选择会话，再筛规范与设备',
                    cohort_units=100, observations=68, outside=3,
                    excluded_equipment=29, excluded_no_session=3,
                    tied_observations=29, tied_timestamps=12,
                    unit='Ω', lsl=0.3036, usl=0.3424,
                    mean=0.3256764705882353, median=0.3252,
                    allowed='可展示同配置描述性分布及原始观测；3条超限为所选项目读数，不是新增报废或放行结论。',
                    paused='I-MR控制限暂停：29条观测共享12个时间值且没有可核验先后；Cp/Cpk另需稳定性、测量系统及分布/抽样依据。',
                    evidence_file='data/bi_method_readiness_sample.json',
                    note='这份样例是截至固定业务时间的定义预演，页面不即时重算；当前变化须重新预检并保留新版本。'),
        references=[
            dict(title='Microsoft：BI内容规划与维护', url='https://learn.microsoft.com/en-us/power-bi/guidance/powerbi-implementation-planning-content-lifecycle-management-plan-design'),
            dict(title='Microsoft：事实、维度与粒度', url='https://learn.microsoft.com/en-us/power-bi/guidance/star-schema'),
            dict(title='NIST：单值控制图', url='https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc322.htm'),
            dict(title='NIST：过程能力适用性', url='https://www.itl.nist.gov/div898/handbook/pmc/section1/pmc16.htm'),
        ],
    )
    for dom in d['domains']:
        for need in dom['items']:
            selected=[m['id'] for m in METHODS if need['id'] in m['example_need_ids']]
            for words, ids in KEYWORDS:
                if any(word in need['need'] for word in words):
                    selected.extend(ids)
            selected.extend(DOMAIN_METHODS[dom['code']])
            need['analysis_methods']=list(dict.fromkeys(selected))
            need['analysis_method_note']='基于明确实例、需求题目及所属业务领域的候选选型；逐项复核适用性，不自动生成公式、关联或实施状态。'
    for page in d['page_blueprints']:
        page['analysis_methods']=PAGE_METHODS[page['id']].copy()
    return d


def workshop_text(d):
    f=d['framework']['method_workshop'];names={m['id']:m['name'] for m in f['methods']}
    lines=['电机制造企业：BI分析方法、页面预演与数据门槛', f['revision'], '', f['definition'], f['scope'],
           '适用：U8、momo MES待上线；约900台/日、全流程自制、小批量定制；预算和IT人员有限。',
           '首批建议：订单交付P02、质量试验P05、对象履历P06、数据可信P15。先核对真实样本，再逐部门扩展。',
           '一期不以凑齐382项为目标；需求先按适用、来源、决策价值和维护负担评审。', '', '一、六项数据门槛']
    lines += [x['name']+'｜核实：'+x['check']+'｜不足时：'+x['stop'] for x in f['readiness']]
    lines += ['', '二、18类分析怎样定义和呈现']
    for m in f['methods']:
        lines += ['', m['id']+' '+m['name'], '问题：'+m['question'], '必需资料：'+'；'.join(m['inputs']),
                  '算法/定义：'+m['algorithm'], '呈现：'+m['view'], '进入条件：'+m['gate'],
                  '暂停与边界：'+m['stop'], '需求示例：'+'/'.join(m['example_need_ids']), m['status']]
    lines += ['', '三、17页的阅读和下钻预演']
    for p in d['page_blueprints']:
        focus=p['content_focus'];metric={m['id']:m['name'] for m in d['metrics']}
        lines += ['', p['id']+' '+p['name']+'｜'+p['reader'], '问题：'+p['question'],
                  '方法候选：'+' / '.join(names[i] for i in p['analysis_methods']),
                  '主结果：'+' / '.join(metric[i] for i in focus['result_metric_ids']),
                  '解释：'+p['visual'], '对象：'+p['detail'], '路径：'+p['drill'],
                  '决定：'+p['decision'], '门槛：'+p['gate'],
                  '手机：'+p['reading_contract']['mobile_task'], '无数据：'+p['reading_contract']['empty_state']]
    lines += ['', '四、一个来源可核对的SPC前置预演']
    s=f['sample'];lines += [s['classification'],
        '截至'+s['business_cutoff']+'；配置'+s['product_id']+'；规范'+s['spec_id']+'；设备'+s['equipment_id'],
        '100台装配队列 → 3台无所选会话 → 29台因设备排除 → 68条有效观测；各项相加核对100。',
        '所选绕组电阻：均值0.3256764706Ω、中位数0.3252Ω；模拟规范0.3036—0.3424Ω，3条项目读数超限。',
        '不是首检失败率：样本是首次完整检测，可能发生在复测；规范及设备筛选不重新挑选会话。',
        s['allowed'], s['paused'], s['note'], '完整样本及编号证据：'+s['evidence_file'],
        '页面预演：范围及时间 → 100/68及排除 → 描述性分布 → 序号缺证清单 → 待补字段 → 重新预检；控制限和Cp/Cpk区域显示暂停原因。',
        '需补字段：设备采样序号、源时间精度/时区、采样方案和方法、同工况及测量系统证据、固定基线与规则版本。',
        '', '五、自定义BI对象的实现约束',
        '业务对象/维度：稳定ID、文本编码、别名、层级、生效关系；一对多预聚合，多对多明确分配依据。',
        '指标：公式/分子分母、粒度、单位、日期角色、适用/排除、依赖版本、缺失及发布责任；共享计算不在每页复制公式。',
        '分析模型：先选问题和方法，再定范围、样本、比较、基线、假设、算法版本及停止条件。',
        '专题：主结果、解释、对象、证据、行动、复查共用范围；不适用筛选显式暂停。',
        '视角/快照：视角保存条件并按当前数据重算；快照冻结当时数字、来源和定义，二者分开。',
        '目标/告警：目标与规则有业务责任及版本；缺数据不亮绿；去重、冷却、升级与复查逐步建设。',
        '建议架构：保留一个受控语义与计算服务，页面读取版本化定义。各部门维护模板与来源，IT维护通用模型和权限；业务审核人与维护替补必须明确。',
        '', '六、按本厂条件分期',
        '基础与一期：身份、Excel标准模板、订单/SN/批次关联、来源行、质量覆盖、交付阻断及数据可信；每天能查对象、查证据。',
        '部门深化：计划/在制、齐套、采购、库存、工时、财务对账与同配置分布；条件统一后扩展跨图比较。',
        '条件专题：曲线、MSA、SPC、过程能力、特殊产品及外部认证，按真实业务与数据条件启用。',
        '成熟分析：历史够且有回测再预测；资源约束标定后再优化；每项评估计算和维护负担。',
        '', '七、全部382项的分析选型索引（完整业务定义沿用主清单）']
    for dom in d['domains']:
        lines += ['', dom['code']+' '+dom['name']+'｜'+str(len(dom['items']))+'项']
        for n in dom['items']:
            lines += [n['id']+' '+n['need']+'｜'+' / '.join(names[i] for i in n['analysis_methods']),
                      '前提：'+n['prerequisite'], '来源/粒度：'+n['source']+'；'+n['grain'],
                      '展示/行动：'+n['view']+'；'+n['action']]
    lines += ['', '八、参考与验证边界']
    lines += [x['title']+'｜'+x['url'] for x in f['references']]
    lines += ['参考用于模型、内容生命周期及方法定义；本厂需求、展示选择和分期为自主构思，不是厂商认证。',
              '上述方法推荐本身不增加指标发布、保存模型或业务事实。另有受控采样独立增量：10个合成试验、730条观测与10条事件，I-MR候选试算及来源验证详见《BI过程稳定性_试算说明_20261007.txt》。真实MSA与正式能力仍待建设，浏览器/手机实际交互待验收。']
    return '\n'.join(lines)+'\n'


def method_reading_note():
    return '2026-10-07展示深化：18类方法的数据门槛、17页阅读预演及全部382项候选选型；指标口径保留。新增受控采样候选试算，详见《BI过程稳定性_试算说明_20261007.txt》。先读《BI展示深化_简明方案_20261007.txt》，方法详见《BI分析方法与页面预演_20261007.txt》。新资料包为《BI深化设计_20261007_离线资料包.zip》；旧v9 ZIP与采样前资料保留为历史。'


def remove_exact_increment(d):
    """Undo only this known planning increment for older release proofs."""
    expected=refine_methods(copy.deepcopy(d))
    assert d['framework']['method_workshop']==expected['framework']['method_workshop']
    d['framework'].pop('method_workshop')
    for dom,expected_dom in zip(d['domains'],expected['domains'],strict=True):
        for n,e in zip(dom['items'],expected_dom['items'],strict=True):
            for field in ('analysis_methods','analysis_method_note'):
                assert n[field]==e[field]
                n.pop(field)
    for p,e in zip(d['page_blueprints'],expected['page_blueprints'],strict=True):
        assert p['analysis_methods']==e['analysis_methods']
        p.pop('analysis_methods')
