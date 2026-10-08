"""Keep the trial reading contract separate from unchanged calculation coverage."""
from copy import deepcopy

MARKER = ' 试排依据阅读：'
STATUS = ('资源、人机、物料联立和两策略对照四个页面的面板正文已按实际三参数契约修复。'
          '任务依据以中文业务表列原编号、配置路线、批次/份号、直接前序、首个阻断、准备/加工/完成时点、换型和等待、资源及人员资格窗口；物料联立保留整批需求、步长单位、实际预留触发任务及缺口。'
          '任务直接来源和全方案来源区分，物料联立任务筛选明确不改变汇总、全方案甘特或完整导出。人员甘特纵轴标明工号；重新读取清除旧凭据，快速切换和弹窗竞争丢弃旧响应，下载防重复。'
          '38组纯JS及六岗位HTTP验证，保留原计算与输入；浏览器布局、手机、键盘和实际下载未验收。')
CONTRACT = dict(revision='schedule-reading-20261008',state=STATUS,
                hrefs=['#finite-schedule','#crew-schedule','#joint-schedule','#joint-schedule?view=compare'],
                definition='完整独立试排汇总与局部任务清单分层；任务数量不累加为批次产量，预留不等于实际领料。',
                presentation='完整批次风险→设备/人员甘特与任务阻断→中文任务依据→直接Excel来源；全方案来源及完整导出独立提供。',
                boundary='不改原算法、事实、权限或审批；暂停、缺失与未排入不补零，kg和件不合计，物料等待与共同等待不相加。')

def refine_schedule_reading(d):
    for group in d['domains']:
        for item in group['items']:
            if item['id'] in ('F-02','F-03','F-06','F-07','Q-02'):
                item['gap'] = item['gap'].split(MARKER)[0]+MARKER+STATUS
    for page in d['page_blueprints']:
        if page['id'] in ('P03','P10'):
            page['status'] = page['status'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['schedule_evidence_reading'] = deepcopy(CONTRACT)
    for surface in d['framework']['surfaces']:
        if surface.get('href') in CONTRACT['hrefs']:
            surface['status'] = surface['status'].split(MARKER)[0]+MARKER+STATUS
    return d
