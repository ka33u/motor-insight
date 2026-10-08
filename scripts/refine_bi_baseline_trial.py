"""Conditional job-specific frozen BOM scheduling, without approval claims."""
from copy import deepcopy
from collections import Counter
MARKER = ' 冻结BOM假设试排：'
STATUS = ('按逐批冻结BOM单耗、损耗及步长计算需求，同型号不同批次可使用不同声明版本，共享供给、人员、设备及时间窗口。'
          '整批未开工门槛核对当前订单/分配范围、截止发货、跨订单分配、装配/报工以及完整关联领料流水；有领料或未知退料不净额抵消。'
          '保留原基线核对和当前BOM算法，两侧可算才对照需求，双方均完成才比较时间；原始来源变化使旧凭据失效。'
          '来源摘要仅证明快照自洽，历史完整性/业务批准未核实；缺单位或路线依据暂停。三岗位可查看批次、人机甘特、物料/预留及来源并导出完整假设。'
          '未登记不证明实际未开工；不写回库存、派工、整单承诺或正式审批。浏览器、手机、键盘及实际下载仍未验收。')
CONTRACT = dict(revision='baseline-bom-conditional-20261008', href='#order-baselines?view=trial', state=STATUS,
               definition='基线系列与版本 × 批次 × 冻结快照行；共享供给按物料和单位。需求逐行向上取整，不能先按产品合并BOM版本。',
               arithmetic='ceil(安排台数 × 冻结单耗 × (1+损耗) / 步长) × 步长；保持Decimal至序列化。冻结减当前，双方完整排入才有完成时间差。',
               presentation='条件边界与硬门槛→基线订单覆盖→当前/冻结同策略对照→全部批次→人机甘特/任务→物料需求/余额/FIFO流水→字段差异/来源/完整导出。',
               boundary='只有声明集合的条件试算，history_verified始终false；不证明历史BOM完整、已核准或可投产。当前用料集合增删可作条件差异，执行身份、单位、路线及当前整批范围不能含混。')

def refine_baseline_trial(d):
    for group in d['domains']:
        for item in group['items']:
            if item['id'] == 'P-06' and not item['display_design']['object_and_evidence'].endswith(item['action']):
                item['display_design']['object_and_evidence'] += ' → '+item['action']
            if item['id'] in ('E-01', 'F-03', 'F-06', 'F-10'):
                item['gap'] = item['gap'].split(MARKER)[0]+MARKER+STATUS
    for page in d['page_blueprints']:
        if page['id'] in ('P02', 'P03', 'P07'):
            page['status'] = page['status'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['baseline_bom_conditional'] = deepcopy(CONTRACT)
    d['framework']['surfaces'] = [s for s in d['framework']['surfaces'] if s.get('name') != '基线BOM假设试排']+[
        dict(name='基线BOM假设试排', href=CONTRACT['href'], question='使用不同批次声明的冻结用料后，共享物料与人机能否共同安排？', content=CONTRACT['presentation'],
             action='核对整批范围与历史登记→查看条件试排→逐任务和快照行复核→交业务评审', status=STATUS)]
    counts = dict(Counter(n['implementation'] for g in d['domains'] for n in g['items']))
    d['planning_summary']['presentation_design']['coverage_counts'] = counts
    return d
