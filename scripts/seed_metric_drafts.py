"""Create reviewable draft contracts; never auto-approve or overwrite edits."""
import os,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.contrib.auth.models import User
from app.metric_registry import create
from app.models import GovernedMetric
user=User.objects.get(username='demo_admin')
common=dict(change_reason='首次建立模拟指标，待独立业务岗位核对样例后审核。',filters=[])
drafts=[
 ('DELIVERY_OTIF','bi_order_lines',dict(name='按期足量发货率',business_definition='以交付计划行为计数对象，承诺日当天及之前累计发货达到约定量视为按期足量。',purpose='识别交付偏差，进入订单工作台协调逾期对象。',business_owner='销售 / 生产计划',clock='当前导入快照；承诺日早于快照日期的计划才纳入分母，承诺日当天仍可履约。专题日期按下单日选择订单队列；交付工作台另按订单现承诺日筛选，均不重放历史。',unit='%',exclusions='采用发货版，未实现完整签收、取消退货与冻结承诺历史；缺少计划的订单需另查数据质量。',comparison='同承诺口径、产品配置和观察截止点比较；产品族分组的比率按分子分母汇总后相除。',review_role='operations',measure={'agg':'ratio','field':'on_time_plan_count','denominator':'due_plan_count'})),
 ('QUALITY_FIRST_PASS','bi_units',dict(name='首次完整有效检测合格率',business_definition='按装配队列SN，最早有效且完整的检测会话合格计入分子，已有此类检测的SN计入分母。',purpose='识别首检质量差异，配合完整检测覆盖与未检清单复核。',business_owner='质量工程',clock='按装配队列选对象，截至模拟快照读取检测；不是按检测发生日统计的期间检测率。',unit='%',exclusions='无完整有效检测的SN不进入分母，需要同时看检测覆盖率；作废会话排除，复测不会冲掉首败。',comparison='同配置、检验规范版本与样本规模比较；不能把复测合格率替代首检。',review_role='quality',measure={'agg':'ratio','field':'first_pass_count','denominator':'first_tested_count'})),
 ('RESOURCE_OCCUPANCY','bi_resource_day',dict(name='资源排班占用率',business_definition='按独立资源位及日期，将有效占用时长合计除以排班可用时长合计。',purpose='检查排班负荷和资源时间冲突，为计划协调提供证据。',business_owner='生产计划 / 设备',clock='按资源日选期间，跨日事件分摊；范围截至模拟快照。',unit='%',exclusions='资源容量或时间完整性异常时暂停计算；不含尚未接入的实际团队合机与维修人员工时。',comparison='按独立工位和同类工序比较；这是排班占用率，不是OEE。',review_role='operations',measure={'agg':'ratio','field':'busy_minutes','denominator':'available_minutes'})),
 ('RECEIVABLE_BALANCE','bi_receivables',dict(name='已开票未核销余额',business_definition='按发票归集截至快照已核销回款，以含税票面额扣除核销额形成余额。',purpose='核对催收对象与核销缺口，不作为会计收入或现金预测。',business_owner='财务 / 销售',clock='当前快照存量；按开票日选择对象不代表恢复某日历史账龄。',unit='分',exclusions='完整红字冲销、贷项与退货净额未接入；发票不等同收入确认。',comparison='统一人民币整数分；单位换算和跨币种合并需另立口径。',review_role='finance',measure={'agg':'sum','field':'balance_cents'})),
]
created=[]
for key,dataset,payload in drafts:
    if GovernedMetric.objects.filter(key=key).exists():continue
    v=create(user,dict(key=key,dataset=dataset,payload={**common,**payload}));created.append({'key':key,'id':v.id,'status':v.status})
print(json.dumps({'created':created,'policy':'Draft only; existing definitions are never overwritten.'},ensure_ascii=False))
