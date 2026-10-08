"""Describe validated preparation and delivery comparison, without new KPI releases."""
from copy import deepcopy
MARKER = ' 换型准备核对：'
STATUS = ('两策略BI新增已排任务准备构成与交期取舍，同刻度拆分首次上机/跨族分钟，保留零分钟事件及同族延续。'
          '按原设备时序、前一任务、批次族和选中候选逐项核查；两列已排任务集合不同或均为空不计算准备差值，整案结束和晚交差值须双方全排入。'
          '设备展开表、策略/事件筛选、分页及原任务详情保留范围，局部筛选不缩小整案来源和导出；同版JSON可无数据库查询复原。'
          '不改原试排、不推出最优或节省收益结论；浏览器、手机和键盘仍未验收。')
CONTRACT = dict(revision='joint-setup-reading-v1', href='#joint-schedule?view=compare', state=STATUS,
    definition='准备事件粒度=策略×设备×已排任务；首次上机初始族未知，随后按上一已排任务族判定跨族或同族。声明分钟向上取整到秒并核对原时点。',
    measures='准备分钟只累计原设备上的任务一次，不叠加人员视角；零分钟首次/跨族仍计事件。准备差值要求两列非空且相同的已排任务集合，完整方案结束取全部任务完成最大值。',
    presentation='整案两条同刻度首次/跨族构成→并列整体结束及已完成批次晚交→原设备汇总→带前一任务/族的事件明细→原两列详情与共同Excel来源。',
    boundary='未排完不是零完成时间；只有已完成批次才有晚交，未排完另列。差值为优先级减交期策略，包含休息/夜间的时间差不能当作占用工时。无效率、OTIF、因果或自动批准。')


def refine_setup_reading(d):
    for group in d['domains']:
        for item in group['items']:
            if item['id'] in ('F-02', 'F-06', 'F-07'):
                item['gap'] = item['gap'].split(MARKER)[0]+MARKER+STATUS
                item['display_design']['availability'] = item['display_design']['availability'].split(MARKER)[0]+MARKER+STATUS
                item['presentation_contract']['detail_contract'] = item['presentation_contract']['detail_contract'].split(MARKER)[0]+MARKER+STATUS
    for page in d['page_blueprints']:
        if page['id'] == 'P03': page['status'] = page['status'].split(MARKER)[0]+MARKER+STATUS
    for surface in d['framework']['surfaces']:
        if surface.get('href') == '#joint-schedule': surface['status'] = surface['status'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['joint_setup_reading'] = deepcopy(CONTRACT)
    return d
