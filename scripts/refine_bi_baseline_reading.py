"""Order → batch → frozen BOM reading lens over unchanged complete results."""
from copy import deepcopy
MARKER = ' 基线联动阅读：'
STATUS = ('修复基线页表格被当成标题说明转义的问题，按完整基线保留订单覆盖与汇总。点选订单行或批次后，关联映射、冻结用料与字段差异按原编号联动；用料相符/待核对筛选只作用用料表，40行分页不截断完整依据。'
          '批次详情使用中文业务表，分列原承诺、基线现承诺、内部目标和加工完成，保留用料版本、步长、单位、当前绑定及Excel来源。'
          '全基线CSV/JSON与全方案来源明确不受明细选择影响；选中批次详情沿用带凭据的当前核对。恢复全部、跨订单清除批次选择及旧异步响应丢弃已做纯JS验证。'
          '未新增或改变计算、事实、审批或来源权限；浏览器、手机、键盘与实际下载仍未验收。')
CONTRACT = dict(revision='baseline-reading-20261008',href='#order-baselines',state=STATUS,
               definition='全基线结果与订单行/基线映射/用料核对状态的明细阅读选择分层。订单按订单行编号联动，批次按映射号联动，不按产品或相似文本猜匹配。',
               presentation='完整基线状态与订单覆盖→点选订单→关联批次→冻结用料/字段差异→批次中文详情与直接来源；全方案来源/全基线导出单独标明。',
               boundary='明细选择不重新求和、改写顶层汇总或产生新的时间/用料计算；来源与导出范围有明确标签。暂停、缺失、零分母和未完成不显示为健康零值。')

def refine_baseline_reading(d):
    for group in d['domains']:
        for n in group['items']:
            if n['id'] in ('E-01','F-06','F-10'):
                n['gap'] = n['gap'].split(MARKER)[0]+MARKER+STATUS
    for page in d['page_blueprints']:
        if page['id'] in ('P02','P03','P07'):
            page['status'] = page['status'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['baseline_reading'] = deepcopy(CONTRACT)
    for surface in d['framework']['surfaces']:
        if surface.get('href') == '#order-baselines':
            surface['content']=CONTRACT['presentation']
            surface['status']=surface['status'].split(MARKER)[0]+MARKER+STATUS
    return d
