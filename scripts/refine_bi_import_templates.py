"""Append verified named-template scope without claiming formal business approval."""
MARKER='命名模板：'
STATUS='本地新增模板编码、名称、部门和维护人，映射与样例表头保存为不可覆盖版本；草稿经当前文件重新核对后由维护人明确启用，启用新版本使旧版本停用，停用版本可重新核对恢复。对新文件分别提示新增/缺失工作表及列、改名和顺序变化；只有顺序变化时按名称定位。核对凭据绑定版本内容、模板修订、账号、文件与当前字段/规则，状态或依据变化后拒绝旧凭据；导入批次追加所用版本，旧批次重新校验标为历史引用，不自动重新启用模板。主库登记1个跨部门合成模板及1个启用版本，没有新增业务事实、导入批次或原件授权。隔离副本完整创建、启停、新旧版本、导入提交重放、历史核查，以及40项新增边界检查和1786项全套测试通过。真实部门模板适用性、正式业务审批/签批、单位变更或换算、组织数据范围、多层/合并表头、浏览器/手机/实际上传下载仍待建设或验收；模板启用不证明记录业务正确。'
LEGACY='受控模板命名与批准版本库、自动字段漂移对照、单位换算、组织范围授权和真实U8/MES仍待建设'
HISTORICAL='初始映射阶段尚缺命名模板、版本及字段变化对照；本次模板库增量另列，正式业务审批、单位换算、组织范围授权和真实U8/MES仍待建设'
ROW=['模板版本与字段变化核对','当前文件使用哪个映射版本，表头变化会影响哪些列或页？','按模板编码和维护人列出固定版本、当前启用状态与规则就绪；当前文件逐页对照新增、缺失和顺序变化，进入批次后保留版本及历史引用，启用与业务批准分开',STATUS]


def refine_import_templates(d):
    for dom in d['domains']:
        for n in dom['items']:
            if n['id']=='W-12':n['gap']=n['gap'].split('\n'+MARKER)[0].replace(LEGACY,HISTORICAL)+'\n'+MARKER+STATUS
    for p in d['page_blueprints']:
        if p['id']=='P15':p['status']=p['status'].split(' '+MARKER)[0].replace(LEGACY,HISTORICAL)+' '+MARKER+STATUS
    f=d['framework']
    for s in f['surfaces']:
        if s['href']=='#imports':s['status']=s['status'].split(' '+MARKER)[0].replace(LEGACY,HISTORICAL)+' '+MARKER+STATUS
    for row in f['presentation']:
        if row[0]=='来源映射与行级异常分步呈现':row[3]=row[3].replace(LEGACY,HISTORICAL)
    f['presentation']=[row for row in f['presentation'] if row[0]!=ROW[0]]+[list(ROW)]
    return d


def remove_exact_increment(d):
    for dom in d['domains']:
        for n in dom['items']:
            if n['id']=='W-12':
                suffix='\n'+MARKER+STATUS;assert n['gap'].endswith(suffix)
                n['gap']=n['gap'][:-len(suffix)].replace(HISTORICAL,LEGACY)
    for p in d['page_blueprints']:
        if p['id']=='P15':
            suffix=' '+MARKER+STATUS;assert p['status'].endswith(suffix)
            p['status']=p['status'][:-len(suffix)].replace(HISTORICAL,LEGACY)
    f=d['framework']
    for s in f['surfaces']:
        if s['href']=='#imports':
            suffix=' '+MARKER+STATUS;assert s['status'].endswith(suffix)
            s['status']=s['status'][:-len(suffix)].replace(HISTORICAL,LEGACY)
    for row in f['presentation']:
        if row[0]=='来源映射与行级异常分步呈现':row[3]=row[3].replace(HISTORICAL,LEGACY)
    assert [r for r in f['presentation'] if r[0]==ROW[0]]==[ROW]
    f['presentation']=[r for r in f['presentation'] if r[0]!=ROW[0]]
    return d
