"""Deterministic synthetic cutover AR; JSON is workbook input, never DB input."""
import os,sys,json,random
from datetime import date,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.schema import SCHEMAS

SEED=2026100301
def generate(customers):
    rng=random.Random(SEED);opening=[];events=[];seq=0
    due_dates=['2026-03-20','2026-05-10','2026-07-15','2026-08-15','2026-09-15','2026-10-01','2026-10-15']
    def event(row,day,kind,value,status='已过账',reverses=None):
        nonlocal seq
        seq+=1;key=f'YS{day[2:4]}{day[5:7]}-{seq:06d}'
        item=dict(id=key,opening_id=row['id'],occurred=day,kind=kind,delta_cents=value,document_no=f'PZ-{day.replace("-","")}-{seq:05d}',reverses_id=reverses,status=status,reason='模拟'+kind+'；用于余额、账龄及冲回关系核对')
        events.append(item);return item
    for i in range(1,43):
        due=date.fromisoformat(due_dates[(i-1)%len(due_dates)]);issued=min(due-timedelta(days=60),date(2026,8,20))
        gross=rng.randrange(18000,160000)*100;balance=gross if i%3 else gross*2//3
        r=dict(id=f'QCYS-260901-{i:05d}',customer_id=customers[(i-1)%len(customers)],document_no=f'LSFP{issued:%y%m}-{i:05d}',issued=issued.isoformat(),due=due.isoformat(),as_of='2026-09-01',currency='CNY',original_gross_cents=gross,opening_balance_cents=balance,note='模拟9月1日零时未核销余额；原单全额仅供核对，期初前已核销不计入本期收款')
        opening.append(r)
        # Seven recurring cases span all due-date buckets and retain excluded events.
        case=(i+(i-1)//7)%7
        if case==1:event(r,'2026-09-05','收款核销',-(balance//3))
        elif case==2:event(r,'2026-09-12','收款核销',-balance)
        elif case==3:
            event(r,'2026-09-08','贷项冲减',-(balance//10))
            event(r,'2026-09-20','收款核销',-(balance//4))
        elif case==4:
            paid=event(r,'2026-09-10','收款核销',-(balance//2))
            event(r,'2026-09-18','核销冲回',-paid['delta_cents'],reverses=paid['id'])
            event(r,'2026-09-29','收款核销',-(balance//5))
        elif case==5:event(r,'2026-10-05','收款核销',-balance)
        elif case==6:
            event(r,'2026-09-15','贷项冲减',-(balance//6),status='草稿')
            event(r,'2026-09-16','收款核销',-(balance//4),status='已撤销')
    return {'schema_version':1,'as_of':'2026-10-01','seed':SEED,
            'notice':'全部为合成模拟数据。期初是2026-09-01零时余额，事件按日记录，不表示日内时点。仅已过账且不晚于截止日的事件参与余额。收款及贷项为负数，核销冲回为正数并引用原收款。不代表银行流水、财务结账或真实欠款。',
            'schemas':{k:SCHEMAS[k] for k in ['ar_opening','ar_events']},'tables':{'ar_opening':opening,'ar_events':events}}

if __name__=='__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    import django;django.setup()
    from app.models import Record
    customers=list(Record.objects.filter(dataset='customers').order_by('business_key').values_list('business_key',flat=True))[:18]
    if len(customers)<18:raise RuntimeError('请先导入基础客户档案')
    data=generate(customers);dest=ROOT/'data/ar_history_scenario.json';dest.write_text(json.dumps(data,ensure_ascii=False,indent=2))
    print(json.dumps({'file':str(dest),'seed':SEED,'tables':{k:len(v) for k,v in data['tables'].items()}},ensure_ascii=False))
