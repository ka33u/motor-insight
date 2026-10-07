"""Deterministic, capacity-constrained synthetic events, not a live APS planner.

The resource, staffing and processing assumptions are emitted as XLSX sources.
No function in this module writes application records or changes actual plans.
"""
from bisect import insort
from collections import defaultdict,Counter
from datetime import datetime,timedelta
from decimal import Decimal,ROUND_HALF_UP
import heapq

START=datetime(2026,9,16,8)
END=datetime(2026,10,1,18)
def stamp(value):return value.isoformat(timespec='seconds')
def parse(value):return datetime.fromisoformat(value)
def index(rows):return {r['id']:r for r in rows}
def grouped(rows,key):
    out=defaultdict(list)
    for row in rows:out[row[key]].append(row)
    return out
def money(value):return int(value.quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def minutes(a,b):return (b-a).total_seconds()/60

class CalendarScheduler:
    def __init__(self,resources,calendars,blocked):
        self.resources=index(resources);self.windows=defaultdict(list);self.busy=defaultdict(list)
        for row in calendars:self.windows[row['resource_id']].append((parse(row['started']),parse(row['finished'])))
        for key in self.windows:self.windows[key].sort()
        for resource in resources:
            self.busy[resource['id']]=sorted(blocked.get(resource['equipment_id'],[]))

    def first_fit(self,key,earliest,duration):
        for start,finish in self.windows[key]:
            cursor=max(start,earliest)
            if cursor+duration>finish:continue
            for a,b in self.busy[key]:
                if b<=cursor:continue
                if a>=finish:break
                if cursor+duration<=a:break
                cursor=max(cursor,b)
                if cursor+duration>finish:break
            if cursor+duration<=finish:return cursor,cursor+duration
        return None

    def reserve(self,process,earliest,duration_minutes,qty=1,equipment=None,deadline=None):
        if duration_minutes<=0:raise ValueError('operation duration must be positive')
        options=[];duration=timedelta(minutes=duration_minutes)
        for key,r in self.resources.items():
            if r['process']!=process or qty>r['max_batch_qty'] or (equipment and r['equipment_id']!=equipment):continue
            result=self.first_fit(key,earliest,duration)
            if result and (deadline is None or result[1]<=deadline):options.append((result[0],result[1],key))
        if not options:raise ValueError(f'No feasible resource: {process}, earliest={earliest}, quantity={qty}, duration={duration_minutes}, deadline={deadline}')
        a,b,key=min(options);insort(self.busy[key],(a,b))
        return self.resources[key],a,b

def apply_schedule(d):
    # This detailed demo allocates two of the originally generic management
    # staff to the winding shop; their IDs and historical wage assumptions stay.
    for employee in d['employees']:
        if employee['id'] in ['E00001','E00017']:employee['department_id']='D07';employee['role']='操作员'
    employees=index(d['employees']);products=index(d['products']);materials=index(d['materials'])
    staff={dep:sorted([e['id'] for e in d['employees'] if e['department_id']==dep]) for dep in {e['department_id'] for e in d['employees']}}
    # Additional explicitly modeled activities use spare staff in the same shop.
    for n in [1,2]:
        d['equipment'].append(dict(id=f'SB-10-{n:02}',name=f'返修{n}号工位',workshop='绕组车间',process='返修',model='模拟独立返修工位',commissioned='2025-03-15',status='运行',owner_id=staff['D07'][-n]))
    for n in [1,2,3]:
        d['equipment'].append(dict(id=f'SB-11-{n:02}',name=f'转子铸铝{n}号设备',workshop='机加工车间',process='转子铸铝',model='模拟转子铸铝单元',commissioned='2025-03-15',status='运行',owner_id=staff['D06'][-n]))
    dept={'冲片':'D05','叠压':'D05','机加工':'D06','绕线嵌线':'D07','浸漆固化':'D07','动平衡':'D06','装配':'D08','终检':'D09','包装':'D11','返修':'D07','转子铸铝':'D06'}
    used=Counter();resources=[]
    for e in d['equipment']:
        slots=4 if e['process'] in ['装配','终检'] else 2 if e['process'] in ['浸漆固化','绕线嵌线'] else 1
        for n in range(1,slots+1):
            dep=dept[e['process']];employee=staff[dep][used[dep]];used[dep]+=1
            r=dict(id=f'{e["id"]}-W{n:02}',equipment_id=e['id'],process=e['process'],station=f'{e["name"]} / 独立'+('腔位' if e['process']=='浸漆固化' else '工位')+str(n),employee_id=employee,capacity=1,max_batch_qty=1 if e['process'] in ['装配','终检','返修'] else 60,effective='2026-09-01',basis='模拟独立资源位；容量与节拍须以工厂实测替换，不能作为实际产能承诺')
            resources.append(r)
    d['production_resources']=resources
    # A nine-hour work window (eight regular plus one explicitly scheduled hour),
    # with a one-hour lunch break. Weekends here are expressly scheduled demo days.
    calendars=[]
    for r in resources:
        for offset in range(15):
            day=(START+timedelta(days=offset)).replace(hour=0)
            for n,(a,b) in enumerate([(8,12),(13,18)],1):
                calendars.append(dict(id=f'PB-{day:%y%m%d}-{r["id"]}-{n}',resource_id=r['id'],employee_id=r['employee_id'],started=stamp(day.replace(hour=a)),finished=stamp(day.replace(hour=b)),shift='模拟白班',basis='08–12 / 13–18；含1小时计划加班；周末按本模拟日历排班'))
    d['resource_calendars']=calendars

    # Repairs in this synthetic history are after the five assembly days. Pending
    # repairs genuinely block their equipment from their start to the cutoff.
    for i,m in enumerate(d['maintenance'],1):
        reported=datetime(2026,9,26+i%3,8)
        if m['status']=='待备件':reported=datetime(2026,9,30,9)
        m['reported']=stamp(reported);m['started']=stamp(reported+timedelta(minutes=25))
        m['finished']=stamp(reported+timedelta(hours=2+i%5)) if m['status']!='待备件' else None
    blocked=defaultdict(list)
    for row in d['downtime']:blocked[row['equipment_id']].append((parse(row['started']),parse(row['finished'])))
    for row in d['maintenance']:
        if row['started']:blocked[row['equipment_id']].append((parse(row['started']),parse(row['finished']) if row['finished'] else END))
    pending={r['equipment_id'] for r in d['maintenance'] if r['started'] and not r['finished']}
    for e in d['equipment']:
        if e['id'] in pending:e['status']='停机待备件'
    # A machine stoppage does not establish which work order was affected.
    # Keep the association unknown instead of retaining an arbitrary WO.
    for row in d['downtime']:row['work_order_id']=None
    scheduler=CalendarScheduler(resources,calendars,blocked)

    # Explicit stator / rotor / assembly material levels. Silicon consumption
    # is split between the two cores; bearings and housing belong to assembly.
    bom=[]
    for row in d['bom']:
        category=materials[row['material_id']]['category']
        if category=='硅钢':
            first=round(row['qty']*.65,4)
            bom.extend([{**row,'id':row['id']+'-DZ','assembly_level':'定子','qty':first},{**row,'id':row['id']+'-ZZ','assembly_level':'转子','qty':round(row['qty']-first,4)}])
        else:bom.append({**row,'assembly_level':'定子' if category in ['铜线','绝缘','漆料'] else '转子' if category in ['轴','铝材'] else '装配件包'})
    d['bom']=bom
    routes=[];dependencies=[]
    branches={'定子':['冲片','叠压','绕线嵌线','浸漆固化'],'转子':['冲片','转子铸铝','机加工','动平衡'],'整机':['装配','终检','包装']}
    old_routes=grouped(d['routes'],'product_id')
    for product in d['products']:
        originals={r['process']:r for r in old_routes[product['id']]};ends={};assembly=None
        for branch,steps in branches.items():
            previous=None
            for seq,process in enumerate(steps,1):
                original=originals.get(process,originals['机加工']);row={**original,'product_id':product['id'],'process':process,'branch':branch,'sequence':seq*10}
                if branch=='转子' and process=='冲片':row['id']=originals['冲片']['id']+'-ZZ'
                if process=='转子铸铝':row['id']=originals['机加工']['id']+'-ZL';row['minutes']=1.5
                routes.append(row)
                if previous:dependencies.append(dict(id=f'YL-{previous["id"]}-{row["id"]}',product_id=product['id'],from_route_id=previous['id'],to_route_id=row['id'],lag_minutes=45 if previous['process']=='转子铸铝' else 5,basis='模拟最小转运/冷却约束，非工程标准'))
                if process=='装配':assembly=row
                previous=row
            ends[branch]=previous
        for branch in ['定子','转子']:
            previous=ends[branch];dependencies.append(dict(id=f'YL-{previous["id"]}-{assembly["id"]}',product_id=product['id'],from_route_id=previous['id'],to_route_id=assembly['id'],lag_minutes=20 if branch=='定子' else 5,basis='模拟装配前等待；两条分支均完成后才允许装配'))
    d['routes']=routes;d['route_dependencies']=dependencies

    units_by_wo=grouped(d['units'],'work_order_id');batches=index(d['batches']);orders=index(d['orders']);lines=index(d['order_lines']);allocation=grouped(d['allocations'],'work_order_id')
    old_ops=grouped(d['operations'],'work_order_id');operations=[];setup_minutes={};ready={}
    def emit(op_id,wo,kind,obj,process,earliest,duration,qty=1,equipment=None,deadline=None,setup=0):
        resource,a,b=scheduler.reserve(process,earliest,duration,qty,equipment,deadline)
        row=dict(id=op_id,work_order_id=wo,object_type=kind,object_id=obj,process=process,equipment_id=resource['equipment_id'],employee_id=resource['employee_id'],started=stamp(a),finished=stamp(b),input_qty=qty,good_qty=qty,scrap_qty=0,rework_qty=0,status='完成',resource_id=resource['id'])
        if process=='返修':row['rework_qty']=qty
        operations.append(row);setup_minutes[op_id]=setup
        return row,a,b

    for wo in d['work_orders']:
        uu=units_by_wo[wo['id']]
        if not uu:continue
        count=len(uu);st=uu[0]['stator_batch'];rot=uu[0]['rotor_batch'];kit='ZJ'+st[2:]
        # Five-day preparation horizon is an explicit demo planning assumption;
        # orders not yet accepted cannot be released for this make-to-order run.
        earliest=max(START,parse(uu[0]['assembly_at']).replace(hour=8,minute=0,second=0)-timedelta(days=5),max(parse(orders[lines[a['order_line_id']]['order_id']]['order_date']).replace(hour=8) for a in allocation[wo['id']]))
        material_ids={r['material_id'] for r in d['bom'] if r['product_id']==wo['product_id']}
        for opening in d['inventory_opening']:
            if opening['material_id'] in material_ids and opening['status']=='冻结':
                approvals=[parse(r['occurred']) for r in d['inventory_status_events'] if r['material_id']==opening['material_id'] and r['lot']==opening['lot'] and r['to_status']=='可用']
                if not approvals:raise ValueError('A required material remains frozen')
                earliest=max(earliest,min(approvals))
        base=f'BG-B-{wo["id"][-6:]}';firsts=[];finishes={}
        for branch,obj,steps in [('定子',st,['冲片','叠压','绕线嵌线','浸漆固化']),('转子',rot,['冲片','转子铸铝','机加工','动平衡'])]:
            previous=earliest
            for seq,process in enumerate(steps,1):
                setup,per,fixed={'冲片':(8,.8,0),'叠压':(8,1.1,0),'绕线嵌线':(10,2,0),'浸漆固化':(10,0,80),'转子铸铝':(8,1,0),'机加工':(8,1.5,0),'动平衡':(5,.6,0)}[process]
                row,a,b=emit(f'{base}-{branch}-{seq:02}',wo['id'],'生产批次',obj,process,previous,setup+count*per+fixed,count,setup=setup)
                if seq==1:firsts.append(a)
                previous=b+timedelta(minutes=45 if process=='转子铸铝' else 20 if process=='浸漆固化' else 5)
            finishes[branch]=previous
        created=min(firsts);ready[wo['id']]=max(finishes.values())
        for bid in [st,rot]:batches[bid]['created']=stamp(created)
        new_batch=dict(id=kit,work_order_id=wo['id'],kind='装配件包',qty=count,created=stamp(created),status='装配领用',container='ZZX-'+wo['id'][-6:]+'-装配件')
        d['batches'].append(new_batch);batches[kit]=new_batch
        for unit in uu:unit['assembly_batch']=kit
        wo['planned_start']=min(wo['planned_start'],created.date().isoformat())
    # Preserve 900 assembled serials on each requested demonstration day, while
    # deriving their timestamps and employees from feasible resource calendars.
    for unit in d['units']:
        day=parse(unit['assembly_at']).replace(hour=8,minute=0,second=0)
        _,a,b=emit(f'BG-U-{unit["id"][-6:]}-01',unit['work_order_id'],'整机',unit['id'],'装配',max(day,ready[unit['work_order_id']]),6,deadline=day.replace(hour=18))
        unit['assembly_at']=stamp(b)
    units=index(d['units'])
    first_op={wo:min(parse(r['started']) for r in operations if r['work_order_id']==wo and r['object_type']=='生产批次') for wo in ready}
    for row in d['inventory_movements']:
        if row['qty_signed']<0 and row['work_order_id'] in first_op:row['occurred']=stamp(first_op[row['work_order_id']])
    # Rebuild only this synthetic lineage from its signed inventory issues.
    genealogy=[]
    for row in d['inventory_movements']:
        if row['qty_signed']>=0 or row['work_order_id'] not in ready:continue
        wo=row['work_order_id'];u=units_by_wo[wo][0];material=materials[row['material_id']];qty=-row['qty_signed'];category=material['category']
        shares=[(u['stator_batch'],round(qty*.65,3)),(u['rotor_batch'],round(qty-round(qty*.65,3),3))] if category=='硅钢' else [(u['stator_batch'] if category in ['铜线','绝缘','漆料'] else u['rotor_batch'] if category in ['轴','铝材'] else u['assembly_batch'],qty)]
        for bid,amount in shares:genealogy.append(dict(id=f'GX-R-{wo[-6:]}-{row["material_id"]}-{bid[:2]}',parent_type='材料批次',parent_id=row['lot'],child_type='生产批次',child_id=bid,qty=amount,unit=material['unit'],occurred=row['occurred'],work_order_id=wo))
    for unit in d['units']:
        for bid in [unit['stator_batch'],unit['rotor_batch'],unit['assembly_batch']]:genealogy.append(dict(id=f'GX-U-{unit["id"][-6:]}-{bid[:2]}',parent_type='生产批次',parent_id=bid,child_type='整机',child_id=unit['id'],qty=1,unit='件',occurred=unit['assembly_at'],work_order_id=unit['work_order_id']))
    d['genealogy']=genealogy

    sessions_by_unit=grouped(d['test_sessions'],'unit_id');queue=[];old_session_ids={id(s):s['id'] for s in d['test_sessions']}
    for sn,ss in sessions_by_unit.items():
        ss.sort(key=lambda s:s['attempt']);heapq.heappush(queue,(parse(units[sn]['assembly_at'])+timedelta(hours=3,minutes=int(sn[-6:])%40),ss[0]['id'],sn,0))
    while queue:
        earliest,_,sn,n=heapq.heappop(queue);unit=units[sn];session=sessions_by_unit[sn][n]
        op,a,b=emit('BG-JC-'+old_session_ids[id(session)],unit['work_order_id'],'整机',sn,'终检',earliest,3,equipment=session['equipment_id'])
        session['tested']=stamp(b);session['operator_id']=op['employee_id']
        if n+1<len(sessions_by_unit[sn]):
            repair,ra,rb=emit('BG-FX-'+sn,unit['work_order_id'],'整机',sn,'返修',b+timedelta(minutes=30),12)
            heapq.heappush(queue,(rb+timedelta(minutes=30),sessions_by_unit[sn][n+1]['id'],sn,n+1))
    session_ids={}
    for row in d['test_sessions']:
        old=row['id'];row['id']=f'TS{parse(row["tested"]):%y%m%d}-{row["unit_id"][-6:]}-{row["attempt"]:02}';session_ids[old]=row['id']
    sessions=index(d['test_sessions'])
    for row in d['measurements']:
        suffix=row['id'].rsplit('-',1)[-1];row['session_id']=session_ids[row['session_id']];s=sessions[row['session_id']];row['id']=s['id']+'-'+suffix;row['file_reference']=f'{s["equipment_id"]}/{parse(s["tested"]):%Y%m%d}/{s["id"]}.csv'
    for row in d['releases']:
        row['session_id']=session_ids[row['session_id']];row['released']=stamp(parse(sessions[row['session_id']]['tested'])+timedelta(hours=1))
    for row in d['nonconformities']:
        ss=sessions_by_unit[row['unit_id']];row['found']=ss[0]['tested'];row['due']=(parse(ss[0]['tested']).date()+timedelta(days=2)).isoformat();row['closed']=ss[-1]['tested'] if row['closed'] else None

    release={r['unit_id']:r for r in d['releases']};packed=grouped(d['shipment_units'],'shipment_id');ship_id_map={}
    for number,shipment in enumerate(d['shipments'],1):
        old=shipment['id'];snrows=packed[old];wo=units[snrows[0]['unit_id']]['work_order_id']
        earliest=max(parse(release[p['unit_id']]['released']) for p in snrows)+timedelta(days=1+(number%4==0))
        operation,a,b=emit(f'BG-BZ-{number:05}',wo,'发货行',old,'包装',earliest,5+len(snrows)*.7,len(snrows),setup=5)
        shipment['shipped']=stamp(b+timedelta(minutes=30));signed=parse(shipment['shipped'])+timedelta(days=2);shipment['signed']=stamp(signed) if signed<=END else None
        shipment['id']=f'FH{parse(shipment["shipped"]):%y%m%d}-{number:05}-01';ship_id_map[old]=shipment['id'];operation['object_id']=shipment['id']
        for p in snrows:p['id']=p['id'].replace(old,shipment['id'],1);p['shipment_id']=shipment['id']
    shipments=index(d['shipments'])
    for inv in d['invoices']:
        inv['shipment_id']=ship_id_map[inv['shipment_id']];when=parse(shipments[inv['shipment_id']]['shipped']).date();days=(parse(inv['due']).date()-parse(inv['issued']).date()).days;inv['issued']=when.isoformat();inv['due']=(when+timedelta(days=days)).isoformat()
    invoices=index(d['invoices']);payments=[]
    for row in d['payments']:
        when=parse(invoices[row['invoice_id']]['issued']).date()+timedelta(days=2)
        if when<=END.date():row['paid']=when.isoformat();payments.append(row)
        else:invoices[row['invoice_id']]['status']='未收款'
    d['payments']=payments
    shipment_by_sn={p['unit_id']:shipments[p['shipment_id']] for p in d['shipment_units']};service=[]
    for row in d['service']:
        reported=parse(shipment_by_sn[row['unit_id']]['shipped'])+timedelta(days=3)
        if reported>END:continue
        row['reported']=stamp(reported);row['response']=stamp(reported+timedelta(minutes=45));closed=reported+timedelta(hours=8)
        row['closed']=stamp(closed) if row['closed'] and closed<=END else None;row['status']='已关闭' if row['closed'] else '跟进中';service.append(row)
    d['service']=service;d['operations']=operations

    labor=[];employee_daily=defaultdict(Counter);labor_cost=Counter()
    for op in operations:
        a,b=parse(op['started']),parse(op['finished']);setup=setup_minutes[op['id']];cuts=[]
        if setup:cuts.append(('换型',a,a+timedelta(minutes=setup)))
        cuts.append(('返工' if op['process']=='返修' else '检验' if op['process']=='终检' else '包装' if op['process']=='包装' else '生产',a+timedelta(minutes=setup),b))
        for n,(activity,start,finish) in enumerate(cuts,1):
            mins=round(minutes(start,finish),4);rate=employees[op['employee_id']]['hourly_cents'];amount=money(Decimal(str(mins))/60*rate)
            row=dict(id=f'GS-{op["id"]}-{n}',operation_id=op['id'],employee_id=op['employee_id'],work_order_id=op['work_order_id'],started=stamp(start),finished=stamp(finish),activity=activity,minutes=mins,hourly_cents=rate,amount_cents=amount,basis='按模拟报工起止时间分解；金额=分钟/60×小时成本，逐行四舍五入到分')
            labor.append(row);employee_daily[(row['employee_id'],start.date().isoformat())][activity]+=mins;labor_cost[row['work_order_id']]+=amount
    d['labor_entries']=labor;assigned={r['employee_id'] for r in resources};attendance=[]
    for employee in d['employees']:
        for offset in range(15):
            day=(START+timedelta(days=offset)).date().isoformat();totals=employee_daily[(employee['id'],day)];scheduled=9 if employee['id'] in assigned else 8
            prod=sum(totals[x] for x in ['生产','检验','包装']);setup=totals['换型'];rework=totals['返工'];support=0 if employee['id'] in assigned else 8
            wait=round(scheduled*60-prod-setup-rework-support*60,4)
            if wait<-.001:raise AssertionError(('employee day overbooked',employee['id'],day,wait))
            attendance.append(dict(id=f'GS{day.replace("-","")}-{employee["id"]}',employee_id=employee['id'],date=day,shift='模拟白班',productive_hours=round(prod/60,4),setup_hours=round(setup/60,4),wait_hours=round(max(0,wait)/60,4),rework_hours=round(rework/60,4),overtime_hours=scheduled-8,support_hours=support,scheduled_hours=scheduled))
    d['attendance']=attendance
    skills={(r['employee_id'],r['process']):r for r in d['skills']}
    for r in resources:
        key=(r['employee_id'],r['process'])
        if key not in skills:skills[key]=dict(id=f'JN-{r["employee_id"]}-{r["equipment_id"][:5]}',employee_id=r['employee_id'],process=r['process'],level=employees[r['employee_id']]['skill_level'],approved='2026-01-10',expires='2027-01-10',status='有效')
    d['skills']=list(skills.values())
    for row in d['costs']:
        if row['category']=='直接人工':row['amount_cents']=labor_cost[row['work_order_id']];row['basis']='报工作业工时明细逐行金额汇总；含换型、生产、检验、返工和包装'
        if row['category']=='返工增耗':row['basis']='模拟返工辅料与复验耗材；不含已归集的作业人工'
        if row['category']=='直接人工':row['occurred']=max(op['finished'][:10] for op in operations if op['work_order_id']==row['work_order_id'])
    # Independent assertions here precede the broader imported-record audit.
    for key in ['resource_id','employee_id']:
        for resource,events in grouped(operations,key).items():
            previous=None
            for event in sorted(events,key=lambda r:r['started']):
                if previous and event['started']<previous['finished']:raise AssertionError(('overlap',key,resource,previous['id'],event['id']))
                previous=event
    return {'resources':len(resources),'calendar_segments':len(calendars),'operations':len(operations),'labor_entries':len(labor),'scope':'synthetic calendar-constrained events; no OEE or actual production-capacity claim','assumptions':['assembly: 3 lines × 4 independent stations, 6 minutes/SN','winding: 3 cells × 2 independently staffed stations','curing: 3 devices × 2 independent chambers','test: 3 devices × 4 stations, 3 minutes/session; 2 devices used','five-day preparation horizon, never before customer order or frozen material release','stator and rotor route dependencies; casting cool-down 45 minutes','08:00–12:00 and 13:00–18:00 resource windows, 2026-09-16 through 2026-09-30','equipment downtime and started repairs excluded from resource slots']}
