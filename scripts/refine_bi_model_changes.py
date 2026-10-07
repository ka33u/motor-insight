"""Document the verified model-update preflight without claiming release approval."""
from collections import Counter
from copy import deepcopy
MARKER=' 模型更新预演：'
STATUS='自由分析更新已有模型前，先并列原定义与候选定义、同一明确范围的独立试算、完整来源摘要及可见依赖。按同一数据集对象主键区分共同、新增纳入和移除，可分页核对Excel行；跨数据集不强行配对。列当前可访问专题和本人视角、口径卡、页面及快照，其他人的私有资料和数量不列。凭据绑定账号、配置、当前资料与依赖；填写依据并确认后原子增加模型版本及定义记录，重复申请复用。旧快照及绑定保留，变更后需重核。尚不提供跨部门发布审批、订阅通知、任意规则预演或历史数值回放；浏览器、手机交互未验收。'
CONTRACT=dict(revision='model-change-preview-20261007',href='#analysis',state=STATUS,
 definition='候选模型与当前模型在同一份当前资料上独立计算，核对定义、样本与下游使用；配置差异不是经营改善或因果结论，保存不是指标认证或业务批准。',
 presentation='新旧定义→各自粒度/日期与全部来源摘要→同类型对象纳入变化→分页来源→依赖及待重核项→变更依据与确认→定义历史。',
 boundary='仅管理员或模型所属分析员更新。预演范围不写入模型；不兼容范围明确暂停。当前流程开始后追加历史，不补造旧版，不保存本次试算数字，不自动恢复或迁移个人绑定。通用模型保存立即产生当前新版本；正式发布流程仍待建设。')

def refine_changes(d):
    for domain in d['domains']:
        for need in domain['items']:
            if need['id'] in ('X-08','X-40'):
                need['gap']=need['gap'].split(MARKER)[0]+MARKER+STATUS
            if need['id']=='X-40':
                need['implementation']='模拟部分覆盖';need['decision_spec']['implementation']='模拟部分覆盖'
    d['planning_summary']['implementation_counts']=dict(Counter(n['implementation'] for g in d['domains'] for n in g['items']))
    d['framework']['model_change_preview']=deepcopy(CONTRACT)
    row=dict(href='#analysis',name='模型更新预演',question='修改口径会改变哪些数值、对象范围和下游使用？',content=CONTRACT['presentation'],action='对照定义与来源→核对依赖→明确依据保存→重核已有绑定',status=STATUS)
    d['framework']['surfaces']=[s for s in d['framework']['surfaces'] if s.get('name')!='模型更新预演']+[row]
    return d
