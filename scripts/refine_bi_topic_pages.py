"""One partial presentation capability; preserve every existing requirement identity."""
import copy
from collections import Counter
MARKER=' 个人页面版本编排：'
STATUS='已提供本人页面编码、业务问题、复查节奏、五类阅读分区、原专题全部卡片各一次、半宽/整行、分区/卡片顺序及说明；通过预览保存不可覆盖的版本，可读取历史、导出定义JSON、归档与恢复。真实结果区移动原卡，不重算或改变原模型。导航明确开始新范围或完整继承当前/对照范围、名称及直接身份条件，目标卡不支持或日期角色不一致即暂停，不静默丢条件。原专题/模型/目标/规则或权限变化须核对再另存版本。全部岗位仅编排本人页面，管理员不能读取他人页面；不提升源数据权限。两份合成示例，交付v2与质量v1。仅模拟部分覆盖：服务端、原生HTTP和纯JS检查通过；浏览器、手机、真实键盘与实际下载未验收；团队发布、拖拽、任意跨模型组页、多终端独立布局、订阅和正式批准仍待建设。'
CONTRACT=dict(revision='private-topic-page-versions-20261007',href='#topic-pages',needs=['X-23'],
 definition='BI工作页围绕一个明确业务问题，分别定义阅读职责、原分析卡、范围适用性、证据与复查；页面身份/版本、指标口径/模型版本、数据状态与结果快照分开保存。',
 reading=['明确读者与业务问题','从已有专题选择原分析卡','安排主结果、解释、对象、依据、复查分区','预览全部卡片与权限占位','保存本人页面新版本','应用原范围看当前结果与来源','核对条件后导航到下一专题','处理后复查或另存结果快照'],
 layout='五种分区、1—8区、原专题1—12卡各一次、全部主结果最多3卡，半宽/整行；不可用原卡保留占位，不隐藏不利结果。标题和说明不改变算法、样本、单位、固定条件或日期角色。',
 navigation='每页至多8个可见目标；明确开始新范围会重置日期、对照、标签和身份条件。继承须全部目标卡支持所有两侧条件与身份；有日期时还须日期角色一致。目标定义变化、旧读取凭据或权限异常暂停。',
 versions='本人唯一编码固定到原专题；预览核对当时原专题、所有模型、目标专题与规则；保存追加不可覆盖版本和依据。重复同操作编号复用，修订竞争暂停；历史布局运行仍读当前事实，结果快照另存。',
 permission='本人私有；六类岗位可编排，只复用当前可访问原卡。未知/停用/冲突岗位拒绝；不授予金额、人员或原件读取权，不形成团队发布。',
 examples=[dict(owner='demo_analyst',code='PAGE.DELIVERY.DAILY.0001',topic_id=15,version=2),dict(owner='demo_admin',code='PAGE.QUALITY.DAILY.0001',topic_id=4,version=1)],
 boundary='全部业务数值继续来自已导入合成Excel；页面定义JSON不含经营结果。浏览器/手机/实际下载未验收，团队批准/共享/订阅/跨模型任意组页和终端独立设计未实现。',state=STATUS)
ROW=dict(name='个人专题页面',question='这个工作页回答什么问题，先看哪张卡，下一页是否能完整继承条件？',content=CONTRACT['layout'],action='业务问题→原专题→阅读分区→预览→不可覆盖版本→原结果/来源→条件核对导航→复查',href='#topic-pages',status=STATUS)
def counts(d):return dict(Counter(i['implementation'] for g in d['domains'] for i in g['items']))
def refine_pages(d):
 for g in d['domains']:
  for n in g['items']:
   if n['id']=='X-23':n['implementation']='模拟部分覆盖';n['decision_spec']['implementation']='模拟部分覆盖';n['gap']=n['gap'].split(MARKER)[0]+MARKER+STATUS
 for p in d['page_blueprints']:
  if p['id']=='P15':p['status']=p['status'].split(MARKER)[0]+MARKER+STATUS
 d['framework']['topic_page_composition']=copy.deepcopy(CONTRACT);d['framework']['surfaces']=[r for r in d['framework']['surfaces'] if r['href']!=ROW['href']]+[copy.deepcopy(ROW)];d['planning_summary']['implementation_counts']=counts(d);return d
def remove_pages(d):
 d['framework'].pop('topic_page_composition',None);d['framework']['surfaces']=[r for r in d['framework']['surfaces'] if r['href']!=ROW['href']]
 for g in d['domains']:
  for n in g['items']:
   if n['id']=='X-23':n['implementation']='待建设';n['decision_spec']['implementation']='待建设';n['gap']=n['gap'].split(MARKER)[0]
 for p in d['page_blueprints']:
  if p['id']=='P15':p['status']=p['status'].split(MARKER)[0]
 # Restore the recorded parent's summary exactly; its counts lagged two prior partial increments.
 d['planning_summary']['implementation_counts']={'模拟部分覆盖':114,'待建设':268};return d
