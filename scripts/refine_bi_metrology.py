"""Only the source-backed metrology subset is labelled partially covered."""
from collections import Counter

NEEDS={'P-04','P-05'}
PAGES={'P05','P06','P08','P10','P15'}
STATUS='第30份模拟Excel通过正常导入新增6表44,253条计量登记，对应已有43,782条终检/来料/工序特性读数；136个显式通道与14个未建立历史使用的原工具档案分开。测量时的校准登记适用、原检测结论、明确/起点未知的影响范围及核查登记分别显示；异常最新版本不回退，区间左闭右开，未知/作废/不需校准分开。按业务与登记截止核查，支持同一源测量的晚登记对照、完整版本、原Excel来源和范围一致的CSV接口；独立原始台账核对三个时点组合，API权限、来源、过滤与导出通过。候选订单与明确发运关系分开，核查摘要绑定原测量和所引版本，依据更正需重新核查。全部是合成登记；未取得真实校准证书、实验室认可、测量不确定度、现场使用确认或受控应检总体。未发布K55，未代替检测判定、产品放行、隔离、召回或正式处置。外校送返、替代排程、MSA、真实接口、浏览器渲染、手机和实际下载仍待建设或验收。'
def refine_metrology(d):
    for domain in d['domains']:
        for n in domain['items']:
            if n['id'] in NEEDS:
                n['implementation']='模拟部分覆盖'
                n['gap']=n['gap'].split('\n计量登记：')[0]+'\n计量登记：'+STATUS
                n['decision_spec']['implementation']=n['implementation']
    for page in d['page_blueprints']:
        if page['id'] in PAGES:page['status']=page['status'].split(' 计量登记：')[0]+' 计量登记：'+STATUS
    f=d['framework']
    f['surfaces']=[s for s in f['surfaces'] if s['href']!='#metrology']+[dict(name='计量校准与影响核查',question='测量当时有哪些登记依据，哪些原记录命中已登记失准范围？',content='测量粒度、两种截止、分母与未知、环节趋势、仪器通道、版本、原件、对象及订单关系',action='选择测量范围→核对适用登记与影响→查原测量和完整版本→人工核查→复查依据变化',href='#metrology',status=STATUS)]
    f['presentation']=[p for p in f['presentation'] if p[0]!='原检测、计量登记与核查并列']+[['原检测、计量登记与核查并列','检测合格记录是否仍需核查其仪器依据？','有效源测量和模拟需校准分母并列；校准登记适用、影响命中、起点未知、待核定及核查独立。原结论保持原值，不能把登记适用率当作应检覆盖或整机合格率',STATUS]]
    f['content_design_note']='目录记录展示设计及经过验证的模拟部分覆盖；63项建议口径仍须业务审定。原生页面的登记分析只说明所列来源与边界，不自动发布正式指标或业务批准。'
    for c in f['domain_data_contracts']:
        if c['code']=='P':c['source_status']='6类计量模拟Excel台账已导入，原工具档案与新增显式通道分开；真实证书、现场身份及U8/MES来源待核实'
    d['planning_summary']['implementation_counts']=dict(Counter(n['implementation'] for dom in d['domains'] for n in dom['items']))
    return d
