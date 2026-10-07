"""Expose verified synthetic certificate evidence without certifying a KPI."""
NEEDS = {'P-04','P-05'}
PAGES = {'P05','P06','P10','P15'}
MARKER = '校准原件：'
STATUS = '第31份模拟Excel通过正常导入新增260份证明台账和264条关联版本；259份模拟CSV/TXT原件已正常归档，默认私有，主库未自动授权。按仪器通道展示原件关联、声明/原件内容核对及独立到期队列；支持业务与登记截止、1—365自然日关注窗口、完整关联版本、Excel行来源和同范围CSV接口。136个显式通道与14个未建立历史使用的工具档案分开；未知、无需校准、到期、原校准异常与原件资料问题分别呈现。当前账号权限与物理完整性按读取时间检查，不能解释为历史已归档。原件一致不证明真实证书、实验室能力或测量有效；保留原校准登记、检测结论和失准核查，不发布K55或代替放行。逐字段Excel往返、正常导入幂等、三组时点的独立台账、权限/撤销/篡改/陈旧依据接口检查通过；浏览器、手机和实际下载尚未实测。真实PDF/OCR、签章、认可范围、不确定度、MSA、送校周转、现场使用、真实U8/MES及正式批准仍待建设或核实。'
SURFACE = dict(name='校准证书与到期',question='哪些仪器将到期，哪些登记缺少可核查原件，当前账号能核对哪些内容？',content='仪器通道、自然日关注窗口、原校准状态、原件资料状态、声明/内容、版本及Excel来源',action='选择时点与窗口→分清到期及资料问题→核查当前关联与原件→追到Excel→由计量岗位安排核查',href='#metrology-evidence',status=STATUS)
PRESENTATION = ['到期与原件核查分别呈现','有校准登记，是否有当前可读取且内容一致的原件？','按仪器通道展示到期队列，资料状态独立；详情对照校准登记、证明声明和原件内容。到期关注窗口由读者选择，不当作批准校准周期或自动停用指令',STATUS]
SOURCE_SUFFIX = '；另有2类模拟校准原件台账及259份模拟原件，真实证书内容和能力待现场核实'


def refine_metrology_evidence(d):
    for dom in d['domains']:
        for n in dom['items']:
            if n['id'] in NEEDS:
                n['gap']=n['gap'].split('\n'+MARKER)[0]+'\n'+MARKER+STATUS
    for p in d['page_blueprints']:
        if p['id'] in PAGES:
            p['status']=p['status'].split(' '+MARKER)[0]+' '+MARKER+STATUS
    f=d['framework']
    f['surfaces']=[s for s in f['surfaces'] if s['href']!=SURFACE['href']]+[dict(SURFACE)]
    f['presentation']=[p for p in f['presentation'] if p[0]!=PRESENTATION[0]]+[list(PRESENTATION)]
    for c in f['domain_data_contracts']:
        if c['code']=='P':
            c['source_status']=c['source_status'].split(SOURCE_SUFFIX)[0]+SOURCE_SUFFIX
    return d


def remove_exact_increment(d):
    """Undo only this enumerated increment to compare with the prior catalog."""
    for dom in d['domains']:
        for n in dom['items']:
            if n['id'] in NEEDS:
                suffix='\n'+MARKER+STATUS
                assert n['gap'].endswith(suffix),n['id']
                n['gap']=n['gap'][:-len(suffix)]
        if dom['code']=='P':
            c=dom['decision_session']['data_contract']
            assert c['source_status'].endswith(SOURCE_SUFFIX)
            c['source_status']=c['source_status'][:-len(SOURCE_SUFFIX)]
    for p in d['page_blueprints']:
        if p['id'] in PAGES:
            suffix=' '+MARKER+STATUS
            assert p['status'].endswith(suffix),p['id']
            p['status']=p['status'][:-len(suffix)]
    f=d['framework']
    assert [s for s in f['surfaces'] if s['href']==SURFACE['href']]==[SURFACE]
    assert [p for p in f['presentation'] if p[0]==PRESENTATION[0]]==[PRESENTATION]
    f['surfaces']=[s for s in f['surfaces'] if s['href']!=SURFACE['href']]
    f['presentation']=[p for p in f['presentation'] if p[0]!=PRESENTATION[0]]
    for c in f['domain_data_contracts']:
        if c['code']=='P':
            assert c['source_status'].endswith(SOURCE_SUFFIX)
            c['source_status']=c['source_status'][:-len(SOURCE_SUFFIX)]
    return d
