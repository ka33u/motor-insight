"""H-27 partial synthetic curve capture; no real furnace/recipe certification."""
from collections import Counter
from copy import deepcopy
MARKER=' 固化曲线演练：'
STATUS='已从第43份自编Excel正常导入35条规范、68条通道条件、34个独立炉次、32条装炉声明及1229条离散温度采样。按实际程序/版本、工单配置及路线选唯一条件；核对完整时间区间、通道、单位、序号、采样缺口、全局独立资源位重叠及装炉批次/报工对应。完整曲线分段绘制，保温只按相邻有效点支持的最长连续区间；不插值、补零、外推或合并分离区段。支持同范围炉次筛选、原始采样分页、Excel行来源及CSV/JSON导出。工单订单分配仅为订单线索。传感器校准、温场、工件芯温、真实设备采集、正式工艺判定与放行、浏览器及手机操作尚未验收。'
CONTRACT=dict(revision='curing-discrete-20261007',href='#thermal-curing',state=STATUS,
              definition='炉次仅计一次；相邻有效℃采样、两端均在声明保温范围且间隔符合规范时支持该区间估计。取最长连续区间核对最少分钟，全过程独立核对温度上限。',
              date_contract='筛选按曲线起点日期；曲线时间、采样时间、登记時間和规范有效区间分别核对；合成业务截止2026-10-01 18:00上海墙钟。',
              boundary='炉温不等于工件芯温；离散采样未证明区间内无波动或固化程度。所列条件达到不等于质量合格、工艺批准或生产放行。装载为半成品件数，不合并为整机台数。')
def refine_curing(d):
    for g in d['domains']:
        for n in g['items']:
            if n['id']=='H-27':
                n['implementation']='模拟部分覆盖';n['decision_spec']['implementation']='模拟部分覆盖';n['gap']=n['gap'].split(MARKER)[0]+MARKER+STATUS
                n['display_design']['availability']=STATUS;n['presentation_contract']['detail_contract']=CONTRACT['definition']+' '+STATUS
    d['planning_summary']['implementation_counts']=dict(Counter(n['implementation'] for g in d['domains'] for n in g['items']))
    d['framework']['curing_curves']=deepcopy(CONTRACT)
    d['framework']['surfaces']=[s for s in d['framework']['surfaces'] if s.get('name')!='固化温度曲线']+[dict(href=CONTRACT['href'],name='固化温度曲线',question='哪些装炉批次曲线缺依据或所列条件未达到？',content='炉次队列→装炉对应与订单线索→完整通道曲线→最长支持保温/断点/超温点→原始采样与Excel行',action='核对装炉、规范与采样→找到需工艺及质量复查的批次',status=STATUS)]
    return d
