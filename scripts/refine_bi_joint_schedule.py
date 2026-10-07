"""Append the material trial's exact scope without inflating BI acceptance."""
from copy import deepcopy
MARKER = ' 物料人机联立补充：'
NEEDS = ('F-03', 'F-06', 'F-07')
STATUS = ('已提供独立合成物料、人机联立试排：当前BOM完整绑定、整批损耗取整、共享供给FIFO、隔离排除与未来到料，'
          '同一图中重排设备和人员。10个案例保留缺料、缺人员窗口及资料暂停；批次交期、人机双甘特、用料和预留流水可追至Excel。'
          '仅模拟部分覆盖；按派序保守预留，不回填、不抢占、不自动释放；未含保质期、替代料、换算、模具和正式批准。'
          '管理员、分析师、运营可读，不授予原件权限；浏览器、手机和实际下载未验收。')
CONTRACT = dict(revision='material-crew-resource-20261007', href='#joint-schedule', needs=list(NEEDS), state=STATUS,
 definition='独立方案×批次×BOM行×绑定工序×供给批次。批次台数计一次；kg和件分别核对。当前配置BOM不是历史订单冻结版本。',
 demand='需求=向上取整[批量×BOM单耗×(1+损耗)/步长]×步长；完整覆盖当前BOM。同一工序首个成功排入任务准备开始时预留整批，后续份号不得早于已预留时点。',
 supply='同物料同单位共享供给，按可用时间与供给号FIFO拆批；隔离批全部排除，否则排除其中不可预留量。按派序先占未来供给，不抢占、不自动释放。',
 method='在物料就绪、前序与滞后、人机尾部、双方日历及资格交集中重新选择完整换型加工窗口。每任务一人，容量1；不回填空档，不证明最优。',
 presentation='范围与假设→批次完成/未排/晚交→设备或人员甘特→首个阻断任务→整批需求、供给守恒和FIFO流水→Excel依据与完整导出。资料错误暂停，已知不足保留全部任务。',
 measures='物料就绪等待=物料可用/既有预留时点与前序就绪的非负差；共同等待还含人机窗口，不能相加。批次差值比较两个启发式结果，不作因果解释。',
 boundary='全部合成，只读试算；不读取历史库存作为未来真值、不确认采购承诺、不写回计划或库存。未含保质期、替代料、单位换算、模具、文件/质量放行和正式派工；不等于完整投产齐套门槛。')


def refine_joint(d):
    for domain in d['domains']:
        for need in domain['items']:
            if need['id'] in NEEDS:
                need['gap'] = need['gap'].split(MARKER)[0] + MARKER + STATUS
    for page in d['page_blueprints']:
        if page['id'] == 'P03':
            page['status'] = page['status'].split(MARKER)[0] + MARKER + STATUS
    d['framework']['joint_schedule_trial'] = deepcopy(CONTRACT)
    d['framework']['surfaces'] = [s for s in d['framework']['surfaces'] if s['href'] != '#joint-schedule'] + [dict(name='物料、人机联立试排', question='料、人、机何时同时可用，哪个批次为何未排入？', content=CONTRACT['presentation'], action='核对BOM、用料、供给时间及人机资格，比较派序后交计划岗位评审', href='#joint-schedule', status=STATUS)]
    return d
