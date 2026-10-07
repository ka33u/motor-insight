"""Precisely scope order coverage and BOM snapshot review within existing needs."""
from copy import deepcopy
MARKER = ' 订单BOM基线补充：'
NEEDS = ('E-01', 'F-06', 'F-10')
STATUS = ('已提供独立合成订单与BOM基线核对：试排批次完整映射到原订单行、工单及分配，复制关键字段、完整BOM集合与取整规则，核对版本链和内容摘要。'
          '订单台数去重，保留未覆盖数量、客户交期与内部目标差异；当前BOM变化不改基线用量，改为待重核。'
          '三岗位可追溯来源并导出；暂停仍保留完整输入。仅模拟部分覆盖，不等于真实历史批准、冻结区执行、自动重排或投产放行。浏览器、手机及实际下载未验收。')
CONTRACT = dict(revision='order-bom-baseline-20261007', href='#order-baselines', needs=list(NEEDS), state=STATUS,
 definition='基线系列/版本×试排批次×原订单行×工单分配×BOM行。各批次唯一映射，订单台数去重；不同版本及方案不相加。',
 arithmetic='按复制的单耗、损耗与步长计算整批用料；用完整集合摘要核对BOM遗漏。当前字段和试排需求分别对照，变化不覆盖基线。',
 coverage='本方案安排不等于订单需求：去重订单台数、基线时点登记发货、安排台数、未覆盖和超排分别列示。资料待核对时不形成整单参考完成。',
 time='客户原承诺、基线现承诺与试排内部目标分列。客户日期按当日结束比较加工完成，不代表检测放行、发运、签收或OTIF。',
 presentation='范围和版本→135台订单/50台安排/85台未覆盖的合成案例→订单覆盖条→批次映射与双交期→基线用料与当前差异→版本关系和Excel来源。',
 boundary='Excel版本化合成快照，摘要不是业务签批或不可篡改存证。不证明文件在模拟截止时点已经存在；历史资料补录会改变按截止时点重放的登记发货。当前物料试排仍独立计算，不自动采用差异快照排程，不写回订单或库存。')


def refine_order_baseline(d):
    for domain in d['domains']:
        for n in domain['items']:
            if n['id'] in NEEDS:
                n['gap'] = n['gap'].split(MARKER)[0]+MARKER+STATUS
    for page in d['page_blueprints']:
        if page['id'] in ('P02', 'P03', 'P07'):
            page['status'] = page['status'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['order_baseline_trial'] = deepcopy(CONTRACT)
    d['framework']['surfaces'] = [s for s in d['framework']['surfaces'] if s['href'] != '#order-baselines']+[dict(name='订单与BOM基线', question='安排的批次覆盖了多少订单，原用料版本是否仍与当前试排一致？', content=CONTRACT['presentation'], action='核对订单缺口、当前字段差异和客户交期，再形成新版本或交业务评审', href='#order-baselines', status=STATUS)]
    return d
