"""Readable companions from the same BI design metadata."""


def execution_text(d, include_index=False):
    plan=d['framework']['execution_design']
    metrics={m['id']:m['name'] for m in d['metrics']}
    def names(ids):
        return ' / '.join(i+' '+metrics[i] for i in ids) or '以对象清单及解释内容为主；不增加凑数指标'
    lines=[
        'BI建设分层与页面内容 · 实施设计补充',
        '适用：U8、MES待上线、全流程自制、约900台/日、小批量定制、预算及IT人力有限。',
        plan['definition'],plan['scope_note'],
        '同源设计版本：'+plan['revision'],
        '约900台/日来自用户；模拟样本数量不是实际产能、业务绩效或投资收益。',
        '', '一、现有382项候选怎样安排',
    ]
    for p in plan['packages']:
        lines.extend([
            p['id']+' '+p['name']+'｜'+str(p['candidate_count'])+'项候选',
            '分类依据：'+p['rule'],'进入条件：'+p['gate'],'持续投入：'+p['cost'],'',
        ])
    lines.extend([
        '这五类是建议分包，类别不代表完成率或数据已具备，也不是工期承诺。',
        '基础与首期页可并行推进；条件专题可在实际业务需要的阶段进入，不需等全部部门页做完。',
        '每项先记录：'+' / '.join(plan['scope_review_states']),
        '每项再填写：业务责任人、来源责任人、实际字段和关系、更新约定、维护替补、试点对象及验收结论。',
        '', '二、低预算的采集与取舍',
    ])
    for title,key in [('四种来源起步','collection_modes'),('优先顺序的评审问题','priority_review'),('能持续运行的五项检查','readiness_checks')]:
        lines.extend(['',title]);lines.extend('｜'.join(row) for row in plan[key])
    lines.extend(['', '三、26份部门需求访谈与日常使用设计'])
    for dom in d['domains']:
        s=dom['decision_session'];c=s['data_contract']
        lines.extend([
            '',dom['code']+' '+dom['name']+'｜'+str(len(s['need_ids']))+'项候选',
            '建议评审岗位：'+s['review_owner'],'要作决定：'+s['question'],
            '查看节奏：'+s['cadence'],'内容范围：'+s['content'],'试点起步：'+s['start'],
            '关键关联键：'+c['key'],'最少采集字段：'+c['fields'],'时间依据：'+c['clock'],
            '需防误读：'+s['blindspot'],'真实来源：'+c['source_status'],
            '本域完整清单：'+'；'.join(n['id']+' '+n['need'] for n in dom['items']),
        ])
    lines.extend(['', '四、17页展示内容的优先级与阅读顺序',
                  '每页首屏选1—3个主结果；解释指标、业务护栏和数据覆盖按任务进入次级层。',
                  '以下引用63项现有候选定义，不新增或改写正式指标，也不证明原页面已完成这些计算。'])
    for p in d['page_blueprints']:
        c=p['content_focus'];s=p['display_spec']
        lines.extend([
            '',p['id']+' '+p['name']+'｜'+c['mode'],'读者：'+p['reader'],
            '主问题：'+p['question'],'主结果候选：'+names(c['result_metric_ids']),
            '解释指标候选：'+names(c['driver_metric_ids']),
            '护栏候选：'+names(c['guardrail_metric_ids']),
            '阅读顺序：'+c['reading_path'],'对象清单：'+c['supporting_content'],
            '筛选依据：'+s['filter_rule'],'时间：'+s['time_semantics'],
            '手机：'+s['mobile'],'处理：'+p['decision'],'关键边界：'+c['boundary'],
            '没有数据时：'+c['empty_state'],
        ])
    lines.extend(['', '五、创新体验的具体呈现'])
    lines.extend('｜'.join(row) for row in plan['innovation_patterns'])
    lines.extend(['', '六、定义与发布应怎样交接',
        '需求：问题、岗位、对象、查看频率、实际决定和复查方法。',
        '业务模型：事实粒度、稳定主键、有效关联、基数、日期角色和计量单位。',
        '指标：身份版本、范围、分子分母、时间、排除、未知、汇总可加性、比较条件和权限。',
        '分析模型：趋势、分解、分布、透视、关系、追溯或情景的输入、算法、样本与边界。',
        '专题：围绕同一决定组合少量卡片、解释图、对象清单、证据和协调入口。',
        '页面：范围、截止、版本、更新时间、结果/未知、对象、证据、动作、复查和手机任务。',
        '发布：草稿→样例核对→业务及数据评审→受控版本→持续使用复查；退出也留原因。',
        '页面配置、指标批准和源业务执行的授权分别处理；当前补充仅为设计元数据。',
        '', '七、来源与验证边界',plan['source_basis'],
        '方法参考（厂内指标、内容布局和分包为自主设计建议）：',
    ])
    lines.extend(s['title']+'｜'+s['url']+'｜'+s.get('use','方法参考') for s in d['sources'])
    lines.extend([
        '未接入真实U8/MES；momo供应商和接口待确认。真实字段、工厂限值及审批规则待核实。',
        '目录与TXT/HTML/JSON同源；本次做结构、引用、完整性、幂等与代码检查。',
        '新增页面实际浏览器渲染、手机布局、筛选交互与下载仍待验收。',
        '完整逐项业务定义、来源、粒度、数据前提、动作和验收见《BI完整382项需求清单.txt》。',
    ])
    if include_index:
        lines.extend(['','八、382项需求建设包索引（每项仅归一类；跨页复用不重复计数）'])
        for dom in d['domains']:
            lines.append('\n'+dom['code']+' '+dom['name'])
            for n in dom['items']:
                p=n['delivery_proposal']
                lines.append(n['id']+' '+n['need']+'｜'+p['package_id']+' '+p['package_name']+'｜'+' / '.join(n['page_ids'])+'｜'+n['implementation'])
    return lines
