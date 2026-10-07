"""Document an evidence join without claiming production approval coverage."""
from copy import deepcopy
MARKER = ' 首件证据补充：'
STATUS = '现有Excel首件计划关联最新非作废实测、适用规范、仪器使用、校准登记及影响范围；分页筛选、直接来源和CSV/JSON可查。新试排按同工单/配置/路线/工序分支查找候选，缺少计划明确待补。仅为证据核对，真实证书审阅、测量能力、复核签字、触发批次覆盖、首件批准和放量流程仍待建设。'
CONTRACT = dict(revision='first-piece-20261007', href='#first-piece', state=STATUS,
 definition='一个首件应检计划一行；首件与巡检、首次与最新分别保留。主状态互斥，超限、漏项和计量疑点可重叠。',
 evidence='最新有效执行先选择再核对，缺项或无效不退回旧合格；计量使用版本完整读取，最近撤销或失效不回退；已登记影响不能因资料核查完成自动消除。',
 presentation='七类状态→计划/工单/工序筛选→最新参数与计量依据→检验履历及漏项→Excel行来源→带摘要的导出。投产方案入口展示同工单的候选首件缺口。',
 boundary='所列证据齐备不等于正式首件批准。不把其他工单历史合格用于新工单放量；候选计划不证明触发覆盖，无候选不阻止首件试制。原件与测量能力仍需独立核验，不改变既有指标、实测或审批。')


def refine_first_piece(d):
    for domain in d['domains']:
        for need in domain['items']:
            need['gap'] = need['gap'].split(MARKER)[0]
            if need['id'] in ('F-08', 'L-09', 'L-12'):
                need['gap'] += MARKER+STATUS
    for page in d['page_blueprints']:
        page['status'] = page['status'].split(MARKER)[0]
        if page['id'] in ('P03', 'P05'):
            page['status'] += MARKER+STATUS
    d['framework']['first_piece_evidence'] = deepcopy(CONTRACT)
    d['framework']['surfaces'] = [s for s in d['framework']['surfaces'] if s['href'] != '#first-piece'] + [dict(name='首件证据工作台', question='当前首件计划的实测和计量依据是否齐备？', content=CONTRACT['presentation'], action='核对缺项、超限、计量疑点及新工单缺口，再交授权岗位复核', href='#first-piece', status=STATUS)]
    return d
