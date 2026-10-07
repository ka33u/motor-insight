"""Read-only reconciliation of imported supplier data and preserved prior results."""
import os,sys,json,csv,io,hashlib,sqlite3,tempfile,zipfile,copy
from pathlib import Path
from collections import defaultdict
from decimal import Decimal,ROUND_HALF_UP
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.db import connection
from django.contrib.auth.models import User
from django.test import RequestFactory
from django.urls import resolve
from app.models import Record,AnalysisModel,TopicSnapshot,ImportBatch,IssueDisposition,AuditEvent
from app import payables
from app.analysis_engine import run_analysis
from app.views import archived_import_path
from app.trace_cases import capture_sources
with connection.cursor() as cursor:cursor.execute('PRAGMA query_only=ON')
sha=lambda b:hashlib.sha256(b).hexdigest()
expected=json.loads((ROOT/'data/payables_scenario.json').read_text())['tables']
for ds,rows in expected.items():
 assert list(Record.objects.filter(dataset=ds).order_by('business_key').values_list('values',flat=True))==sorted(rows,key=lambda r:r['id']),ds
baseline_dir=Path(tempfile.mkdtemp(prefix='motor-ap-baseline-'))
with zipfile.ZipFile(ROOT/'data/backups/motor-backup-20261004-173726.zip') as z:(baseline_dir/'before.sqlite3').write_bytes(z.read('data/platform.sqlite3'))
before=sqlite3.connect(baseline_dir/'before.sqlite3');now=sqlite3.connect(f'file:{ROOT}/data/platform.sqlite3?mode=ro',uri=True)
old=before.execute('SELECT * FROM app_record ORDER BY id').fetchall();current={r[0]:r for r in now.execute('SELECT * FROM app_record')}
assert all(current[r[0]]==r for r in old)
changed_allowed={'app_record','app_importbatch','app_importrow','app_auditevent','app_issuedisposition','django_session'}
preserved=[]
for (table,) in before.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
 if table in changed_allowed:continue
 a=sorted(before.execute(f'SELECT * FROM "{table}"').fetchall(),key=repr);b=sorted(now.execute(f'SELECT * FROM "{table}"').fetchall(),key=repr)
 assert a==b,table;preserved.append(table)
user=User.objects.get(username='demo_admin')
def strip_revision(value):
 if isinstance(value,dict):return {k:strip_revision(v) for k,v in value.items() if k!='revision'}
 if isinstance(value,list):return [strip_revision(v) for v in value]
 return value
old_models=json.loads((ROOT/'data/payables_before.json').read_text())
for model in AnalysisModel.objects.order_by('pk'):
 value=json.loads(json.dumps(run_analysis(user,model.dataset,model.definition),ensure_ascii=False,default=str))
 assert strip_revision(old_models[str(model.pk)])==strip_revision(value),model.pk
# Independent arithmetic from raw rows: only this fixed synthetic scenario, not a second production engine.
tables=defaultdict(list)
for ds,v in Record.objects.values_list('dataset','values'):tables[ds].append(v)
cut='2026-10-01';invoices={r['id']:r for r in tables['ap_invoices'] if r['status']=='已确认' and r['posted']<=cut}
payments={r['id']:r for r in tables['ap_payments'] if r['status']=='已付款' and r['paid']<=cut}
allocs={r['id']:r for r in tables['ap_allocations'] if r['status']=='已核销' and r['occurred']<=cut and r['invoice_id'] in invoices and r['payment_id'] in payments}
credits=defaultdict(int);reversals=defaultdict(int)
for r in tables['ap_adjustments']:
 if r['status']=='已过账' and r['occurred']<=cut and r['invoice_id'] in invoices:
  if r['kind']=='贷项冲减':credits[r['invoice_id']]-=r['delta_cents']
  elif r['allocation_id'] in allocs:reversals[r['allocation_id']]+=r['delta_cents']
net={k:r['amount_cents']-reversals[k] for k,r in allocs.items()}
balances={k:r['net_cents']+r['tax_cents']-sum(net[a] for a,v in allocs.items() if v['invoice_id']==k)-credits[k] for k,r in invoices.items()}
unallocated={k:r['amount_cents']-sum(net[a] for a,v in allocs.items() if v['payment_id']==k) for k,r in payments.items()}
plans={r['id']:r for r in tables['ap_payment_plans'] if r['status']=='已批准' and r['approved']<=cut and r['created']<=cut and r['invoice_id'] in invoices}
remaining={k:r['amount_cents']-sum(net[a] for a,v in allocs.items() if v.get('plan_id')==k) for k,r in plans.items()}
billed=defaultdict(Decimal)
for r in tables['ap_invoice_lines']:
 if r['invoice_id'] in invoices:billed[r['receipt_id']]+=Decimal(str(r['qty']))
purchases={r['id']:r for r in tables['purchase_lines']};materials={r['id']:r for r in tables['materials']};reference={};units=defaultdict(lambda:[Decimal(0),Decimal(0)])
for r in tables['receipts']:
 qty=Decimal(str(r['qty']));gap=qty-billed[r['id']];po=purchases[r['purchase_line_id']];u=materials[r['material_id']]['unit'];units[u][0]+=qty;units[u][1]+=gap
 reference[r['id']]=int((gap*Decimal(po['unit_price_cents'])).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
d=payables.current();assert not d.global_issues
for kind,raw,key in [('invoices',balances,'balance_cents'),('payments',unallocated,'unallocated_cents'),('plans',remaining,'remaining_cents'),('receipts',reference,'reference_net_cents')]:
 actual=getattr(d,kind);assert {k:r[key] for k,r in actual.items() if r[key] is not None}==raw,kind
summaries={tab:payables.summary(list(getattr(d,tab).values()),tab) for tab in payables.TABS}
factory=RequestFactory();api_checks={}
for tab in payables.TABS:
 req=factory.get('/api/payables',{'tab':tab});req.user=user;resp=resolve('/api/payables').func(req);assert resp.status_code==200
 payload=json.loads(resp.content);assert payload['summary']==summaries[tab];api_checks[tab]=payload['total']
 if tab=='invoices':assert sum(x['balance_cents'] or 0 for x in payload['aging'])==sum(balances.values())
 if tab=='plans':assert sum(x['remaining_cents'] for x in payload['schedule'])==sum(remaining.values())
batch=ImportBatch.objects.get(filename='19_供应商应付_模拟.xlsx');original=archived_import_path(batch);assert sha(original.read_bytes())==batch.file_hash
assert sha((Path('/Users/zhangyu/Downloads')/batch.filename).read_bytes())==batch.file_hash
source_count=0
for kind in payables.TABS:
 for obj in getattr(d,kind).values():
  sources=capture_sources({'sources':obj['sources']})
  for r in sources:assert not r.get('missing'),(kind,obj['id'],r)
  source_count+=len(sources)
exports={}
for tab in payables.TABS:
 file=Path('/Users/zhangyu/Downloads')/f'payables-{tab}.csv';rows=list(csv.reader(io.StringIO(file.read_text(encoding='utf-8-sig'))));header=rows[3];data=rows[4:];assert len(data)==len(getattr(d,tab))
 values={row[0]:row for row in data};key={'invoices':'已核对余额分','payments':'已核对未核销分','plans':'可核对未执行分','receipts':'按约定未税参考额分'}[tab]
 index=header.index(key);raw={'invoices':balances,'payments':unallocated,'plans':remaining,'receipts':reference}[tab]
 for k,v in raw.items():assert int(values[k][index])==v,(tab,k)
 target=ROOT/'outputs'/f'供应商对账_{tab}.csv';target.write_bytes(file.read_bytes());exports[tab]={'rows':len(data),'sha256':sha(file.read_bytes())}
file=Path('/Users/zhangyu/Downloads/payables-invoices (1).csv');rows=list(csv.reader(io.StringIO(file.read_text(encoding='utf-8-sig'))));assert len(rows[4:])==16;assert sum(int(x[12]) for x in rows[4:])==37789403
(ROOT/'outputs/供应商对账_逾期1至30天.csv').write_bytes(file.read_bytes())
follow=IssueDisposition.objects.get(key='ap:invoices:YFFP2609-000017');assert follow.status=='待采购确认' and follow.version==1
assert AuditEvent.objects.filter(action='payable.followup',object_id=follow.key).count()==1
out=dict(records=Record.objects.count(),old_records_preserved=len(old),added_records=sum(len(r) for r in expected.values()),datasets=len(tables),preserved_tables=preserved,models_preserved=len(old_models),snapshots={str(s.pk):s.payload_hash for s in TopicSnapshot.objects.all()},independent_reconciliation=True,summaries=summaries,api_counts=api_checks,source_references_checked=source_count,workbook_sha256=batch.file_hash,batch=str(batch.pk),browser_csv=exports,aging_export_rows=16,follow_up=dict(key=follow.key,status=follow.status,version=follow.version),synthetic_only=True)
(ROOT/'data/payables_validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in out.items() if k not in ['summaries','preserved_tables','snapshots','browser_csv']},ensure_ascii=False))
