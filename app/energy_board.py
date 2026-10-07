"""Interval electricity, meter coverage and EHS cohorts from committed Excel facts.

Meter totals are imported submeter records, not a certified factory balance.
Assembly ratios use explicit SN-operation-equipment links, never allocation.
"""
from collections import defaultdict
from datetime import datetime, date, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from . import analytics
from .assets import dt, merge, seconds
from .models import Record

TABLES=('energy','ehs','employees','equipment','operations','units')
STAGES={'meters':{'all':'全部分表','complete':'时间覆盖完整','gap':'存在覆盖缺口','attention':'数据待核对'},
        'ehs':{'all':'全部事项','open':'截止未关闭','overdue':'未关闭且逾期','today':'今日到期未关闭','closed':'有复核关闭日期','late':'逾期后关闭','attention':'数据待核对'}}
NOTE='合成Excel演练。电量是区间用电量，截取和跨日/整点拆分按时长均摊；同表重叠不相加。分表加总未验证总分表层级，不能视为全厂能源平衡。参考单耗为同期间车间电量÷明确归属该车间的装配SN数，不是产品实测能耗。'

def filters(q):
    if set(q)-{'tab','from','to','workshop','meter','q','stage','page'}:raise ValueError('不支持的能源筛选')
    f={k:q.get(k,'') for k in ['from','to','workshop','meter','q']};f.update(tab=q.get('tab','meters'),stage=q.get('stage','all'))
    if f['tab'] not in STAGES or f['stage'] not in STAGES[f['tab']]:raise ValueError('工作页或清单状态不可用')
    if any(len(f[k])>150 for k in ['workshop','meter','q']):raise ValueError('筛选内容过长')
    if f['tab']=='ehs' and f['meter']:raise ValueError('整改页不支持表计筛选')
    today=date.fromisoformat(analytics.AS_OF[:10])
    for k in ['from','to']:
        if f[k] and (date.fromisoformat(f[k]).isoformat()!=f[k] or date.fromisoformat(f[k])>today):raise ValueError('日期须在固定快照业务日以内')
    if f['from'] and f['to'] and f['from']>f['to']:raise ValueError('开始日期不能晚于结束日期')
    if f['from'] and (date.fromisoformat(f['to']) if f['to'] else today)-date.fromisoformat(f['from'])>timedelta(days=366):raise ValueError('每次最多查询367个业务日')
    return f

def number(v):
    if isinstance(v,bool) or v is None:raise ValueError('缺少非负数值')
    try:n=Decimal(str(v))
    except InvalidOperation:raise ValueError('数值格式错误')
    if not n.is_finite() or not 0<=n<=Decimal('1000000000000'):raise ValueError('数值无效或超范围')
    return n

def cents(v):return int(v.quantize(Decimal(1),rounding=ROUND_HALF_UP))
def refs(ds,rows):return [{'dataset':ds,'key':r['id']} for r in rows]
def unique(rows):return list({(r['dataset'],r['key']):r for r in rows}.values())
def safe(value,money):
    if isinstance(value,dict):return {k:safe(v,money) for k,v in value.items() if money or ('cents' not in k and k!='tariffs')}
    if isinstance(value,list):return [safe(v,money) for v in value]
    return value

class EnergyBoard:
    def __init__(self,data,f,cutoff=None):
        self.data=data;self.f=f;self.cutoff=cutoff or analytics.AS_OF;self.end=dt(self.cutoff);self.today=self.end.date();self.global_issues=[]
        self.idx={ds:{r['id']:r for r in data.get(ds,[])} for ds in TABLES};self.meters={};self.cases={}
        self.equipment=self.idx['equipment'];self.ops=defaultdict(list)
        for r in data.get('operations',[]):
            if r.get('process')=='装配' and r.get('object_type')=='整机':self.ops[r['object_id']].append(r)
        parsed=[]
        for r in data.get('energy',[]):
            try:
                a,b=dt(r['started']),dt(r['ended'])
                if b<=a or b-a>timedelta(days=367):raise ValueError()
                if a<self.end:parsed.append((a,min(b,self.end)))
            except (ValueError,TypeError,KeyError):pass
        base_lo=min((a for a,b in parsed),default=self.end).date();base_hi=(max((b for a,b in parsed),default=self.end)-timedelta(microseconds=1)).date()
        start=date.fromisoformat(f['from']) if f['from'] else base_lo
        finish=date.fromisoformat(f['to']) if f['to'] else max(start,base_hi)
        self.lo=datetime.combine(start,time());self.hi=min(datetime.combine(finish+timedelta(days=1),time()),self.end)
        if self.hi<self.lo:self.hi=self.lo
        self.days=[];cursor=self.lo
        while cursor<self.hi:self.days.append(cursor.date().isoformat());cursor+=timedelta(days=1)
        groups=defaultdict(list)
        for r in data.get('energy',[]):groups[r.get('meter') or '未填写表计'].append(r)
        for meter,rows in sorted(groups.items()):self.meters[meter]=self.meter(meter,rows)
        self.build_assembly()
        for r in data.get('ehs',[]):
            item=self.ehs(r)
            if item:self.cases[r['id']]=item

    def meter(self,key,rows):
        shops=sorted({r.get('workshop','') for r in rows});issues=[];cost_issues=[];readings=[];intervals=[];daily=defaultdict(lambda:{'kwh':Decimal(0),'cost':Decimal(0),'spans':[]});hourly=defaultdict(Decimal);tariffs=defaultdict(Decimal)
        if len(shops)!=1 or not shops[0]:issues.append('同一表计车间归属缺失或不唯一')
        if key=='未填写表计':issues.append('表计编号缺失')
        for r in rows:
            item={**r,'window_kwh':None,'window_start':None,'window_end':None,'issues':[]}
            try:
                a,b=dt(r['started']),dt(r['ended'])
                if b<=a or b-a>timedelta(days=367):raise ValueError()
            except (ValueError,TypeError,KeyError):
                item['issues'].append('时间区间无效，无法判断是否属于所选范围');readings.append(item);issues.append(r['id']+'：时间区间无效');continue
            x,y=max(a,self.lo),min(b,self.hi)
            if y<=x:continue
            item.update(window_start=x.isoformat(),window_end=y.isoformat());intervals.append((x,y))
            try:kwh=number(r.get('kwh'))
            except ValueError:
                item['issues'].append('电量缺失、负值或无效');readings.append(item);issues.append(r['id']+'：电量无效');continue
            try:rate=number(r.get('tariff_cents'))
            except ValueError:rate=None;cost_issues.append(r['id']+'：电价缺失或无效')
            duration=Decimal(str((b-a).total_seconds()));fraction=Decimal(str((y-x).total_seconds()))/duration;item['window_kwh']=float(kwh*fraction)
            cursor=x
            while cursor<y:
                edge=min(y,cursor.replace(minute=0,second=0,microsecond=0)+timedelta(hours=1));portion=kwh*Decimal(str((edge-cursor).total_seconds()))/duration
                day=cursor.date().isoformat();daily[day]['kwh']+=portion;daily[day]['spans'].append((cursor,edge));hourly[cursor.hour]+=portion
                if rate is not None:daily[day]['cost']+=portion*rate;tariffs[rate]+=portion
                cursor=edge
            readings.append(item)
        ordered=sorted(intervals)
        if sum((b-a).total_seconds() for a,b in ordered)-seconds(ordered)>1e-6:issues.append('同一表计存在重叠读数区间，整表电量暂停汇总')
        covered=seconds(ordered)/3600;expected=(self.hi-self.lo).total_seconds()/3600
        coverage=covered/expected*100 if expected else None;complete=bool(expected and abs(covered-expected)<1e-8 and not issues)
        out_daily=[]
        for day in self.days:
            p=daily[day];a=datetime.combine(date.fromisoformat(day),time());hours=(min(a+timedelta(days=1),self.hi)-max(a,self.lo)).total_seconds()/3600
            got=seconds(p['spans'])/3600
            out_daily.append({'date':day,'kwh':float(p['kwh']) if p['spans'] and not issues else None,'covered_hours':got,'expected_hours':hours,'complete':abs(got-hours)<1e-8 and not issues,'cost_cents':cents(p['cost']) if p['spans'] and not issues and not cost_issues else None})
        total=sum((p['kwh'] for p in daily.values()),Decimal(0));cost=sum((p['cost'] for p in daily.values()),Decimal(0));flags=['all']
        if issues:flags+=['attention']
        if complete:flags+=['complete']
        if not complete:flags+=['gap']
        row={'id':key,'workshop':' / '.join(shops),'readings':len(readings),'kwh':float(total) if readings and not issues else None,'cost_cents':cents(cost) if readings and not issues and not cost_issues else None,'covered_hours':covered,'expected_hours':expected,'coverage_pct':coverage,'complete':complete,'flags':flags,'issues':issues,'cost_issues':cost_issues}
        return {'row':row,'daily':out_daily,'hourly':[{'hour':f'{h:02}:00','kwh':float(hourly[h]) if h in hourly and not issues else None} for h in range(24)],'tariffs':[{'tariff_cents':float(k),'kwh':float(v)} for k,v in sorted(tariffs.items())] if not issues and not cost_issues else [],'readings':readings,'sources':refs('energy',readings)}

    def build_assembly(self):
        self.assembly=defaultdict(list);self.assembly_issues=defaultdict(list);self.assembly_unmatched=defaultdict(list)
        for u in self.data.get('units',[]):
            try:t=dt(u['assembly_at'])
            except (ValueError,TypeError,KeyError):self.global_issues.append('装配SN时间无效：'+u['id']);continue
            if not self.lo<=t<self.hi:continue
            matches=self.ops[u['id']];day=t.date().isoformat();valid=[]
            for op in matches:
                eq=self.equipment.get(op.get('equipment_id'))
                try:ok=eq and eq.get('workshop') and op['work_order_id']==u['work_order_id'] and op['status']=='完成' and dt(op['finished'])==t and dt(op['started'])<t
                except (ValueError,TypeError,KeyError):ok=False
                if ok:valid.append((op,eq))
            if len(matches)!=1 or len(valid)!=1:
                self.assembly_issues[day].append('装配SN与唯一完成工序/设备无法对应：'+u['id']);self.assembly_unmatched[day].append(u);continue
            op,eq=valid[0];self.assembly[day].append({'id':u['id'],'product_id':u['product_id'],'work_order_id':u['work_order_id'],'assembly_at':u['assembly_at'],'workshop':eq['workshop'],'operation_id':op['id'],'equipment_id':eq['id']})

    def selected(self):
        f=self.f;rows=[x['row'] for x in self.meters.values()] if f['tab']=='meters' else list(self.cases.values())
        return [r for r in rows if (not f['workshop'] or r['workshop']==f['workshop']) and (not f['meter'] or r['id']==f['meter']) and (not f['q'] or f['q'].casefold() in ' '.join(str(r.get(k,'')) for k in ['id','workshop','kind','description']).casefold())]

    def reference(self,day,selected):
        selected_ids={r['id'] for r in selected};objects=self.assembly[day];shops={r['workshop'] for r in objects};result=[]
        for shop in sorted(shops):
            people=[r for r in objects if r['workshop']==shop];meters=[v for v in self.meters.values() if v['row']['workshop']==shop];active=[m for m in meters if m['row']['id'] in selected_ids]
            if not active:continue
            daily=[next(x for x in m['daily'] if x['date']==day) for m in active];reasons=[]
            if len(active)!=len(meters):reasons.append('只选择了车间部分表计')
            if any(not x['complete'] for x in daily):reasons.append('车间表计时间覆盖不完整或数据异常')
            if self.assembly_issues[day]:reasons.append('当日有装配SN归属待核对')
            if self.global_issues:reasons.append('有装配时间无法确定的SN')
            kwh=sum(x['kwh'] for x in daily) if all(x['kwh'] is not None for x in daily) else None
            result.append({'date':day,'workshop':shop,'kwh':kwh,'units':len(people),'configurations':len({r['product_id'] for r in people}),'kwh_per_assembly':kwh/len(people) if not reasons and people and kwh is not None else None,'reason':'；'.join(reasons),'meter_ids':[m['row']['id'] for m in active]})
        return result

    def ehs(self,r):
        issues=[];found=due=closed=None
        try:
            found=date.fromisoformat(r['found']);due=date.fromisoformat(r['due']);closed=date.fromisoformat(r['closed']) if r.get('closed') else None
            if due<found or (closed and closed<found):raise ValueError()
        except (ValueError,TypeError,KeyError):issues.append('发现、期限或关闭日期无效')
        if found and (found>self.today or self.f['from'] and found.isoformat()<self.f['from'] or self.f['to'] and found.isoformat()>self.f['to']):return None
        if r.get('status') not in ['已复核','整改中']:issues.append('未知整改台账状态')
        if r.get('status')=='已复核' and not closed:issues.append('台账已复核但缺少关闭日期')
        if closed and closed<=self.today and r.get('status')!='已复核':issues.append('关闭日期与台账状态不一致')
        owner=self.idx['employees'].get(r.get('owner_id'))
        if not owner:issues.append('责任工号没有对应档案')
        done=bool(not issues and closed and closed<=self.today);opened=bool(not issues and not done);overdue=bool(opened and due<self.today);late=bool(done and closed>due)
        flags=['all']+(['attention'] if issues else ['closed'] if done else ['open'])
        if overdue:flags+=['overdue']
        if late:flags+=['late']
        if opened and due==self.today:flags+=['today']
        return {**r,'owner_name':owner['name'] if owner else '未匹配','closed_as_of':closed.isoformat() if done else None,'calculated_state':'数据待核对' if issues else '已记录复核关闭' if done else '截止未关闭','elapsed_days':(closed-found).days if done else None,'open_days':(self.today-found).days if opened else None,'overdue_days':(self.today-due).days if overdue else 0 if not issues else None,'late_close_days':(closed-due).days if late else 0 if done else None,'flags':flags,'issues':issues}

    def summary(self,rows):
        if self.f['tab']=='ehs':
            completed=[r for r in rows if 'closed' in r['flags']]
            return {'objects':len(rows),'open':sum('open' in r['flags'] for r in rows),'overdue':sum('overdue' in r['flags'] for r in rows),'closed':len(completed),'attention':sum(bool(r['issues']) for r in rows),'closed_days':sum(r['elapsed_days'] for r in completed)/len(completed) if completed else None}
        valid=[r for r in rows if r['kwh'] is not None];hours=sum(r['covered_hours'] for r in rows);expected=sum(r['expected_hours'] for r in rows)
        return {'objects':len(rows),'verified':len(valid),'complete':sum(r['complete'] for r in rows),'attention':sum(bool(r['issues']) for r in rows),'kwh':sum(r['kwh'] for r in valid) if valid else None,'coverage_pct':hours/expected*100 if expected else None,'covered_hours':hours,'expected_hours':expected,'cost_cents':sum(r['cost_cents'] for r in valid) if valid and all(r['cost_cents'] is not None for r in valid) else None}

    def breakdown(self,rows):
        if self.f['tab']=='ehs':
            shops=sorted({r['workshop'] for r in rows})
            return {'workshops':[{'name':s,'open':sum('open' in r['flags'] for r in rows if r['workshop']==s),'closed':sum('closed' in r['flags'] for r in rows if r['workshop']==s),'attention':sum(bool(r['issues']) for r in rows if r['workshop']==s)} for s in shops]}
        chosen=[self.meters[r['id']] for r in rows];daily=[]
        for day in self.days:
            slices=[next(x for x in m['daily'] if x['date']==day) for m in chosen];values=[x['kwh'] for x in slices if x['kwh'] is not None]
            daily.append({'date':day,'kwh':sum(values) if values else None,'complete_meters':sum(x['complete'] for x in slices),'meters':len(chosen),'covered_hours':sum(x['covered_hours'] for x in slices),'expected_hours':sum(x['expected_hours'] for x in slices)})
        hourly=[]
        for h in range(24):
            values=[m['hourly'][h]['kwh'] for m in chosen if m['hourly'][h]['kwh'] is not None];hourly.append({'hour':f'{h:02}:00','kwh':sum(values) if values else None})
        reference=[x for day in self.days for x in self.reference(day,rows)]
        return {'daily':daily if rows else [],'hourly':hourly if rows else [],'workshops':[{'name':s,'kwh':sum(r['kwh'] for r in rows if r['workshop']==s and r['kwh'] is not None) if any(r['kwh'] is not None for r in rows if r['workshop']==s) else None} for s in sorted({r['workshop'] for r in rows})],'assembly':reference,'assembly_issues':[x for day in self.days for x in self.assembly_issues[day]],'window_start':self.lo.isoformat(),'window_end':self.hi.isoformat()}

    def detail(self,kind,key):
        if kind=='meter' and key in self.meters and self.f['tab']=='meters' and key in {r['id'] for r in self.selected()}:return self.meters[key]
        if kind=='ehs' and key in self.cases and self.f['tab']=='ehs' and key in {r['id'] for r in self.selected()}:
            r=self.cases[key];return {'row':r,'sources':refs('ehs',[r])+([{'dataset':'employees','key':r['owner_id']}] if r['owner_id'] in self.idx['employees'] else [])}
        if kind=='assembly' and key in self.days and self.f['tab']=='meters':
            references=self.reference(key,self.selected());shops={r['workshop'] for r in references};units=[u for u in self.assembly[key] if u['workshop'] in shops]
            sources=refs('units',units)+[{'dataset':'operations','key':u['operation_id']} for u in units]+[{'dataset':'equipment','key':u['equipment_id']} for u in units]
            sources+=refs('units',self.assembly_unmatched[key])+refs('operations',[op for u in self.assembly_unmatched[key] for op in self.ops[u['id']]])
            daylo=datetime.combine(date.fromisoformat(key),time());dayhi=daylo+timedelta(days=1)
            for r in references:
                for mid in r['meter_ids']:
                    sources+=refs('energy',[x for x in self.meters[mid]['readings'] if x['window_start'] and max(dt(x['window_start']),daylo)<min(dt(x['window_end']),dayhi)])
            return {'row':{'id':key,'issues':self.assembly_issues[key]},'references':references,'units':units,'unmatched_units':self.assembly_unmatched[key],'sources':unique(sources)}
        raise Record.DoesNotExist()

def current(f):return EnergyBoard({k:list(Record.objects.filter(dataset=k).values_list('values',flat=True)) for k in TABLES},f)
