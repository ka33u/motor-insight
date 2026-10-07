"""Describe private definition cards without promoting any coverage status."""
import copy
MARKER=' 个人模型口径卡说明：'
NEEDS=('X-07','X-08','X-10')
STATUS='新增本人模型编码、业务问题、岗位、对象粒度/时间说明、解释边界、可选复查日期和不可覆盖的定义版本。绑定当时通用模型、指定指标与分组版本、数据集契约和规则摘要；定义依据变化时当前分析暂停，重新核对后另存新版本。自由分析保存后可登记，专题按共同模型编号列本人相关口径卡，不继承专题临时日期或联动筛选。读取当前模拟数据，不冻结历史结果；说明文字不改变计算筛选。支持历史JSON、归档/重新启用、重复申请复用及当前权限核查，管理员也不能读他人卡。正式跨部门口径审批、团队共享、订阅和任意查询仍待建设；浏览器、手机及实际下载未验收。'
CONTRACT=dict(revision='private-model-definition-cards-20261007',needs=list(NEEDS),href='#model-cards',
 objects='需求→来源事实/维度→指标→分析模型→专题→当前结果或单独结果快照→复查',
 definitions='个人唯一编码、名称、业务问题、岗位、对象粒度说明、时间范围说明、解释边界、可选复查日期；指定模型、指标、分组与契约/规则版本',
 presentation='列表状态→业务口径卡→登记/当前定义对照→历史版本→当前数据结果→原自由分析中的图表及来源；专题显示本人相关卡',
 privacy='本人私有；按当前源模型及字段权限核对；专题不授予读取权，管理员不例外',
 time='资料截止2026-10-01T18:00:00；复查日期按该模拟业务日期解释；当前数据执行，不复原历史事实',
 boundaries='卡片说明不改变模型实际筛选或对象粒度；保存定义不保存结果；专题日期/联动不自动用于卡片单独运行；不代替正式指标发布',
 examples=[dict(code='MODEL.ORDER.OTIF.0001',owner='demo_analyst',model_id=44,metric='DELIVERY_OTIF v8'),dict(code='MODEL.UNIT.POWER.0001',owner='demo_admin',model_id=47,grouping='固定功率分组 v1')],
 state=STATUS)
ROW=dict(name='个人模型口径卡',question='这个模型回答什么问题，登记的算法依据与当前是否一致？',content=CONTRACT['presentation'],action='先保存分析模型→读取当前定义→登记口径→版本核对→运行当前数据与追查来源',href='#model-cards',status=STATUS)
def refine_cards(d):
 for g in d['domains']:
  for n in g['items']:
   if n['id'] in NEEDS:n['gap']=n['gap'].split(MARKER)[0]+MARKER+STATUS
 for p in d['page_blueprints']:
  if p['id']=='P15':p['status']=p['status'].split(MARKER)[0]+MARKER+STATUS
 d['framework']['model_cards']=copy.deepcopy(CONTRACT)
 d['framework']['surfaces']=[r for r in d['framework']['surfaces'] if r['href']!=ROW['href']]+[copy.deepcopy(ROW)]
 return d
def remove_exact_cards(d):
 assert d['framework'].pop('model_cards')==CONTRACT
 assert [r for r in d['framework']['surfaces'] if r['href']==ROW['href']]==[ROW]
 d['framework']['surfaces']=[r for r in d['framework']['surfaces'] if r['href']!=ROW['href']];suffix=MARKER+STATUS
 for g in d['domains']:
  for n in g['items']:
   if n['id'] in NEEDS:assert n['gap'].endswith(suffix);n['gap']=n['gap'][:-len(suffix)]
 for p in d['page_blueprints']:
  if p['id']=='P15':assert p['status'].endswith(suffix);p['status']=p['status'][:-len(suffix)]
 return d
