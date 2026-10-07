"""Create deterministic Excel input only; never mutate imported records."""
import os,sys,json,copy
from pathlib import Path
from datetime import date,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app.analytics import AS_OF
def records(ds):return list(Record.objects.filter(dataset=ds).order_by('business_key').values_list('values',flat=True))
quotes=[q for q in records('quotes') if int(q['id'].split('-')[-1])<=300]
products=records('products');customers=records('customers');orders={r['id']:r for r in records('orders')};lines={r['id']:r for r in records('order_lines')}
staff=sorted(r['id'] for r in records('employees') if r['department_id']=='D02' and r['active'])
tables={'quotes':[],'quote_details':[],'quote_order_links':[],'quote_tasks':[]};targets={}
# This mapping reconstructs the documented synthetic generator's explicit
# even-line identities. Runtime BI never guesses links from number patterns.
for q in quotes:
    idx=int(q['id'].split('-')[-1]);o=idx//2-1;oid=f'SO202609{10+o%10:02}{o+1:04}';line=lines[oid+'-002'];order=orders[oid]
    assert (q['customer_id'],q['product_id'],q['qty'])==(order['customer_id'],line['product_id'],line['qty'])
    targets[q['id']]=line
odd_lines=sorted([r for r in lines.values() if r['id'].endswith('-001')],key=lambda x:x['id'])[:6]
for i in range(1,61):
    number=300+i;key=f'BJ2609-{number:05d}'
    if i<=6:
        line=odd_lines[i-1];order=orders[line['order_id']];p=next(x for x in products if x['id']==line['product_id'])
        q=dict(id=key,customer_id=order['customer_id'],product_id=p['id'],qty=line['qty']+5,unit_price_cents=p['price_cents'],quote_date='2026-09-06',valid_until='2026-10-15',status='部分转单',reason='首批数量已形成订单，余量仍待客户释放（模拟）');targets[key]=line
    else:
        p=products[(i*5)%len(products)];customer=customers[(i*7)%len(customers)]
        status='跟进中' if i<=24 else '待技术确认' if i<=36 else '已失单' if i<=48 else '客户暂停'
        reason={'跟进中':'等待客户商务反馈','待技术确认':'安装及轴伸要求尚未冻结','已失单':['客户项目取消','客户另选方案','交期条件未达成'][i%3],'客户暂停':'客户项目暂缓，重新启动时间未确认'}[status]
        quoted=date(2026,9,20+i%10)
        q=dict(id=key,customer_id=customer['id'],product_id=p['id'],qty=[5,10,15,20,30][i%5],unit_price_cents=p['price_cents']*[96,100,104][i%3]//100,quote_date=quoted.isoformat(),valid_until='2026-09-30' if i%3==0 else '2026-10-15',status=status,reason=reason+'（模拟）')
    tables['quotes'].append(q)
all_quotes=quotes+tables['quotes']
for i,q in enumerate(all_quotes,1):
    quoted=date.fromisoformat(q['quote_date']);line=targets.get(q['id']);order=orders[line['order_id']] if line else None
    owner=order['owner_id'] if order else staff[i%len(staff)]
    outcome=order['order_date'] if order else (quoted+timedelta(days=2)).isoformat() if q['status']=='已失单' else None
    # One current metadata record per quote. No undocumented revision history.
    tables['quote_details'].append(dict(id=f'BJDA26-{i:05d}',quote_id=q['id'],owner_id=owner,inquiry_date=(quoted-timedelta(days=1+i%4)).isoformat(),inquiry_no=f'XJ26-{i:05d}',channel=['老客户复购','设备配套询价','业务拜访','网站询价'][i%4],currency='CNY',tax_basis='待确认' if i in [177,184,205] else '未税',version='V1',outcome_date=outcome,requirement='核对安装方式、轴伸尺寸、接线位置、交期和付款条件；模拟资料未附客户签章原件'))
    if line:
        tables['quote_order_links'].append(dict(id=f'BJGL26-{i:05d}',quote_id=q['id'],order_line_id=line['id'],qty=line['qty'],confirmed=order['order_date'],status='有效',reference=order['customer_po']+'；按既有模拟订单事实登记对应关系，非客户原件核验'))
    if i<=150:
        ended=date.fromisoformat(order['order_date'])
        tables['quote_tasks'].append(dict(id=f'BJRW26-{i:05d}-01',quote_id=q['id'],owner_id=owner,created=q['quote_date'],kind='订单关联核对',due=ended.isoformat(),completed=ended.isoformat(),status='已完成',description='登记报价与明确订单行及对应数量',result='模拟对应关系已登记，客户原件仍待归档'))
    else:
        for j,kind in [(1,'技术条件核对'),(2,'商务回访')]:
            due=quoted+timedelta(days=1 if j==1 else 4+i%6)
            done=q['status']=='已失单' or j==1 and q['status']!='待技术确认'
            completed=quoted+timedelta(days=1 if j==1 else 2) if done else None
            tables['quote_tasks'].append(dict(id=f'BJRW26-{i:05d}-{j:02d}',quote_id=q['id'],owner_id=owner,created=q['quote_date'],kind=kind,due=due.isoformat(),completed=completed.isoformat() if completed else None,status='已完成' if completed else '待反馈',description='确认安装、轴伸及附件要求' if j==1 else '跟进余量释放' if q['status']=='部分转单' else '确认商务反馈、有效期或项目恢复条件',result='模拟回访已登记；不代表正式技术或商务批准' if done else None))
schemas={k:copy.deepcopy(SCHEMAS[k]) for k in tables}
# Workbook packaging can combine incremental facts from an existing dataset.
# The canonical quotes schema remains in department 03 inside the application.
schemas['quotes']['department']='16_销售报价过程'
out={'notice':'全部为合成演练。新增60条报价并补充210条商务资料、156条明确订单关联和270条跟进任务。原150条报价和订单保持不变；关联依据按既有模拟生成规则及客户/配置/数量核对。报价为配置行粒度，商务资料声明价税口径；任务完成不等于成交，未附客户签章原件。','as_of':AS_OF,'schema_version':1,'schemas':schemas,'tables':tables}
(ROOT/'data/sales_scenario.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({k:len(v) for k,v in tables.items()},ensure_ascii=False))
