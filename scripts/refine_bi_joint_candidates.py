"""Candidate inspection is evidence navigation, not a new scheduling algorithm."""
from copy import deepcopy
MARKER=' 候选人机依据：'
STATUS=('物料人机联立任务详情展开当前任务全部候选设备及批量上限、人员资格登记/假设/有效交集、双方原输入窗口和不可用段。'
        '直接前序和原算法传播的首个阻断任务按完整编号可继续读取，同一凭据约束方案、策略、输入、账号及候选展示定义。'
        '补齐未选中候选及窗口的Excel来源；完整导出可零数据库查询复原同一候选依据。'
        '批量符合、资格交集可用、窗口登记和本次选中分别呈现；不计算新的可开工时间或剩余容量，不推荐替换人机，不改原排程、预留或审批。'
        '19项新增服务端、13组纯JS及六岗位HTTP已验证；浏览器、手机、键盘和实际下载仍未验收。')
CONTRACT=dict(revision='joint-candidates-20261008',href='#joint-schedule',state=STATUS,
              definition='以当前试排任务号确定资源候选、人员候选和关联窗口；使用原资格计算结果及原任务依赖，不按姓名、型号或相似文本匹配。',
              presentation='任务状态与原阻断→候选设备批量上限→候选资格交集→可展开的双方窗口/不可用段→前序与首个阻断任务→完整直接来源。',
              boundary='输入窗口未扣其他任务和不可用段，也未裁剪到试排范围；符合单一条件不证明人机物料同时可用。首个阻断是算法传播结果，不等于现场根因。')

def refine_candidates(d):
    for group in d['domains']:
        for item in group['items']:
            if item['id'] in ('F-02','F-06','F-07','Q-02'):
                item['gap']=item['gap'].split(MARKER)[0]+MARKER+STATUS
    for page in d['page_blueprints']:
        if page['id'] in ('P03','P10'):page['status']=page['status'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['joint_candidate_evidence']=deepcopy(CONTRACT)
    for surface in d['framework']['surfaces']:
        if surface.get('href')=='#joint-schedule':surface['status']=surface['status'].split(MARKER)[0]+MARKER+STATUS
    return d
