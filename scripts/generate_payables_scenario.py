"""Deterministic supplier documents, written to XLSX before any import."""
import os,sys,json
from collections import defaultdict
from datetime import date,timedelta
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.schema import SCHEMAS
KEYS=['purchase_terms','ap_invoices','ap_invoice_lines','ap_payments','ap_payment_plans','ap_allocations','ap_adjustments']
def rounded(x):return int(Decimal(x).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def generate(raw):
    data={k:[] for k in KEYS};pos={p['id']:p for p in raw['purchase_lines']}
    finance=[r for r in raw['employees'] if r.get('role')=='财务专员' and r.get('active')]
    if not finance:raise ValueError('模拟付款安排需已有财务岗位人员')
    for i,p in enumerate(sorted(pos.values(),key=lambda x:x['id']),1):
        data['purchase_terms'].append(dict(id=f'CGYS-2609-{i:05d}',purchase_line_id=p['id'],currency='CNY',price_basis='未税',tax_bps=1300,confirmed=p['ordered'],reference='模拟采购双方约定：采购单价为CNY未税价，13%仅为本演练设定'))
    grouped=defaultdict(list);extras=defaultdict(list)
    receipts=sorted([r for r in raw['receipts'] if r['received'][:10]<='2026-09-27'],key=lambda r:r['id'])[:112]
    for i,r in enumerate(receipts):
        sid=pos[r['purchase_line_id']]['supplier_id'];qty=Decimal(str(r['qty']))
        if i%10==0:
            first=qty*Decimal('0.6');grouped[sid].append((r,first));extras[sid].append((r,qty-first))
        else:grouped[sid].append((r,qty*(Decimal('0.5') if i%9==0 else 1)))
    allocations_by_supplier=defaultdict(list);credits={};reversals={};invoice_index={};seq=0;line_seq=0
    for sid,items in sorted(grouped.items()):
        items+=extras[sid]
        for offset in range(0,len(items),2):
            seq+=1;key=f'YFFP2609-{seq:06d}';chunk=items[offset:offset+2]
            issued=max('2026-09-24',max(r['received'][:10] for r,_ in chunk));posted=(date.fromisoformat(issued)+timedelta(days=1)).isoformat()
            status='草稿' if seq%23==0 else '已确认'
            if seq%19==0:posted='2026-10-05'
            due=(date.fromisoformat(issued)+timedelta(days=[3,7,12,20][seq%4])).isoformat()
            inv=dict(id=key,supplier_id=sid,invoice_no=f'SIM-VAT-2609-{seq:07d}',currency='CNY',issued=issued,posted=posted,due=due,net_cents=0,tax_cents=0,status=status,reference='模拟供应商发票及应付确认；不是真实税票')
            for receipt,qty in chunk:
                line_seq+=1;po=pos[receipt['purchase_line_id']];price=po['unit_price_cents']+(10 if seq%17==0 else 0);net=rounded(qty*price);tax=rounded(Decimal(net)*Decimal('0.13'))
                data['ap_invoice_lines'].append(dict(id=f'YFMX2609-{line_seq:06d}',invoice_id=key,receipt_id=receipt['id'],qty=float(qty),unit_price_cents=price,tax_bps=1300,net_cents=net,tax_cents=tax,reference='模拟供应商调价，采购价税差异待核对' if seq%17==0 else '模拟到货与供应商发票逐行关联'))
                inv['net_cents']+=net;inv['tax_cents']+=tax
            data['ap_invoices'].append(inv);invoice_index[key]=inv;gross=inv['net_cents']+inv['tax_cents'];credits[key]=0;reversals[key]=0
            if status!='已确认' or posted>'2026-10-01':continue
            case=seq%8
            if case==3:
                credit=gross//10;credits[key]=credit
                data['ap_adjustments'].append(dict(id=f'YFTZ2609-{len(data["ap_adjustments"])+1:06d}',invoice_id=key,occurred='2026-09-28',kind='贷项冲减',delta_cents=-credit,allocation_id=None,status='已过账',document_no=f'SIM-DX-2609-{seq:06d}',reason='模拟结算折让；不改变实际到货数量，不等同退料'))
            amount=gross if case==2 else gross//2 if case in [1,4,7] else gross//5 if case==3 else gross//3 if case in [5,6] else 0
            if amount:allocations_by_supplier[(sid,'future' if case==5 else 'draft' if case==6 else 'current')].append((key,amount,seq))
    for (sid,mode),items in sorted(allocations_by_supplier.items()):
        for offset in range(0,len(items),2):
            chunk=items[offset:offset+2];i=len(data['ap_payments'])+1;key=f'FKDJ2609-{i:06d}';paid='2026-10-05' if mode=='future' else '2026-09-29';total=sum(a for _,a,_ in chunk)
            data['ap_payments'].append(dict(id=key,supplier_id=sid,currency='CNY',paid=paid,amount_cents=total+(total//5 if i%4==0 else 0),status='草稿' if mode=='draft' else '已付款',document_no=f'SIM-FKPZ-{i:06d}',method='模拟转账登记',reference='合成付款凭据，供跨票核销及未核销金额演练；非银行流水'))
            for invoice,amount,seq in chunk:
                aid=f'FKHX2609-{len(data["ap_allocations"])+1:06d}'
                data['ap_allocations'].append(dict(id=aid,payment_id=key,invoice_id=invoice,occurred=paid,amount_cents=amount,status='草稿' if mode=='draft' else '已核销',plan_id=None,reference='模拟一笔付款按指定金额核销发票'))
                if seq%8==4 and mode=='current':
                    rev=amount//2;reversals[invoice]+=rev
                    data['ap_adjustments'].append(dict(id=f'YFTZ2609-{len(data["ap_adjustments"])+1:06d}',invoice_id=invoice,occurred='2026-09-30',kind='核销冲回',delta_cents=rev,allocation_id=aid,status='已过账',document_no=f'SIM-HXCH-{seq:06d}',reason='模拟部分核销关系冲回，资金仍在付款登记中，转回未核销金额；不是银行退款'))
    for i,inv in enumerate(data['ap_invoices'],1):
        if inv['status']!='已确认' or inv['posted']>'2026-10-01':continue
        gross=inv['net_cents']+inv['tax_cents'];allocs=[a for a in data['ap_allocations'] if a['invoice_id']==inv['id'] and a['status']=='已核销' and a['occurred']<='2026-10-01']
        net=sum(a['amount_cents'] for a in allocs)-reversals[inv['id']];balance=gross-credits[inv['id']]-net
        cases=[(gross-credits[inv['id']],True)] if i%3 else [(max(balance,1),False)]
        if i%11==0 and balance>1:cases=[(balance//2,True),(balance-balance//2,True)];allocs=[]
        for j,(amount,approved) in enumerate(cases):
            key=f'FKAP2610-{len(data["ap_payment_plans"])+1:06d}';created=inv['posted'];planned='2026-09-28' if i%5==0 else ['2026-10-04','2026-10-08','2026-10-15'][i%3]
            if i%11==0:created='2026-10-01';planned=['2026-10-08','2026-10-15'][j]
            data['ap_payment_plans'].append(dict(id=key,invoice_id=inv['id'],created=created,planned=planned,amount_cents=amount,status='已批准' if approved else '待审批',approved=created if approved else None,owner_id=finance[i%len(finance)]['id'],reference='模拟分期付款安排' if i%11==0 else '模拟已批准安排，仅供与核销对照，不执行付款' if approved else '模拟待审批申请，不计入已批准安排'))
            if approved:
                for a in allocs:a['plan_id']=key
    return {'schema_version':1,'as_of':'2026-10-01','seed':20261004,'notice':'全部为合成模拟数据。采购价税约定、供应商发票、付款、核销、贷项、冲回和付款安排分别记录。仅已确认或已过账且不晚于截止日的事实进入余额；计划不抵减应付，核销冲回不是银行退款。13%为演练约定，不作为实际税务规则。',
            'schemas':{k:SCHEMAS[k] for k in KEYS},'tables':data}
if __name__=='__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    import django;django.setup()
    from app.models import Record
    raw={k:list(Record.objects.filter(dataset=k).order_by('business_key').values_list('values',flat=True)) for k in ['suppliers','purchase_lines','receipts','materials','employees']}
    result=generate(raw);dest=ROOT/'data/payables_scenario.json';dest.write_text(json.dumps(result,ensure_ascii=False,indent=2));print({k:len(v) for k,v in result['tables'].items()})
