"""Recipient changes are distinct from material net changes and batch completion."""
from copy import deepcopy
MARKER = ' 批次获料对照：'
STATUS = ('两策略物料页新增按原物料号、单位和批次的获配对照，Decimal核对整批需求、预留、未预留及差值。'
          '分别展示增加获配、减少获配、数量不变但流水变化；增加量减减少量与总预留差值一致，净变化为0仍可有批次取舍。'
          '同一物料两列共用最大单批需求刻度，保留精确数量、原批次状态及无完成时间；物料/变化筛选、分页不改变刻度。'
          '点批次只看对应物料工序，可与批次/变化条件取交集或重置全部任务；完整来源及两列导出不随局部选择缩小。'
          '展示定义绑定原对照凭据，完整JSON可零数据库查询复原；原排程、需求和预留算法不变，不将获配当作齐套、领料或交付批准。'
          '已基于43份有效合成Excel回放库核查12方案与六岗位，浏览器布局、手机、键盘及实际下载仍未验收。')
CONTRACT = dict(revision='joint-batch-material-v1', href='#joint-schedule?view=compare', state=STATUS,
    definition='同一方案和来源的两策略结果；粒度为material_id＋unit＋job_id。整批需求按需求号计一次，工序份号仅作为下钻身份。',
    measures='获配差值=右列预留−左列预留；正负分别归为增加/减少。每种物料的增加量−减少量=总预留差值；数量不变但供给/任务/时点不同单列，各物料批次数有交叠。',
    presentation='两列完整批次与转换→完整物料总账→同料批次获配量和未预留量（共用最大单批需求刻度）→对应物料工序→两列整批需求与流水→共同来源及完整导出。',
    boundary='不重排、不转移预留、不推荐最优策略；本物料全预留不表示全部物料齐套或批次排完，未预留也可能来自人机或前序受阻。不同单位不加总。')


def refine_batch_material(d):
    for group in d['domains']:
        for item in group['items']:
            if item['id'] in ('F-03', 'F-06', 'F-07'):
                item['gap'] = item['gap'].split(MARKER)[0]+MARKER+STATUS
    for page in d['page_blueprints']:
        if page['id'] == 'P03': page['status'] = page['status'].split(MARKER)[0]+MARKER+STATUS
    for surface in d['framework']['surfaces']:
        if surface.get('href') == CONTRACT['href']:
            surface['status'] = surface['status'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['joint_batch_material_comparison'] = deepcopy(CONTRACT)
    return d
