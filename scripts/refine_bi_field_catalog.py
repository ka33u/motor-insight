"""Reversible presentation metadata for existing permission-scoped field contracts."""
MARKER='字段字典：'
STATUS='本地BI字段字典按当前账号列出全部可访问数据集与字段，支持数据集/业务名称或编码/字段类型/单位状态联合查找、每页25字段、同范围CSV/JSON和逐字段说明；自由分析可查看当前数据集契约。展示原主键、类型、必填、关联目标、粒度、日期及筛选能力，明确固定、每行、未声明和非数值单位，区分单价/配置参数、余额时点、登记工时及其中加班的合计边界；仅元数据，不含业务记录。采用现有派生/散点单位约定，补充销售交付/发货台数和班次五类小时的说明；单位提示不启用新公式或重写原字段契约。专题摘要核对单位说明，交付/发货/登记工时可显示原数值与单位，库存/采购仍不混单位。字段导出重新核对说明算法、全目录契约、范围与当前账号；权限变化或陈旧依据暂停。已核对全部字段、分页与同范围导出、六岗位可见性和既有模型专题；无主数据审批、跨系统映射、指标别名/分类/使用位置完整词典、字段级责任人及变更评审。真实U8/MES、浏览器/手机/实际下载仍未验收。'
ROW=['BI字段字典与建模提示','选择字段前，怎样核对单位、日期、身份及汇总边界？','当前权限目录 → 联合查找 → 字段契约 → 现有分析编辑器查看 → 同范围字段说明导出',STATUS]
SURFACE=dict(href='#field-catalog',name='BI字段字典',audience='业务分析、数据负责人及有数据访问权岗位',question='字段代表什么，单位和来源粒度是否允许当前分析？',content='字段身份、类型、必填、关联、日期、单位状态和汇总边界，当前权限下联合查找',action='建模前查看字段说明，按同范围导出契约并复核未知单位',status=STATUS)
IDS={'W-04','X-09','X-28'}
def refine_field_catalog(d):
 for dom in d['domains']:
  for n in dom['items']:
   if n['id'] in IDS:n['gap']=n['gap'].split('\n'+MARKER)[0]+'\n'+MARKER+STATUS
 for p in d['page_blueprints']:
  if p['id']=='P15':p['status']=p['status'].split(' '+MARKER)[0]+' '+MARKER+STATUS
 f=d['framework'];f['presentation']=[r for r in f['presentation'] if r[0]!=ROW[0]]+[list(ROW)]
 f['surfaces']=[r for r in f['surfaces'] if r['href']!=SURFACE['href']]+[dict(SURFACE)]
 return d

def remove_exact_increment(d):
 for dom in d['domains']:
  for n in dom['items']:
   if n['id'] in IDS:
    suffix='\n'+MARKER+STATUS;assert n['gap'].endswith(suffix);n['gap']=n['gap'][:-len(suffix)]
 for p in d['page_blueprints']:
  if p['id']=='P15':
   suffix=' '+MARKER+STATUS;assert p['status'].endswith(suffix);p['status']=p['status'][:-len(suffix)]
 f=d['framework'];assert [r for r in f['presentation'] if r[0]==ROW[0]]==[ROW];f['presentation']=[r for r in f['presentation'] if r[0]!=ROW[0]]
 assert [s for s in f['surfaces'] if s['href']==SURFACE['href']]==[SURFACE];f['surfaces']=[s for s in f['surfaces'] if s['href']!=SURFACE['href']]
 return d
