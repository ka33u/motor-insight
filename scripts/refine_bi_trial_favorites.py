"""Add typed trial navigation to the existing personal workbench contract."""
from copy import deepcopy
MARKER=' 方案收藏：'
STATUS=('个人工作台新增资源、人机、物料联立及订单基线方案收藏；明确保存单策略、两策略对照或冻结BOM试排阅读方式。'
        '入口解析保留原方案编号，目录按现有目标岗位权限分页，打开重新核对记录和来源完整性；展示当前名称、声明版本与记录修订，本人别名不被覆盖。'
        '支持原有分组排序、登录入口、重复与修订冲突、移除和失权/删除回退。仅存本库内部定位，不复制临时凭据、结果或局部筛选；当前可打开不代表方案可排或正式批准。'
        '原七类收藏保持，新增第八类；初始化不预设个人收藏。完整数据库重建后内部定位不能跨库搬用。浏览器、手机、键盘与真实岗位试用仍未验收。')
CONTRACT=dict(revision='workbench-trial-favorites-v1',href='#workbench',state=STATUS,
 definition='本人工作台目标=方案族＋本库记录号＋阅读方式；原业务编号在打开时由当前方案记录解析，校验来源身份。',
 presentation='添加试排与基线方案或收藏已选方案→本人别名和分组→当前名称/版本/状态→原方案当前计算与Excel依据。',
 boundary='四类方案、两种策略，物料联立可两列对照，订单基线可冻结BOM试排。无任意URL、共享配置、结果快照、审批、派工、计算缓存或自动采用方案。')
def refine_trial_favorites(d):
 for group in d['domains']:
  for item in group['items']:
   if item['id']=='X-21':
    item['gap']=item['gap'].split(MARKER)[0]+MARKER+STATUS
    item['display_design']['availability']=item['display_design']['availability'].split(MARKER)[0]+MARKER+STATUS
    item['presentation_contract']['detail_contract']=item['presentation_contract']['detail_contract'].split(MARKER)[0]+MARKER+STATUS
 for page in d['page_blueprints']:
  if page['id'] in ('P03','P15'):page['status']=page['status'].split(MARKER)[0]+MARKER+STATUS
 for surface in d['framework']['surfaces']:
  if surface.get('href')=='#workbench':surface['status']=surface['status'].split(MARKER)[0]+MARKER+STATUS
 c=d['framework']['personal_workbench'];c['state']=c['state'].split(MARKER)[0]+MARKER+STATUS
 c['boundary']=c['boundary'].replace('七类固定内部目标','八类固定内部目标（含试排与基线方案）')
 d['framework']['workbench_trial_favorites']=deepcopy(CONTRACT)
 return d
