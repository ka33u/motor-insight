"""X-21 private navigation increment; no source model or fact edits."""
from collections import Counter
from copy import deepcopy
MARKER=' 个人工作台：'
STATUS='已提供每账号独立的工作台：收藏系统页面、分析模型、专题、本人视角、本人专题页面、本人口径卡和编码规则。支持本人别名、分组、组内与分组顺序，以及工作台或可用收藏作为无指定地址时的登录入口。读取和打开时重新检查当前账号权限、目标存在与定义绑定；需核对项进入原核对流程，不可用项暂停，失效登录入口回到工作台。相同目标去重、最多100项、配置修订冲突须刷新；不改变共享默认值或业务资料。不保存临时筛选、结果、原件授权或访问统计，常用范围须先保存个人专题视角。对象收藏、共享工作台、订阅提醒、实际岗位、浏览器及手机交互仍待验收或建设。'
CONTRACT=dict(revision='personal-workbench-20261008',href='#workbench',state=STATUS,
 definition='收藏是本人目标引用、别名、工作分组、顺序和登录偏好；结果仍按原页面当前口径和当前可见资料计算，不是历史快照。',
 presentation='工作分组→目标类型、当前名称、状态与版本→打开或核对→原页面范围、结果、对象与Excel来源。',
 boundary='七类固定内部目标，不保存任意URL。个人范围仅通过已有视角保存与重核。其他账号的个人视角、页面和口径卡不出现在目录；配置变更按现有管理员审计权限留痕。')
def refine_workbench(d):
    for group in d['domains']:
        for item in group['items']:
            if item['id']=='X-21':
                item['implementation']='模拟部分覆盖';item['decision_spec']['implementation']='模拟部分覆盖'
                item['gap']=item['gap'].split(MARKER)[0]+MARKER+STATUS
                item['display_design']['availability']=STATUS
                item['presentation_contract']['detail_contract']=CONTRACT['definition']+' '+STATUS
    d['planning_summary']['implementation_counts']=dict(Counter(n['implementation'] for g in d['domains'] for n in g['items']))
    d['framework']['personal_workbench']=deepcopy(CONTRACT)
    d['framework']['surfaces']=[s for s in d['framework']['surfaces'] if s.get('name')!='我的工作台']+[dict(href='#workbench',name='我的工作台',question='今天常用哪些已保存分析与核查入口，哪些需要先重核？',content=CONTRACT['presentation'],action='按工作步骤分组→打开可用入口或核对失效依据→在原页继续核查',status=STATUS)]
    return d
