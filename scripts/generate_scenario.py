"""Deterministic synthetic factory, emitted as workbook-authoring inputs.

No operational imports may consume this JSON directly. The ingestion seed path
must read the exported XLSX files and retain workbook/sheet/row provenance.
"""
import json, random, sys, math
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import defaultdict, Counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.schema import SCHEMAS
from scripts.scenario_calendar import work_order_plan
R=random.Random(20261002)
DATA={k:[] for k in SCHEMAS}
AS_OF=datetime(2026,10,1,18)
def dt(v): return v.isoformat(timespec='seconds') if isinstance(v,datetime) else v.isoformat()
def add(key,**row):
    schema=SCHEMAS[key]
    for field in schema['fields']:
        if not field['required']:row.setdefault(field['name'],None)
    actual=set(row); expected={c['name'] for c in schema['fields']}
    assert actual==expected,(key,expected-actual,actual-expected)
    DATA[key].append(row);return row
def byid(k):return {x['id']:x for x in DATA[k]}

dept_names=['经营管理','销售','研发工艺','生产计划','冲片车间','机加工车间','绕组车间','装配车间','质量试验','采购','仓储物流','设备维护','人事行政','财务','能源安环','售后服务']
for i,name in enumerate(dept_names,1):add('departments',id=f'D{i:02}',name=name,owner=name+'负责人')
for i in range(1,193):
    d=(i-1)%16+1
    add('employees',id=f'E{i:05}',name=f'模拟员工{i:03}',department_id=f'D{d:02}',role=dept_names[d-1]+'专员' if d not in [5,6,7,8] else '操作员',skill_level=R.choice(['初级','中级','高级']),hourly_cents=R.randrange(2200,6800,100),active=True)
staff=lambda dept:R.choice([r['id'] for r in DATA['employees'] if r['department_id']==f'D{dept:02}'])
for i in range(1,31):
    add('customers',id=f'KH{i:05}',name=f'{R.choice(["华东","江南","北方","海川","中原"])}{R.choice(["泵业","机械","风机","环保","装备"])}{i:02}（模拟）',region=R.choice(['华东','华南','华北','西南']),industry=R.choice(['水泵','风机','压缩机','输送设备','环保设备']),payment_days=R.choice([30,45,60,90]),owner_id=staff(2))
for i in range(1,19):add('suppliers',id=f'GY{i:05}',name=f'模拟工业供应商{i:02}',category=['硅钢','铜线','轴承','铝材','漆料','机加工件'][i%6],region=R.choice(['江苏','浙江','山东','广东']),lead_days=R.choice([5,7,10,15,21]),qualified=True)
mat_groups=[('01.01','无取向硅钢','硅钢','50W470','kg',720),('01.02','漆包铜线','铜线','QZ-2/155','kg',7850),('02.01','深沟球轴承','轴承','6205-2Z','件',1850),('02.02','电机轴','轴','45钢精磨','件',2600),('03.01','绝缘漆','漆料','无溶剂浸渍漆','kg',2450),('03.02','机壳','壳体','铸铁机座','件',6500),('04.01','绝缘材料','绝缘','DMD绝缘纸','kg',3200),('04.02','铝锭','铝材','电工铝','kg',2050)]
for group,name,cat,spec,unit,cost in mat_groups:
 for i in range(1,7):add('materials',id=f'{group}.{i:04}',name=f'{name}-{i:02}',category=cat,spec=f'{spec}/{i:02}',unit=unit,unit_cost_cents=cost+i*20,supplier_id=f'GY{((i+len(DATA["materials"]))%18)+1:05}',safety_qty=200 if unit=='kg' else 80)
power_values=[0.75,1.5,2.2,3,5.5,7.5,11,15]
for i in range(48):
    family=['YE3','YE4','YVF2'][i//16];p=power_values[i%8];frame=['80M','90L','100L','112M','132S','132M','160M','160L'][i%8];poles=[2,4,6][i%3]
    add('products',id=f'CP.{i+1:05}.A',model=f'{family}-{frame}-{poles}',family=family,power_kw=p,voltage=380 if i%5 else 660,poles=poles,frame=frame,mounting='B3' if i%2 else 'B5',protection='IP55',insulation='F',bom_version='A.02' if i%7==0 else 'A.01',route_version='GY-A.01',drawing=f'DJ-{i+1:05}-A',price_cents=int(55000+p*28000)*(115 if family=='YE4' else 100)//100,standard_hours=round(0.8+p*0.075,3))
processes=[('冲片','冲片车间',5),('叠压','冲片车间',5),('机加工','机加工车间',6),('绕线嵌线','绕组车间',7),('浸漆固化','绕组车间',7),('动平衡','机加工车间',6),('装配','装配车间',8),('终检','质量试验',9),('包装','仓储物流',11)]
for pi,(process,shop,dep) in enumerate(processes):
 for n in range(1,4):add('equipment',id=f'SB-{pi+1:02}-{n:02}',name=f'{process}{n}号设备',workshop=shop,process=process,model=f'MODEL-{pi+1:02}-{n}',commissioned=f'202{n}-03-15',status='运行' if n<3 or pi%3 else '待保养',owner_id=staff(dep))
eq=lambda process:R.choice([e['id'] for e in DATA['equipment'] if e['process']==process])
material_for={}
for i,p in enumerate(DATA['products']):
    material_for[p['id']]=[]
    for gi,(group,name,cat,spec,unit,cost) in enumerate(mat_groups):
        mid=f'{group}.{i%6+1:04}'; qty=round((1.8+p['power_kw']*0.8) if cat=='硅钢' else (0.35+p['power_kw']*0.2) if cat=='铜线' else 2 if cat=='轴承' else 1 if unit=='件' else 0.12+p['power_kw']*0.02,3)
        material_for[p['id']].append((mid,qty))
        add('bom',id=f'BOM-{i+1:05}-{gi+1:02}',product_id=p['id'],material_id=mid,version=p['bom_version'],qty=qty,scrap_allowance=0.035 if cat=='硅钢' else 0.015,effective='2026-09-01')
    for seq,(process,shop,dep) in enumerate(processes,1):add('routes',id=f'GY-{i+1:05}-{seq:02}',product_id=p['id'],version=p['route_version'],sequence=seq,process=process,workshop=shop,minutes=round(p['standard_hours']*60/[9,10,8][i%3],2),mandatory=True)
    if i<14:add('projects',id=f'RD2026-{i+1:03}',name=f'{p["model"]}定制验证',product_id=p['id'],owner_id=staff(3),planned_end=f'2026-09-{16+i:02}',actual_end=f'2026-09-{17+i:02}' if i<9 else None,status='已转产' if i<9 else '验证中',budget_cents=R.randrange(800000,3500000,10000))
    if i%7==0:add('engineering_changes',id=f'ECN2609-{i+1:03}',product_id=p['id'],from_version='A.01',to_version='A.02',reason='接线盒位置与客户安装空间调整',effective='2026-09-01',approved_by=staff(3),status='已批准')

# Purchasing, inspected lots and quantity-balanced warehouse opening/movements.
lots={};materials=byid('materials')
for mi,m in enumerate(DATA['materials']):
    lot=f'{"CU" if m["category"]=="铜线" else "RM"}260831{mi+1:04}';lots[m['id']]=lot
    opening=100000 if m['unit']=='kg' else 10000
    add('inventory_opening',id=f'QC260901-{mi+1:04}',material_id=m['id'],lot=lot,location=f'CK01-A{mi%8+1:02}-{mi//8+1:02}',as_of='2026-09-01',qty=opening,unit_cost_cents=m['unit_cost_cents'],status='冻结' if mi==47 else '可用')
    if mi==47:add('inventory_status_events',id='ZT260918-00001',material_id=m['id'],lot=lot,location=f'CK01-A{mi%8+1:02}-{mi//8+1:02}',occurred='2026-09-18T07:30:00',from_status='冻结',to_status='可用',reason='期初冻结批次补充材质文件，经质量复核批准解冻（模拟）',approver_id='E00009')
    for j in range(3):
        n=mi*3+j+1;pk=f'PO2609-{n:05}-01';quantity=1000 if m['unit']=='kg' else 200
        add('purchase_lines',id=pk,supplier_id=m['supplier_id'],material_id=m['id'],ordered=f'2026-09-{5+j:02}',due=f'2026-09-{17+j:02}',qty=quantity,unit_price_cents=m['unit_cost_cents']+R.choice([-10,0,20]),status='未到货' if n%13==0 else '已到货')
        if n%13==0:continue
        received=datetime(2026,9,17+j+(2 if n%7==0 else 0),9)
        rid=f'DH2609-{n:05}'; rlot=f'RM{received:%y%m%d}{n:05}';bad=n%17==0
        add('receipts',id=rid,purchase_line_id=pk,material_id=m['id'],lot=rlot,qty=quantity,received=dt(received),certificate=f'CZ-2609-{n:05}',status='隔离' if bad else '检验合格')
        add('incoming_inspections',id=f'IQC2609-{n:05}',receipt_id=rid,sample_size=20,defect_count=3 if bad else 0,inspected=dt(received+timedelta(hours=3)),result='不合格' if bad else '合格',inspector_id=staff(9),disposition='隔离待退货' if bad else '批准入库')
        if not bad:add('inventory_movements',id=f'RK2609-{n:05}',material_id=m['id'],lot=rlot,location=f'CK01-A{mi%8+1:02}-{mi//8+1:02}',occurred=dt(received+timedelta(hours=4)),movement='采购入库',qty_signed=quantity,work_order_id=None,reference=rid)

products=byid('products'); order_line_to_wo={};wo_to_line={};plan_for={};produced=0;unit_by_wo=defaultdict(list);sessions_by_unit=defaultdict(list)
for o in range(150):
    oid=f'SO202609{10+o%10:02}{o+1:04}';customer=f'KH{o%30+1:05}'
    add('orders',id=oid,customer_id=customer,order_date=f'2026-09-{10+o%10:02}',owner_id=staff(2),currency='CNY',status='执行中',customer_po=f'KPO-26-{o+1:05}')
    for line in [1,2]:
        idx=o*2+line; p=DATA['products'][(idx*7)%48];qty=[15,20,25,30][idx%4];due=date(2026,9,23)+timedelta(days=idx%16);original=due-timedelta(days=2) if idx%19==0 else due
        lid=f'{oid}-{line:03}';wo=f'MO2609-{idx:06}';order_line_to_wo[lid]=wo;wo_to_line[wo]=lid
        add('order_lines',id=lid,order_id=oid,product_id=p['id'],qty=qty,unit_price_cents=int(p['price_cents']*R.choice([.94,.98,1,1.03])),original_due=dt(original),due=dt(due),change_reason='客户批准延后' if due!=original else None,custom_requirement=R.choice(['标准配置','接线盒旋转90度','特殊轴伸','客户指定轴承','加长引线','铭牌双语']))
        parts=[qty//2,qty-qty//2] if idx%9==0 else [qty]
        plan_for[lid]=[]
        for pi,pqty in enumerate(parts,1):
            plan=f'JH-{idx:06}-{pi:02}';plan_for[lid].append(plan)
            add('delivery_plans',id=plan,order_line_id=lid,qty=pqty,due=dt(due+timedelta(days=pi-1)),version=1)
        actual_qty=min(qty,max(0,4500-produced));unitdate=date(2026,9,21)+timedelta(days=produced//900)
        planned_start,planned_end=work_order_plan(unitdate,due)
        add('work_orders',id=wo,product_id=p['id'],planned_qty=qty,planned_start=dt(planned_start),planned_end=dt(planned_end),priority='紧急' if idx%17==0 else '普通',status='未开工' if not actual_qty else '执行中',bom_version=p['bom_version'],route_version=p['route_version'])
        add('allocations',id=f'FP-{idx:06}',work_order_id=wo,order_line_id=lid,qty=qty,effective=f'2026-09-{10+o%10:02}')
        if idx%2==0:add('quotes',id=f'BJ2609-{idx:05}',customer_id=customer,product_id=p['id'],qty=qty,unit_price_cents=p['price_cents'],quote_date=f'2026-09-{3+idx%7:02}',valid_until='2026-10-15',status='已转订单',reason='技术与交期已确认')
        if not actual_qty:continue
        bstart=datetime.combine(unitdate-timedelta(days=3),datetime.min.time()).replace(hour=8)
        st=f'DZ{unitdate:%y%m%d}{idx:04}';rot=f'ZZ{unitdate:%y%m%d}{idx:04}'
        for bid,kind in [(st,'定子'),(rot,'转子')]:add('batches',id=bid,work_order_id=wo,kind=kind,qty=actual_qty,created=dt(bstart),status='装配领用',container=f'ZZX-{idx:04}-{kind}')
        for mid,per in material_for[p['id']]:
            # Indivisible components are issued in whole pieces; process mass
            # includes a simulated 1.5% loss. Do not apply fractional loss to pcs.
            qty_used=int(actual_qty*per) if materials[mid]['unit']=='件' else round(actual_qty*per*1.015,3)
            add('inventory_movements',id=f'LL-{idx:06}-{mid}',material_id=mid,lot=lots[mid],location=f'CK01-A{list(materials).index(mid)%8+1:02}-{list(materials).index(mid)//8+1:02}',occurred=dt(bstart),movement='生产领料',qty_signed=-qty_used,work_order_id=wo,reference=wo)
            add('genealogy',id=f'GX-R-{idx:06}-{mid}',parent_type='材料批次',parent_id=lots[mid],child_type='生产批次',child_id=st if materials[mid]['category'] in ['铜线','绝缘','漆料','硅钢'] else rot,qty=qty_used,unit=materials[mid]['unit'],occurred=dt(bstart),work_order_id=wo)
        for seq,(process,shop,dep) in enumerate(processes[:6]):
            start=bstart+timedelta(hours=seq*6)
            add('operations',id=f'BG-B-{idx:06}-{seq+1:02}',work_order_id=wo,object_type='生产批次',object_id=st if seq in [0,1,3,4] else rot,process=process,equipment_id=eq(process),employee_id=staff(dep),started=dt(start),finished=dt(start+timedelta(minutes=actual_qty*2.5)),input_qty=actual_qty,good_qty=actual_qty,scrap_qty=0,rework_qty=0,status='完成')
        for u in range(actual_qty):
            serial=produced+1;day=date(2026,9,21)+timedelta(days=produced//900);assembly=datetime.combine(day,datetime.min.time()).replace(hour=8)+timedelta(seconds=(produced%900)*36)
            sn=f'M{day:%y%m%d}{serial:06}';produced+=1
            unit=add('units',id=sn,work_order_id=wo,product_id=p['id'],assembly_at=dt(assembly),stator_batch=st,rotor_batch=rot,status='待检')
            unit_by_wo[wo].append(unit)
            for bid in [st,rot]:add('genealogy',id=f'GX-U-{serial:06}-{bid[:2]}',parent_type='生产批次',parent_id=bid,child_type='整机',child_id=sn,qty=1,unit='件',occurred=dt(assembly),work_order_id=wo)
            add('operations',id=f'BG-U-{serial:06}-01',work_order_id=wo,object_type='整机',object_id=sn,process='装配',equipment_id=eq('装配'),employee_id=staff(8),started=dt(assembly-timedelta(minutes=20)),finished=dt(assembly),input_qty=1,good_qty=1,scrap_qty=0,rework_qty=0,status='完成')

# Specifications are synthetic engineering envelopes, never a production norm.
specs_by_product={}
for p in DATA['products']:
    resistance=round(5/(p['power_kw']+.5),3)
    spec_defs=[('R','绕组电阻','Ω',resistance*.94,resistance*1.06),('IR','绝缘电阻','MΩ',100,None),('HV','耐压泄漏电流','mA',0,5),('I0','空载电流','A',p['power_kw']*.15,p['power_kw']*.55+1),('N0','空载转速','rpm',6000/p['poles']*.95,6000/p['poles']*1.01),('VB','振动速度','mm/s',0,2.8),('NO','噪声','dBA',35,78),('DIR','旋向符合','bool',1,1)]
    specs_by_product[p['id']]=[]
    for code,name,unit,lo,hi in spec_defs:
        spec=add('test_specs',id=f'JC-{p["id"]}-{code}-A',product_id=p['id'],version='JY-A.01',test_code=code,test_name=name,unit=unit,lsl=round(lo,4) if lo is not None else None,usl=round(hi,4) if hi is not None else None,mandatory=True,effective='2026-09-01',note='模拟规范，仅用于系统验证，不可用于真实检验')
        specs_by_product[p['id']].append(spec)

release_by_unit={};nc=0
for serial,u in enumerate(DATA['units'],1):
    if serial%29==0:continue  # expected but untested objects remain in denominator
    assembly=datetime.fromisoformat(u['assembly_at']);device='SB-08-02' if serial%3==0 else 'SB-08-01'
    first_bad=(serial%23==0 or (device=='SB-08-02' and serial%19==0));incomplete=serial%97==0
    repeats=2 if first_bad and serial%5!=0 else 1
    for attempt in range(1,repeats+1):
        sid=f'TS{assembly:%y%m%d}-{serial:06}-{attempt:02}';bad=first_bad and (attempt==1 or serial%11==0)
        stamp=assembly+timedelta(hours=2+attempt,minutes=serial%40);complete=not incomplete
        result='不完整' if not complete else '不合格' if bad else '合格'
        sess=add('test_sessions',id=sid,unit_id=u['id'],attempt=attempt,equipment_id=device,operator_id=staff(9),tested=dt(stamp),temperature_c=round(R.uniform(23,30),1),spec_version='JY-A.01',complete=complete,result=result,reason='初次检测' if attempt==1 else '返修复测',voided=False)
        sessions_by_unit[u['id']].append(sess)
        for j,spec in enumerate(specs_by_product[u['product_id']]):
            if incomplete and spec['test_code']=='HV':continue
            lo=spec['lsl'];hi=spec['usl'];value=1 if spec['test_code']=='DIR' else R.uniform(max(lo or 0,.01),hi) if hi is not None else R.uniform(250,1800)
            if bad and spec['test_code']=='R':value=hi*1.12
            passed=(lo is None or value>=lo) and (hi is None or value<=hi)
            value=round(value,4);rawunit=spec['unit'];raw=value
            if spec['test_code']=='R' and serial%2==0:rawunit='mΩ';raw=round(value*1000,4)
            add('measurements',id=f'{sid}-{spec["test_code"]}',session_id=sid,spec_id=spec['id'],raw_value=raw,raw_unit=rawunit,value=value,unit=spec['unit'],result='合格' if passed else '不合格',file_reference=f'{device}/{assembly:%Y%m%d}/{sid}.csv')
    latest=sessions_by_unit[u['id']][-1]
    if first_bad:
        nc+=1;closed=latest['result']=='合格'
        add('nonconformities',id=f'NCR2609-{nc:05}',unit_id=u['id'],work_order_id=u['work_order_id'],defect_code='EL-R-HIGH',description='绕组电阻超过模拟规范上限',found=sessions_by_unit[u['id']][0]['tested'],owner_id=staff(7),due=dt(assembly.date()+timedelta(days=2)),action='检查接线与绕组，返修后复测' if repeats==2 else '待工艺复核',status='复核关闭' if closed else '处理中',closed=latest['tested'] if closed else None)
    if latest['result']=='合格' and serial%41!=0:
        rel=add('releases',id=f'FX2609-{serial:06}',unit_id=u['id'],session_id=latest['id'],released=dt(datetime.fromisoformat(latest['tested'])+timedelta(hours=1)),approver_id=staff(9),status='批准放行');release_by_unit[u['id']]=rel;u['status']='已放行'
    else:u['status']='隔离待处理' if latest['result']=='不合格' else '待补检' if incomplete else '待放行'

lines=byid('order_lines');orders=byid('orders');plans=byid('delivery_plans');shipment_number=0
consumption_cost=defaultdict(int)
for movement in DATA['inventory_movements']:
    if movement['work_order_id'] and movement['qty_signed']<0:
        amount=Decimal(str(-movement['qty_signed']))*Decimal(materials[movement['material_id']]['unit_cost_cents'])
        consumption_cost[movement['work_order_id']]+=int(amount.quantize(Decimal('1'),rounding=ROUND_HALF_UP))
# Opening stock covers this scenario's demand plus a modest buffer, instead of
# an arbitrary huge balance. Separate purchased lots are kept separately.
used=defaultdict(float)
for movement in DATA['inventory_movements']:
    if movement['qty_signed']<0:used[(movement['material_id'],movement['lot'])]-=movement['qty_signed']
for opening in DATA['inventory_opening']:
    material=materials[opening['material_id']];step=100 if material['unit']=='件' else 500
    opening['qty']=math.ceil(used[(opening['material_id'],opening['lot'])]/step)*step+material['safety_qty']

for wo,units in unit_by_wo.items():
    lid=wo_to_line[wo];line=lines[lid];released=[u for u in units if u['id'] in release_by_unit]
    # A subset waits for dispatch although released, providing a truthful queue.
    available=released[:max(0,len(released)-(3 if len(released)>5 and int(wo[-6:])%7==0 else 0))]
    offset=0
    for pid in plan_for[lid]:
        selected=available[offset:offset+plans[pid]['qty']];offset+=len(selected)
        if not selected:continue
        shipment_number+=1;shipping=max(datetime.fromisoformat(release_by_unit[u['id']]['released']) for u in selected)+timedelta(days=1+(shipment_number%4==0))
        sid=f'FH{shipping:%y%m%d}-{shipment_number:05}-01';signed=shipping+timedelta(days=2)
        add('shipments',id=sid,delivery_plan_id=pid,order_line_id=lid,qty=len(selected),shipped=dt(shipping),signed=dt(signed) if signed<=AS_OF else None,carrier=R.choice(['模拟物流甲','模拟物流乙','自提']),tracking=f'WL2609{shipment_number:08}')
        for n,u in enumerate(selected,1):
            add('shipment_units',id=f'{sid}-{n:03}',shipment_id=sid,unit_id=u['id'],package=f'BX-{shipment_number:05}-{(n-1)//5+1:03}');u['status']='已发货'
        customer=byid('customers')[orders[line['order_id']]['customer_id']];net=len(selected)*line['unit_price_cents'];tax=round(net*.13)
        inv=add('invoices',id=f'FP2609-{shipment_number:05}',shipment_id=sid,customer_id=customer['id'],issued=dt(shipping.date()),due=dt(shipping.date()+timedelta(days=customer['payment_days'])),net_cents=net,tax_cents=tax,status='部分收款' if shipment_number%3 else '已收款')
        paid=(net+tax) if shipment_number%3==0 else (net+tax)//3
        add('payments',id=f'SK2609-{shipment_number:05}',invoice_id=inv['id'],paid=dt(min(shipping.date()+timedelta(days=2),AS_OF.date())),amount_cents=paid,method='模拟银行转账')

for wo,units in unit_by_wo.items():
    p=products[units[0]['product_id']];n=len(units);occurred=units[-1]['assembly_at'][:10]
    material=consumption_cost[wo]
    for category,amount,basis in [('材料',material,'按模拟领料数量×参考单价'),('直接人工',round(n*p['standard_hours']*3600),'标准工时暂估'),('制造费用',round(n*5800),'按台数暂估分摊'),('返工增耗',sum(1 for u in units if len(sessions_by_unit[u['id']])>1)*3500,'返修追加成本')]:
        add('costs',id=f'CB-{wo}-{category}',work_order_id=wo,category=category,amount_cents=amount,occurred=occurred,basis=basis,status='暂估未结账')

for i,e in enumerate(DATA['equipment'],1):
    for d in range(5):
        start=datetime(2026,9,21+d,10)+(timedelta(minutes=i*2));end=start+timedelta(minutes=20+i%7*9)
        add('downtime',id=f'TJ2609-{i:03}-{d+1:02}',equipment_id=e['id'],started=dt(start),finished=dt(end),reason=['换型','待料','设备故障','计划保养'][i%4],work_order_id=DATA['work_orders'][(i*3+d)%200]['id'])
    report=datetime(2026,9,20+i%8,9);finish=report+timedelta(hours=2+i%5)
    add('maintenance',id=f'WX2609-{i:04}',equipment_id=e['id'],kind='故障维修' if i%3 else '计划保养',reported=dt(report),started=dt(report+timedelta(minutes=25)),finished=dt(finish) if i%7 else None,failure=R.choice(['润滑不足','传感器偏移','皮带磨损','到期保养']),technician_id=staff(12),cost_cents=R.randrange(15000,85000,1000),status='已完成' if i%7 else '待备件')
    add('tools',id=f'GJ-{i:04}',name=f'{e["process"]}检具/工装{i:02}',kind='计量器具' if i%2 else '工装夹具',equipment_id=e['id'],uses=R.randrange(1200,8000),maintenance_limit=6000,calibrated='2026-03-01',next_due='2026-09-30' if i%9==0 else '2027-03-01',status='待校准' if i%9==0 else '有效')

for e in DATA['employees']:
    for day in range(21,26):
        productive=round(R.uniform(5.5,6.7),2);setup=round(R.uniform(.4,.9),2);rework=round(R.uniform(0,.4),2);wait=round(8-productive-setup-rework,2)
        add('attendance',id=f'GS2609{day:02}-{e["id"]}',employee_id=e['id'],date=f'2026-09-{day}',shift='白班',productive_hours=productive,setup_hours=setup,wait_hours=wait,rework_hours=rework,overtime_hours=0)
    if e['department_id'] in ['D05','D06','D07','D08','D09']:
        process=R.choice([p[0] for p in processes if f'D{p[2]:02}'==e['department_id']])
        add('skills',id=f'JN-{e["id"]}',employee_id=e['id'],process=process,level=e['skill_level'],approved='2026-01-10',expires='2027-01-10',status='有效')
for shop in sorted({p[1] for p in processes}):
 for d in range(21,26):
    for hr in range(24):
        start=datetime(2026,9,d,hr);end=start+timedelta(hours=1);work=8<=hr<18
        add('energy',id=f'NY-{shop}-{d:02}{hr:02}',meter=f'EM-{sorted({p[1] for p in processes}).index(shop)+1:02}',workshop=shop,started=dt(start),ended=dt(end),kwh=round(R.uniform(80,140) if work else R.uniform(10,25),2),tariff_cents=108 if 10<=hr<15 else 76 if work else 42,measurement='模拟车间分表读数')
for i in range(24):
    found=date(2026,9,15)+timedelta(days=i%12)
    add('ehs',id=f'AH2609-{i+1:04}',workshop=R.choice(processes)[1],kind=R.choice(['设备防护','消防通道','漆料存放','现场整理']),description='模拟巡检发现需整改事项',found=dt(found),due=dt(found+timedelta(days=5)),owner_id=staff(15),status='已复核' if i%3 else '整改中',closed=dt(found+timedelta(days=3)) if i%3 else None)
shipped_units=DATA['shipment_units']
for i,su in enumerate(shipped_units[::91],1):
    shipment=byid('shipments')[su['shipment_id']];line=lines[shipment['order_line_id']];reported=datetime.fromisoformat(shipment['shipped'])+timedelta(days=3)
    if reported>AS_OF:continue
    closed=reported+timedelta(hours=8)
    add('service',id=f'SH2609-{i:04}',unit_id=su['unit_id'],customer_id=orders[line['order_id']]['customer_id'],reported=dt(reported),failure=R.choice(['接线咨询','运输外观损伤','安装振动','运行噪声']),environment=R.choice(['泵房潮湿环境','风机房','车间输送线']),response=dt(reported+timedelta(minutes=45)),closed=dt(closed) if i%3 and closed<AS_OF else None,cost_cents=0 if i%4==0 else R.randrange(5000,65000,1000),status='已关闭' if i%3 and closed<AS_OF else '跟进中')

# Close real document statuses against simulated facts, not unrelated random flags.
from production_schedule import apply_schedule
SCHEDULE_VALIDATION=apply_schedule(DATA)
shipqty=Counter()
for s in DATA['shipments']:shipqty[s['order_line_id']]+=s['qty']
for o in DATA['orders']:
    children=[l for l in DATA['order_lines'] if l['order_id']==o['id']]
    o['status']='已交齐' if all(shipqty[l['id']]>=l['qty'] for l in children) else '部分交付' if any(shipqty[l['id']] for l in children) else '待生产'
for w in DATA['work_orders']:
    u=unit_by_wo[w['id']]
    w['status']='完工待清尾' if u and len(u)==w['planned_qty'] else '部分完工' if u else '未开工'

from generate_ar_history import generate as generate_ar_history
AR_HISTORY=generate_ar_history(sorted(r['id'] for r in DATA['customers'])[:18])
DATA.update(AR_HISTORY['tables'])

def validate():
    keysets={k:{r[s['primary_key']] for r in DATA[k]} for k,s in SCHEMAS.items()}
    for k,s in SCHEMAS.items():
        assert len(keysets[k])==len(DATA[k]),k
        for row in DATA[k]:
            for f in s['fields']:
                value=row[f['name']]
                assert value is not None or not f['required'],(k,f['name'])
                if f['reference'] and value is not None:assert value in keysets[f['reference']],(k,row['id'],f['name'],value)
    assert len(DATA['units'])==4500
    from app.manufacturing_rules import issues as manufacturing_issues
    for dataset in ['work_orders','batches','operations']:
        for row in DATA[dataset]:assert not manufacturing_issues(dataset,row),(dataset,row['id'],manufacturing_issues(dataset,row))
    assert Counter(u['assembly_at'][:10] for u in DATA['units'])=={f'2026-09-{day}':900 for day in range(21,26)}
    for lid,line in lines.items():
        assert sum(plans[p]['qty'] for p in plan_for[lid])==line['qty']
        assert shipqty[lid]<=line['qty']
    assert len({r['unit_id'] for r in DATA['shipment_units']})==len(DATA['shipment_units'])
    for su in DATA['shipment_units']:
        assert su['unit_id'] in release_by_unit
        assert datetime.fromisoformat(byid('shipments')[su['shipment_id']]['shipped'])>=datetime.fromisoformat(release_by_unit[su['unit_id']]['released'])
    balances=defaultdict(float)
    for r in DATA['inventory_opening']:balances[(r['material_id'],r['lot'],r['location'])]+=r['qty']
    for r in DATA['inventory_movements']:balances[(r['material_id'],r['lot'],r['location'])]+=r['qty_signed']
    assert all(v>=-1e-6 for v in balances.values())
    for r in DATA['payments']:
        inv=byid('invoices')[r['invoice_id']];assert r['amount_cents']<=inv['net_cents']+inv['tax_cents']
    return {'records':sum(map(len,DATA.values())),'tables':len(DATA),'units':4500,'units_per_day':900,'days':5,'schedule':SCHEDULE_VALIDATION,'checks':['unique keys','required fields','all declared foreign keys','delivery plan quantity conservation','no over-shipment','unique shipping SN','release before shipment','nonnegative inventory','payment not above invoice'],'table_counts':{k:len(v) for k,v in DATA.items()}}

if __name__=='__main__':
    ROOT.joinpath('data').mkdir(exist_ok=True)
    validation=validate()
    payload={'notice':'全部为合成模拟数据，编号仿真实业务；不存在真实客户、员工或生产事实。资源容量、班次、工时和检验限值均为演示假设，不可用于真实排产或检验。','seed':20261002,'timezone':'Asia/Shanghai','as_of':dt(AS_OF),'schema_version':2,'schemas':SCHEMAS,'tables':DATA,'validation':validation}
    (ROOT/'data/scenario.json').write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')))
    (ROOT/'data/ar_history_scenario.json').write_text(json.dumps(AR_HISTORY,ensure_ascii=False,indent=2))
    (ROOT/'data/scenario_validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2))
    print(json.dumps(validation,ensure_ascii=False))
