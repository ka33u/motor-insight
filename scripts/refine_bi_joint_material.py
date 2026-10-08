"""Same-material evidence reading, with original reservation and quantity semantics."""
from copy import deepcopy
MARKER=' 逐物料核对：'
STATUS=('物料页及任务用料/缺口可按原物料号和单位打开同料核查，查看同刻度需求/供给构成、逐批次用量、完整需求适用任务、供给状态与原序预留流水。'
        '服务端以Decimal核对需求=已预留+未预留、供给=排除+已预留+范围内剩余+范围外剩余；整批需求不随份号重复累加。'
        '同一凭据约束物料、任务候选与Excel来源，支持任务往返；定义变化须重新读取。完整导出保留全方案，result可零查询复原物料视图。'
        '未预留不等于缺料，已预留不等于实际领料；原总量缺口不等于整批未预留量。保留原算法，不作跨批次因果归责或重新分配。'
        '44号合成Excel新增两个同型号、各6台批次的共享硅钢对照：MP-261009-001仅够一批，交期优先排完B001、优先级优先排完B002；'
        'MP-261009-002供给充足，两策略均排完12台。新输入经正常导入和公开文件空库回放，需求、预留、来源及两策略结果可核查。'
        '案例之间供给独立，不代表真实缺料归因或正式派工。浏览器、手机、键盘及实际下载仍未验收。')
CONTRACT=dict(revision='joint-material-evidence-v1',href='#joint-schedule',state=STATUS,
              definition='完整试排中按material_id与unit精确匹配需求、供给与分配；每个需求与供给身份唯一，分配须对应原任务、批次、路线、供给可用和任务准备开始时刻。',
              measures='同料同单位以十进制核对原账；整批需求只计一次。总量缺口=max(0,所需量-范围内可用量)，未预留量=所需量-已预留量，两者分别展示。',
              time='范围终点及之后到料均在范围外；以原厂内时间核对，流水保留算法序号而不按预留时刻重排。构成图不是时间齐套图。',
              presentation='物料总量或任务缺口→同刻度需求/供给构成→同料批次→需求与适用任务→供给批次/排除→原序分配→任务候选及返回→Excel来源。',
              boundary='不改变排程、预留、BOM、库存或审批；未排完批次已有预留继续保留。不同物料、kg和件不汇总，完整导出仍为全方案。')

def refine_material(d):
    for group in d['domains']:
        for item in group['items']:
            if item['id'] in ('F-03','F-06'):item['gap']=item['gap'].split(MARKER)[0]+MARKER+STATUS
    for page in d['page_blueprints']:
        if page['id']=='P03':page['status']=page['status'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['joint_material_evidence']=deepcopy(CONTRACT)
    for surface in d['framework']['surfaces']:
        if surface.get('href')=='#joint-schedule':surface['status']=surface['status'].split(MARKER)[0]+MARKER+STATUS
    return d
