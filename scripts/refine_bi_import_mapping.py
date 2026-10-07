"""Expose only the verified Excel mapping scope; retain the full W-12 gap."""
from collections import Counter

NEED = 'W-12'
MARKER = '字段映射：'
STATUS = '第32份模拟Excel为异构表头演练文件，未写入主库；采购、销售和仓储按工作表及字段显式映射，支持明确忽略列或整页、必填和重名冲突提示、原生类型样例与历史批次映射复用。映射核对凭据绑定文件、文件名、账号、字段定义、校验规则及映射，15分钟有效；通过仅表示表头核对，随后仍执行完整行级校验和原有审核流程。隔离副本识别15条重复、1条待审核冲突、1条非文本编号错误，备注页明确跳过；原件、原始行、映射和表头核对审计可回查。相同文件与映射可复用原批次，复用不重新逐行校验。主库212466事实及全部旧表未变。受控模板命名与批准版本库、自动字段漂移对照、单位换算、组织范围授权和真实U8/MES仍待建设；浏览器、手机及实际上传下载尚未实测。'
SURFACE = dict(name='Excel字段映射与导入',question='部门表头怎样对应业务字段，哪些列或页需忽略，哪些记录需要审核？',content='原生样例、工作表/字段映射、必填与重复绑定提示、未采用列、映射依据和完整校验批次',action='选择文件→明确业务表和字段→核对映射→进入完整校验批次→检查异常并按原流程审核',href='#imports',status=STATUS)
PRESENTATION = ['来源映射与行级异常分步呈现','表头可对应业务字段，是否意味着全部记录可以提交？','映射阶段并列原表头、目标字段、原生样例和忽略项；进入批次后分别展示重复、冲突、无效及可提交行，保留原文件、原始行和映射核对依据',STATUS]


def refine_import_mapping(d):
    for dom in d['domains']:
        for n in dom['items']:
            if n['id']==NEED:
                n['implementation']='模拟部分覆盖'
                n['decision_spec']['implementation']='模拟部分覆盖'
                n['gap']=n['gap'].split('\n'+MARKER)[0]+'\n'+MARKER+STATUS
    for p in d['page_blueprints']:
        if p['id']=='P15':p['status']=p['status'].split(' '+MARKER)[0]+' '+MARKER+STATUS
    f=d['framework']
    f['surfaces']=[s for s in f['surfaces'] if s['href']!=SURFACE['href']]+[dict(SURFACE)]
    f['presentation']=[p for p in f['presentation'] if p[0]!=PRESENTATION[0]]+[list(PRESENTATION)]
    d['planning_summary']['implementation_counts']=dict(Counter(n['implementation'] for dom in d['domains'] for n in dom['items']))
    return d


def remove_exact_increment(d):
    """Remove the named scope, asserting all original fields outside it remain."""
    for dom in d['domains']:
        for n in dom['items']:
            if n['id']==NEED:
                assert n['implementation']==n['decision_spec']['implementation']=='模拟部分覆盖'
                suffix='\n'+MARKER+STATUS
                assert n['gap'].endswith(suffix)
                n['gap']=n['gap'][:-len(suffix)]
                n['implementation']=n['decision_spec']['implementation']='待建设'
    for p in d['page_blueprints']:
        if p['id']=='P15':
            suffix=' '+MARKER+STATUS
            assert p['status'].endswith(suffix)
            p['status']=p['status'][:-len(suffix)]
    f=d['framework']
    assert [s for s in f['surfaces'] if s['href']==SURFACE['href']]==[SURFACE]
    assert [p for p in f['presentation'] if p[0]==PRESENTATION[0]]==[PRESENTATION]
    f['surfaces']=[s for s in f['surfaces'] if s['href']!=SURFACE['href']]
    f['presentation']=[p for p in f['presentation'] if p[0]!=PRESENTATION[0]]
    d['planning_summary']['implementation_counts']=dict(Counter(n['implementation'] for dom in d['domains'] for n in dom['items']))
    return d
