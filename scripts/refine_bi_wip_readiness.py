"""Document the evidence bridge, preserving the pending scope of WIP scheduling."""
from copy import deepcopy
MARKER=' 在制重排准备：'
STATUS=('新增只读工单核对页，并列报工时间分类、定子/转子原批次份额、装配SN与原备料口径的整单定额及领退料。'
        '同名路线仅列候选，不自动绑定；良品不跨工序累加，净领料不充当线边实存，整单待领不充当剩余工序需求。'
        '未知在制保留空值和已知部分；混箱保留各工单份额并补齐相关根批次来源。'
        '支持按工单检索、登记/证据分类、原行下钻、Excel来源和完整筛选CSV。'
        '本轮使用已有47份模拟Excel中的46份有效输入，未新增或修改业务记录。'
        '任务完成映射、剩余工时、线边余料、运行中人机占用及在制联立重排仍待建设；浏览器、手机和实际下载未验收。')
CONTRACT=dict(revision='wip-replanning-evidence-v1',href='#wip-readiness',state=STATUS,
    definition='工单阅读粒度；报工是记录笔数，定子/转子按原批次份额分支列件数，物料按原单位逐项列示。固定业务及登记截止下读取当前导入登记，不构成完整历史数据库快照。',
    measures='有报工工单、有核定在制份额工单与完工登记仍有份额工单分别去重计数，可以交叠。分支有未知批次或没有基准时完整数量留空，另列已知部分；无报工登记不证明尚未开工。',
    presentation='工单范围→证据覆盖计数→登记状态与证据并列→可交叠分类队列→任务映射缺口/在制份额/报工原数量/整单领退料→原Excel行与完整清单导出。',
    boundary='准备资料核对不生成剩余工序排程。旧联立试排与整单备料公式保留；余料、消耗、工序剩余工时和人机恢复必须补充明确版本证据。')
ROW=dict(name='在制重排准备核对',question='这张工单有哪些报工、在制和领退料证据，重排前还需补齐什么？',content=CONTRACT['presentation'],
    action='按工单核对三个粒度→定位原Excel及关联批次→由计划、工艺、车间和仓储补充明确映射与剩余约束',href='#wip-readiness',status=STATUS)

def refine_readiness(d):
    for group in d['domains']:
        for item in group['items']:
            if item['id'] in ('F-01','F-03','F-07','G-02','J-09'):
                item['gap']=item['gap'].split(MARKER)[0]+MARKER+STATUS
                item['display_design']['availability']=item['display_design']['availability'].split(MARKER)[0]+MARKER+STATUS
                item['presentation_contract']['detail_contract']=item['presentation_contract']['detail_contract'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['surfaces']=[r for r in d['framework']['surfaces'] if r['href']!=ROW['href']]+[deepcopy(ROW)]
    d['framework'].pop('wip_readiness',None);d['framework']['wip_readiness']=deepcopy(CONTRACT)
    return d
