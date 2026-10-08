"""Root association is a reading aggregation over the original trial, not a cause model."""
from copy import deepcopy
MARKER=' 首阻断关联：'
STATUS=('按原试排首阻断编号整理关联未排任务、涉及批次和逐批次台数；全方案摘要独立去重，多首阻断交叠单列，禁止跨行相加或当作损失产量。'
        '按最早内部目标、批次数、任务数及原编号确定阅读顺序，不生成新的派工优先级。'
        '点首阻断读取原任务候选依据，点数量查看完整关联任务；批次、状态与首阻断取交集，可重置，阅读页间保留而重新读取重置。'
        '原汇总、甘特、来源和完整导出保持全方案；资料暂停或关系/汇总无法核对时暂停关联计算。'
        '纯JS、独立Python核对及隔离HTTP已验证；浏览器、手机、键盘和实际下载仍未验收。')
CONTRACT=dict(revision='joint-blocker-reading-v1',href='#joint-schedule',state=STATUS,
              definition='仅使用完整结果中未排任务的root_tasks原编号归组；原首阻断必须存在且自指，任务/批次编号唯一，状态与完整摘要一致。',
              measures='逐行任务按任务号去重；涉及批次按批次号去重后每批台数只取一次。全方案独立对任务/批次去重，不能累加行结果。多首阻断任务单列。',
              time='取关联批次内部应完成时间最小值，保持厂内假设时间；不是客户承诺、已逾期判断或损失工时。',
              presentation='完整首阻断摘要→每页40个阻断及原未排原因→点击任务候选证据/点击数量联动明细→任务、批次及状态交集；局部选择不改全局口径。',
              boundary='原算法的阻断传播并非现场因果、关键路径或风险评分。涉及批次台数不是损失产量/客户逾期量。导出仍为原完整方案，使用本版函数可从其result复原关联表。')

def refine_blockers(d):
    for group in d['domains']:
        for item in group['items']:
            if item['id'] in ('F-03','F-06','F-07'):item['gap']=item['gap'].split(MARKER)[0]+MARKER+STATUS
    for page in d['page_blueprints']:
        if page['id']=='P03':page['status']=page['status'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['joint_blocker_reading']=deepcopy(CONTRACT)
    for surface in d['framework']['surfaces']:
        if surface.get('href')=='#joint-schedule':surface['status']=surface['status'].split(MARKER)[0]+MARKER+STATUS
    return d
