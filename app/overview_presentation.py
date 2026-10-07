"""Reading priorities change presentation, never metric definitions or access."""
from . import access,issue_workspace

PRESETS={
 'management':dict(label='经营管理',question='交付是否可靠，质量和数据证据是否支持结论？',primary=['otif','late','fpy']),
 'production':dict(label='生产计划',question='装配、检测与待交队列哪里需要协调？',primary=['produced','shipped','late']),
 'quality':dict(label='质量试验',question='检测是否完整，哪些判定与放行依据需要核对？',primary=['coverage','fpy','produced']),
 'finance':dict(label='财务关注',question='已导入发票与回款支持怎样的资金判断？',primary=['shipped','otif','late']),
 'read':dict(label='业务阅读',question='当前快照的业务进度与证据缺口是什么？',primary=['produced','shipped','coverage']),
}
DEFAULTS={'admin':'management','analyst':'management','operations':'production','quality':'quality','finance':'finance','viewer':'read'}
BOUNDARY='首页六项指标沿用总览 v1 的独立队列定义，不等同已发布模型或指标版本；切换关注点只调整展示顺序。异常入口采用质量页有效检测/放行核对规则，同一对象可有多个观察，不相加为台数。'

def build(user,query):
    if set(query)-{'family','preset'} or hasattr(query,'getlist') and any(len(query.getlist(k))!=1 for k in query):raise ValueError('首页筛选未知或重复')
    family=query.get('family','');preset=query.get('preset','') or DEFAULTS[access.role(user)]
    choices={k:v for k,v in PRESETS.items() if k!='finance' or access.can_money(user)}
    if preset not in choices:raise ValueError('该关注点不可用')
    work=issue_workspace.Workspace(user,issue_workspace.filters({'family':family}))
    return dict(preset=preset,**choices[preset],choices=[{'key':k,'label':v['label']} for k,v in choices.items()],
        boundary=BOUNDARY,kind_counts=work.board(1)['kind_counts'],scope=work.filters,notice=issue_workspace.NOTICE)
