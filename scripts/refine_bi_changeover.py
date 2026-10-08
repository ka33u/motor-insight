"""Describe one normally imported mixed-product experiment without inflating coverage."""
from copy import deepcopy
MARKER = ' 三品种换型演练：'
STATUS = ('新增45号合成Excel，3产品3批24台、96任务，原设备及工号共用，BOM物料足额。'
          'MP-261016-001对照同一输入的两种原派序：准备360/240分钟，跨族20/10次，首次准备各10次；'
          '按交期全部按内部目标完成，按优先级B002晚949.6分钟，整体完工反而晚6.6分钟。'
          '现有批次并列、人机占用分段、原任务用料/候选及Excel来源可读；优先级人工给定，不是自动同族优化。'
          '没有正式派工、具体型号转换矩阵或模具约束；浏览器与实际岗位试用未验收。')
CONTRACT = dict(revision='mixed-product-changeover-v1', href='#joint-schedule?study=MP-261016-001&view=compare', state=STATUS,
    definition='同一套847行导入假设下的三批试排；换型准备含每资源首次上机与后续跨族，按资源逐段核对，不把人机两视角相加。',
    presentation='先比较批次内部交期及完成时点，再看同设备上下两行的换型/加工分段，最后核查任务、BOM需求、原候选及Excel行。',
    boundary='少换型不等于更早交付；日历外自然分钟也计入晚交。方案24台不可按策略两列重复累加，不使用历史订单OTIF口径。')


def refine_changeover(d):
    for group in d['domains']:
        for item in group['items']:
            if item['id'] in ('F-02', 'F-06', 'F-07'):
                item['gap'] = item['gap'].split(MARKER)[0]+MARKER+STATUS
                item['display_design']['availability'] = item['display_design']['availability'].split(MARKER)[0]+MARKER+STATUS
                item['presentation_contract']['detail_contract'] = item['presentation_contract']['detail_contract'].split(MARKER)[0]+MARKER+STATUS
    for page in d['page_blueprints']:
        if page['id'] == 'P03':
            page['status'] = page['status'].split(MARKER)[0]+MARKER+STATUS
    for surface in d['framework']['surfaces']:
        if surface.get('href') == '#joint-schedule':
            surface['status'] = surface['status'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['mixed_product_changeover'] = deepcopy(CONTRACT)
    return d
