"""Track bounded WIP remainder simulation without promoting formal scheduling."""
from copy import deepcopy
MARKER=' 在制剩余试排：'
STATUS=('新增完整Excel版本驱动的剩余任务试排：明确原工单与报工，已完成仅保留实际时点，加工中固定原人机续作，暂停待续增加恢复准备。'
        '逐任务剩余定额扣声明已投入量，独立余料分共享与工单专属，联合物料、人机日历及资格。'
        '提供工单覆盖、历史/续作/新排/阻断、双视角甘特、物料守恒、任务明细、版本来源和完整CSV/JSON可重算导出。'
        '48号模拟Excel包含2工单12台、52任务及8方案；保留旧联立算法。'
        '仍是合成局部试排，尚缺报废补产、返工路线、替代料、模具、多机看护、冻结历史资格与正式批准；浏览器及手机未验收。')
CONTRACT=dict(revision='WIP_REMAINDER_SHARED_POOLS_1',href='#wip-trial',state=STATUS,
 definition='一个完整方案版本×一种派序策略；逐任务完成量+剩余量=原任务量。工单覆盖按完整工单计，不把跨工序任务台数加成产量。',
 measures='历史完成任务、锁定续作任务、新排剩余任务、未排任务互斥；工单仅在所有任务有实际或未来完成时计算完工与交期。暂停时摘要空值，不记零阻断。',
 material='逐任务剩余量×BOM(1+损耗)按步长向上取整，减声明已投入量；已投入量不进库存。独立尚未耗用池按物料/批次/位置去重，专属先用且不能跨工单，共享池一次预留。',
 presentation='方案/版本与策略→暂停原因或四类任务计数→工单覆盖与交期→设备/人员未来时间轴→原报工与任务剩余量→物料余额与预留流水→同版原Excel来源及完整导出。',
 boundary='整单精确映射，报工必须全部明确覆盖；加工中从截止时点原人机连续续作。版本链、数量、用料或摘要冲突暂停。单容量、单人全程陪同、尾部追加，不抢占或回填，不声称最优及真实可派工。')

def refine_wip_trial(d):
 for group in d['domains']:
  for item in group['items']:
   if item['id'] in ('F-01','F-03','F-07','G-02','J-09'):
    for obj,key in [(item,'gap'),(item['display_design'],'availability'),(item['presentation_contract'],'detail_contract')]:obj[key]=obj[key].split(MARKER)[0]+MARKER+STATUS
 d['framework']['surfaces']=[r for r in d['framework']['surfaces'] if r['href']!='#wip-trial']+[dict(name='在制剩余试排',question='已发生报工之后，剩余任务能否在料、人、机约束下完成？',content=CONTRACT['presentation'],action='先核对完整版本→区分历史与未来→查首阻断、原报工和余料→导出复算后走正式业务流程',href='#wip-trial',status=STATUS)]
 d['framework'].pop('wip_trial',None);d['framework']['wip_trial']=deepcopy(CONTRACT)
 return d
