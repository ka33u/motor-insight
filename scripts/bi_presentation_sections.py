"""Offline reading companion from exactly the same presentation contracts."""


def presentation_text(d, include_index=True):
    f=d['framework']['presentation_design']
    needs=[n for dom in d['domains'] for n in dom['items']]
    names={n['id']:n['need'] for n in needs}
    metrics={m['id']:m['name'] for m in d['metrics']}
    lines=[
        '电机制造企业：BI展示内容与交互设计 · 完善版',
        f['revision'],
        f'{len(d["domains"])}领域 / {len(needs)}项候选需求 / {len(d["metrics"])}项指标口径 / {len(d["page_blueprints"])}页蓝图',
        '适用现状：用友U8；momo MES待上线且产品信息待确认；全流程自制；约900台/日；小批量定制；预算和IT人力有限。',
        '现有全部业务数据为合成演示，未接入真实U8/MES；本文为设计建议。',
        f['scope'],'',
        '一、BI怎样定义',f['definition'],f['factory_definition'],
        '目的：让岗位能从结果找到对象和证据，作出下一步决定，并在相同范围下复查。',
        '职责：U8维护财务及经营单据；MES维护生产执行；数据平台维护采集、身份、关系与版本；BI负责定义、计算和呈现。具体系统边界以实际接口及流程确认。',
        '', '二、八类可配置定义对象',
    ]
    lines.extend('｜'.join(x[k] for k in ['name','definition','example_code','boundary']) for x in f['definition_objects'])
    lines.extend(['','三、按任务选择十二种呈现方式','以下是设计形态，不代表十二套功能均已建成。'])
    for x in f['formats']:
        lines.extend(['',x['name']+'｜'+x['reader'],'首屏：'+x['content'],
                      '图形：'+x['visual'],'节奏：'+x['cadence'],'密度与边界：'+x['density']])
    lines.extend(['','四、一页BI的统一阅读顺序',
        '1. 范围与可信度：业务日期类型、观察期间、业务/已知截止、配置、筛选、权限、指标版本和来源时间。',
        '2. 主结果或对象摘要：每页选1—3个结果；数量带单位，比率带分子分母，分布带样本数。',
        '3. 解释与可比性：趋势、分组、差异或时间；说明可比条件、未覆盖对象和不能解释的部分。',
        '4. 完整对象清单：订单行、工单、批次、SN或单据；分页不改变全范围统计。',
        '5. 来源与版本：具体记录、Excel工作表/行、关联依据和有权读取的原件。',
        '6. 责任、下一步与复查：协调留痕、正式业务执行与批准分开；返回保留原范围。',
        '', '五、17页的默认任务与展示路径',
    ])
    for p in d['page_blueprints']:
        r=p['reading_contract'];c=p['content_focus']
        lines.extend(['',p['id']+' '+p['name'],'使用者：'+p['reader'],
            '第一件事：'+r['first_task'],'默认阅读：'+r['default_reading'],
            '主结果候选：'+' / '.join(i+' '+metrics[i] for i in r['result_metric_ids']),
            '解释候选：'+' / '.join(i+' '+metrics[i] for i in c['driver_metric_ids']),
            '护栏候选：'+' / '.join(i+' '+metrics[i] for i in c['guardrail_metric_ids']),
            '显示范围：'+' / '.join(r['visible_context']),
            '对象和下钻：'+p['detail']+'；'+p['drill'],
            '最后形成的决定：'+r['exit_decision'],'手机用途：'+r['mobile_task'],
            '数据门槛：'+p['gate'],'没有数据：'+r['empty_state'],
            '已有模拟状态：'+p['status'],
        ])
    lines.extend(['','六、12条跨部门问题路径'])
    for j in f['journeys']:
        lines.extend(['',j['id']+' '+j['question'],j['path'],'边界：'+j['boundary'],
            '涉及需求：'+' / '.join(i+' '+names[i] for i in j['need_ids']),
            '页面：'+' / '.join(j['page_ids'])])
    lines.extend(['','七、26领域的比较条件与手机任务'])
    for x in f['domain_comparison']:
        lines.extend(['',x['code']+' '+x['name'],'可比条件：'+x['rule'],'手机：'+x['mobile_task']])
    lines.extend(['','八、数据不具备时怎样显示'])
    lines.extend(x['name']+'｜'+x['render'] for x in f['gates'])
    lines.extend(['','九、从需求到受控发布'])
    lines.extend(' → '.join(row) for row in f['configuration_flow'])
    lines.extend(['','十、低预算先补四种来源'])
    lines.extend('｜'.join(row) for row in f['collection_start'])
    lines.extend(['','十一、可能还需要扩展的条件清单',
        '企业确认存在对应业务后，再补字段、口径、页面及维护岗位；不把条件项一律列为必建。'])
    for x in f['conditional_questions']:
        lines.extend([x['subject']+'｜'+x['question'],'涉及领域：'+x['domains'],'后续：'+x['followup']])
    if include_index:
        lines.extend(['','十二、全部382项需求与逐项展示契约索引',
            '本索引列出所有候选；完整业务定义、前提、公式、动作、验收与缺口见《BI完整382项需求清单.txt》。'])
        for dom in d['domains']:
            lines.extend(['',dom['code']+' '+dom['name']+'｜'+str(len(dom['items']))+'项'])
            for n in dom['items']:
                c=n['presentation_contract']
                lines.extend([n['id']+' '+n['need']+'｜'+n['implementation'],
                    '  问题：'+c['question'],'  主视觉：'+c['primary_visual']+'；粒度：'+c['object_grain'],
                    '  比较：'+c['compare_gate'],'  页面：'+' / '.join(n['page_ids']),
                    '  证据与行动：'+c['evidence'],
                ])
    lines.extend(['','十三、方法依据与验证边界',f['reference_basis']])
    lines.extend(x['title']+'｜'+x['url'] for x in f['references'])
    lines.extend([
        '新增元数据、引用、离线结构、脚本语法及已有BI草稿服务端检查；浏览器实际渲染、手机、筛选和下载尚未实测。',
        '本轮保留原需求、指标和页面定义及模拟覆盖状态；计量原件仅在P-04/P-05与四页状态中增加经验证的模拟范围。未新增正式指标发布、真实系统连接或审批执行。',
        '首期建议继续围绕订单交付、质量试验、对象追溯与数据可信度四页；经营首页汇总其中已核实结果。',
    ])
    return lines
