"""Record the delivered synthetic pre-start review without promoting whole needs."""
from copy import deepcopy
MARKER = ' 投产条件核对补充：'
NEEDS = ('E-02', 'F-08', 'P-02', 'P-08', 'P-10')
STATUS = ('新增独立合成投产核对：按批次工序明确工装、文件和质量条件，缺行暂停；对照固定试排的完整换型加工区间、工装设备适配、版本、到期、次数与预占。'
          '展示满足、阻断、资料不足及前序影响；整方案预算不随任务筛选重算，支持来源与导出。'
          '仅补足登记核对环节，不代表相应完整需求完成；真实原件审阅、新试排工单首件实测、工装借还与批准派工、自动重排、浏览器和手机验收仍待完成。')
CONTRACT = dict(revision='launch-review-20261007', href='#launch-review', needs=list(NEEDS), state=STATUS,
 definition='订单基线×试排批次×工序的三类条件矩阵；逐任务份号核对时间与计次。漏列不等于不需要，显式不适用须有依据。',
 time='沿用固定试排时间；登记不得晚于资料截止，有效窗口覆盖完整换型与加工，区间左闭右开，工装台账到期日按00:00失效。',
 capacity='同一物理工装跨任务独占，外部借用/停用窗口排除；每台计次按任务数量累计，预计累计不能超过维护阈值。按任务起点和编号保守分配，不搜索全局最优替代。',
 evidence='工装配置/工序/设备/版本，文件配置/工序/版本及状态，质量条件工单/工序/版本分别核对；缺资料与限制开工分开，前序未满足向后传播。',
 presentation='整方案摘要→批次与订单→可筛选任务条件矩阵→原因与直接Excel依据→跨任务工装占用与次数→完整来源和CSV/JSON。',
 boundary='资料满足不等于现场开工许可。其他条件受阻仍保留已分配工装的保守预算；未匹配需求不计作零。文件编号不证明原件已验证，开工质量登记不是首件实测或整机放行。不写回计划或库存，不自动重排。')


def refine_launch(d):
    for domain in d['domains']:
        for n in domain['items']:
            if n['id'] in NEEDS: n['gap']=n['gap'].split(MARKER)[0]+MARKER+STATUS
    for page in d['page_blueprints']:
        page['status']=page['status'].split(MARKER)[0]
        if page['id'] in ('P03','P07','P10'):page['status']+=MARKER+STATUS
    d['framework']['launch_review']=deepcopy(CONTRACT)
    d['framework']['surfaces']=[s for s in d['framework']['surfaces'] if s['href']!='#launch-review']+[dict(name='投产条件核对',question='试排任务还缺哪些工装、文件或质量开工依据？',content=CONTRACT['presentation'],action='定位资料、版本、占用或维护缺口，交责任岗位核对后重新读取',href='#launch-review',status=STATUS)]
    return d
