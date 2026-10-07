"""Personnel hours and current skill-register coverage from imported Excel facts."""
from collections import defaultdict,Counter
from datetime import date,datetime,timedelta
from math import isfinite
from . import analytics
from .models import Record

TABLES=('departments','employees','attendance','skills','labor_entries','operations','resource_calendars','production_resources')
HOURS={'productive_hours':'生产/检验/包装','setup_hours':'换型','wait_hours':'等待','rework_hours':'返工','support_hours':'间接支持'}
ACTIVITY={'生产':'productive_hours','检验':'productive_hours','包装':'productive_hours','换型':'setup_hours','返工':'rework_hours'}
STAGES={'hours':{'all':'全部人员','recorded':'有班次记录','missing':'未有班次记录','labor':'有作业明细','attention':'数据待核对'},
 'skills':{'all':'全部授权','effective':'台账当前有效','expired':'日期已到期','today':'今日到期','soon':'30天内到期','future':'日期未生效','inactive':'状态未有效','attention':'数据待核对'}}
NOTE='合成Excel演练。班次工时按业务日期，作业按实际起止截取；其中加班已包含在总工时内。技能为当前台账及日期窗口，未提供暂停/撤销历史，不能据此确认历史作业资格。工时结构不代表个人绩效或实际出勤。'
def dt(value):
    t=datetime.fromisoformat(value)
    if t.tzinfo is not None:raise ValueError('须为工厂本地时间')
    return t
def day(value):
    d=date.fromisoformat(value)
    if d.isoformat()!=value:raise ValueError('日期格式须为YYYY-MM-DD')
    return d
def numeric(value):return type(value) in (int,float) and isfinite(value) and value>=0
def merged(spans):
    out=[]
    for a,b in sorted(spans):
        if a>=b:continue
        if out and a<=out[-1][1]:out[-1]=(out[-1][0],max(out[-1][1],b))
        else:out.append((a,b))
    return out
def hours(spans):return sum((b-a).total_seconds()/3600 for a,b in merged(spans))
def filters(q):
    if set(q)-{'tab','from','to','department','process','stage','q','page'}:raise ValueError('不支持的人员筛选')
    f={k:str(q.get(k,'')) for k in ['from','to','department','process','q']};f['tab']=q.get('tab','hours');f['stage']=q.get('stage','all')
    if f['tab'] not in STAGES or f['stage'] not in STAGES[f['tab']]:raise ValueError('人员页签或清单状态无效')
    if f['tab']=='skills' and (f['from'] or f['to']):raise ValueError('技能台账使用固定截止日，不使用工时期间')
    if f['tab']=='hours' and f['process']:raise ValueError('班次总工时不能直接按工序拆分；请在技能页筛选工序')
    for k in ['from','to']:
        if f[k] and day(f[k])>day(analytics.DAY):raise ValueError('日期不得晚于模拟截止日')
    if f['from'] and f['to'] and f['from']>f['to']:raise ValueError('开始日期不得晚于结束日期')
    if f['from'] and (day(f['to'] or analytics.DAY)-day(f['from'])).days>366:raise ValueError('单次工时窗口最多367个业务日')
    if len(f['q'])>100:raise ValueError('搜索不超过100字')
    return f

class Workforce:
    def __init__(self,data,f,cutoff=analytics.AS_OF):
        self.data=data;self.f=f;self.cutoff=cutoff;self.today=day(cutoff[:10]);self.global_issues=[]
        self.index={key:{r['id']:r for r in data.get(key,[])} for key in TABLES}
        self.by={key:defaultdict(list) for key in ['attendance','skills','labor_entries','resource_calendars','production_resources']}
        for ds,groups in self.by.items():
            for r in data.get(ds,[]):
                if r.get('employee_id') not in self.index['employees']:
                    self.global_issues.append(f"{ds} / {r['id']}：工号缺少人员档案")
                groups[r.get('employee_id')].append(r)
        self.lower=dt((f['from'] or '1900-01-01')+'T00:00:00')
        self.upper=min(dt(cutoff),dt(f['to']+'T00:00:00')+timedelta(days=1)) if f['to'] else dt(cutoff)
        self.people={eid:self.person(e) for eid,e in self.index['employees'].items()}
        self.grants={s['id']:self.grant(s) for s in data.get('skills',[])}
        for r in data.get('production_resources',[]):
            try:
                day(r['effective'])
                if not r.get('process'):raise ValueError('工序未填写')
            except (KeyError,TypeError,ValueError):self.global_issues.append('production_resources / '+r['id']+'：生效日或工序未明确，岗位覆盖矩阵可能不完整')
    def in_day(self,value):return (not self.f['from'] or value>=self.f['from']) and value<=(self.f['to'] or self.cutoff[:10])
    def clip(self,r):
        a,b=dt(r['started']),dt(r['finished'])
        if a>=b:raise ValueError('起止时间倒置或为空')
        return a,b,max(a,self.lower),min(b,self.upper)
    def grant(self,s):
        e=self.index['employees'].get(s.get('employee_id'),{});issues=[];flags=['all'];valid=False;left=None
        try:
            a,b=day(s['approved']),day(s['expires']);left=(b-self.today).days
            if a>b or not s.get('process'):raise ValueError('批准/到期或工序无效')
            if not e or type(e.get('active')) is not bool:raise ValueError('人员档案或在职标识无效')
            if s['status'] not in ['有效','暂停','撤销','已暂停','已撤销','已过期','待审批']:raise ValueError('授权状态未知')
            if s['status']!='有效' or not e['active']:flags.append('inactive')
            elif a>self.today:flags.append('future')
            elif b<self.today:flags.append('expired')
            else:
                valid=True;flags.append('effective')
                if left==0:flags.append('today')
                elif left<=30:flags.append('soon')
        except (ValueError,TypeError,KeyError) as ex:issues.append(str(ex));flags.append('attention')
        return {k:s.get(k) for k in ['id','employee_id','process','level','approved','expires','status']}|{'name':e.get('name','档案缺失'),'department_id':e.get('department_id',''),'department':self.index['departments'].get(e.get('department_id'),{}).get('name','未关联部门'),'active':e.get('active'),'effective':valid,'days_to_due':left,'flags':flags,'issues':issues}
    def person(self,e):
        eid=e['id'];issues=[];refs={('employees',eid)};daily={};attendance=[];labor=[];calendars=[];spans=[];calspans=[];labor_totals=Counter();labor_daily=Counter();keys=Counter()
        dep=self.index['departments'].get(e.get('department_id'),{})
        if not dep:issues.append('人员所属部门未关联')
        else:refs.add(('departments',dep['id']))
        if type(e.get('active')) is not bool:issues.append('在职标识无效')
        def issue(ds,r,reason):issues.append(ds+' / '+r['id']+'：'+reason)
        for r in self.by['attendance'][eid]:
            try:
                day(r['date'])
                if not self.in_day(r['date']):continue
                refs.add(('attendance',r['id']));attendance.append({k:r.get(k) for k in ['id','date','shift',*HOURS,'overtime_hours','scheduled_hours']})
                k=(r['date'],r.get('shift'));keys[k]+=1
                if keys[k]>1:raise ValueError('同人同日同班次重复')
                vals={k:r.get(k) for k in HOURS}
                if any(not numeric(v) or v>24 for v in vals.values()):raise ValueError('分类工时缺失或超范围')
                total=sum(vals.values());overtime=r.get('overtime_hours');scheduled=r.get('scheduled_hours')
                if total>24.001 or not numeric(overtime) or overtime>total+.001:raise ValueError('总工时或加班子集无效')
                if scheduled is not None and (not numeric(scheduled) or scheduled>24 or abs(total-scheduled)>.001):raise ValueError('分类合计与班次排班不符')
                d=daily.setdefault(r['date'],dict(date=r['date'],total=0,overtime=0,scheduled=0,scheduled_known=True,**{k:0 for k in HOURS}))
                for k,v in vals.items():d[k]+=v
                d['total']+=total;d['overtime']+=overtime;d['scheduled_known']&=scheduled is not None;d['scheduled']+=scheduled or 0
                if d['total']>24.001:raise ValueError('同人同日分类工时超过24小时')
            except (ValueError,TypeError,KeyError) as ex:issue('attendance',r,str(ex));refs.add(('attendance',r['id']))
        for r in self.by['labor_entries'][eid]:
            try:
                a,b,start,end=self.clip(r)
                if start>=end:continue
                refs.add(('labor_entries',r['id']));op=self.index['operations'].get(r.get('operation_id'))
                if not op:raise ValueError('缺少报工事件')
                refs.add(('operations',op['id']))
                if op.get('employee_id')!=eid or op.get('work_order_id')!=r.get('work_order_id') or a<dt(op['started']) or b>dt(op['finished']):raise ValueError('人员/工单/时间与报工不符')
                if r.get('activity') not in ACTIVITY or not numeric(r.get('minutes')) or abs((b-a).total_seconds()/60-r['minutes'])>.001:raise ValueError('作业类别或分钟与起止不符')
                h=(end-start).total_seconds()/3600;spans.append((start,end));labor_totals[ACTIVITY[r['activity']]]+=h
                cursor=start
                while cursor<end:
                    stop=min(end,datetime.combine(cursor.date()+timedelta(days=1),datetime.min.time()))
                    labor_daily[cursor.date().isoformat()]+=(stop-cursor).total_seconds()/3600;cursor=stop
                labor.append({k:r.get(k) for k in ['id','operation_id','work_order_id','activity','started','finished']}|{'process':op.get('process'),'hours':h,'window_start':start.isoformat(),'window_end':end.isoformat()})
            except (ValueError,TypeError,KeyError) as ex:issue('labor_entries',r,str(ex));refs.add(('labor_entries',r['id']))
        for r in self.by['resource_calendars'][eid]:
            try:
                a,b,start,end=self.clip(r)
                if start>=end:continue
                refs.add(('resource_calendars',r['id']));resource=self.index['production_resources'].get(r.get('resource_id'))
                if not resource:raise ValueError('资源位未关联')
                refs.add(('production_resources',resource['id']));calspans.append((start,end))
                calendars.append({k:r.get(k) for k in ['id','resource_id','shift','started','finished']}|{'process':resource.get('process'),'window_start':start.isoformat(),'window_end':end.isoformat()})
            except (ValueError,TypeError,KeyError) as ex:issue('resource_calendars',r,str(ex));refs.add(('resource_calendars',r['id']))
        overlap=sum((b-a).total_seconds()/3600 for a,b in spans)-hours(spans)
        if overlap>1e-6:issues.append('同人作业明细时间重叠')
        cal_overlap=sum((b-a).total_seconds()/3600 for a,b in calspans)-hours(calspans)
        if cal_overlap>1e-6:issues.append('同人资源排班时间重叠')
        outside=hours(spans)-hours([(max(a,c),min(b,d)) for a,b in merged(spans) for c,d in merged(calspans) if max(a,c)<min(b,d)]) if calspans else None
        if outside is not None and outside>1e-6:issues.append('作业明细存在资源排班外时间')
        # Attendance includes support/wait not covered by task entries. Compare only
        # categories recorded in task entries, and only when both sources exist.
        totals={k:sum(d[k] for d in daily.values()) for k in HOURS}
        delta=sum(totals[k] for k in ['productive_hours','setup_hours','rework_hours'])-sum(labor_totals.values()) if attendance and labor else None
        if labor:
            for key in sorted(set(daily)|set(labor_daily)):
                if key not in daily:issues.append(key+'：作业明细未有对应班次记录');continue
                recorded=sum(daily[key][k] for k in ['productive_hours','setup_hours','rework_hours'])
                if abs(recorded-labor_daily[key])>.001:issues.append(key+'：班次作业分类与明细合计不符')
        for s in self.by['skills'][eid]:refs.add(('skills',s['id']))
        for resource in self.by['production_resources'][eid]:refs.add(('production_resources',resource['id']))
        flags=['all','recorded' if attendance else 'missing']
        if labor:flags.append('labor')
        if issues:flags.append('attention')
        valid=bool(attendance) and not issues
        row={k:e.get(k) for k in ['id','name','department_id','role','skill_level','active']}|{'department':dep.get('name','未关联部门'),'days':len(daily),'attendance_rows':len(attendance),'labor_rows':len(labor),'operation_count':len({r['operation_id'] for r in labor}),'total_hours':sum(totals.values()) if valid else None,'overtime_hours':sum(d['overtime'] for d in daily.values()) if valid else None,'labor_hours':sum(labor_totals.values()) if labor and not issues else None,'calendar_hours':hours(calspans) if calspans and not issues else None,'outside_hours':outside,'overlap_hours':overlap,'reconciliation_delta':delta,'categories':totals if valid else {k:None for k in HOURS},'flags':flags,'issues':issues}
        return {'row':row,'daily':sorted(daily.values(),key=lambda r:r['date']),'attendance':attendance,'labor':labor,'calendars':calendars,'sources':[{'dataset':ds,'key':key} for ds,key in sorted(refs)]}
    def selected(self):
        rows=[p['row'] for p in self.people.values()] if self.f['tab']=='hours' else list(self.grants.values())
        f=self.f
        return sorted([r for r in rows if (not f['department'] or r['department_id']==f['department']) and (not f['process'] or r['process']==f['process']) and (not f['q'] or f['q'].casefold() in ' '.join(str(r.get(k,'')) for k in ['id','employee_id','name','department','process']).casefold())],key=lambda r:r['id'])
    def detail(self,eid):
        if eid not in self.people:raise Record.DoesNotExist()
        p=self.people[eid]
        grants=[self.grants[r['id']] for r in self.by['skills'][eid]]
        return {**p,'grants':grants,'resource_roles':[{k:r.get(k) for k in ['id','process','station','effective']}|{'current_register_match':any(g['effective'] and g['process']==r.get('process') for g in grants)} for r in self.by['production_resources'][eid]]}
    def summary(self,rows):
        if self.f['tab']=='skills':
            effective=[r for r in rows if r['effective']]
            return {'objects':len(rows),'people':len({r['employee_id'] for r in rows}),'effective_people':len({r['employee_id'] for r in effective}),'effective_pairs':len({(r['employee_id'],r['process']) for r in effective}),'expiring':sum('today' in r['flags'] or 'soon' in r['flags'] for r in rows),'attention':sum('attention' in r['flags'] for r in rows)}
        valid=[r for r in rows if r['total_hours'] is not None]
        return {'objects':len(rows),'recorded':sum('recorded' in r['flags'] for r in rows),'verified':len(valid),'attention':sum('attention' in r['flags'] for r in rows),'missing':sum('missing' in r['flags'] for r in rows),'total_hours':sum(r['total_hours'] for r in valid) if valid else None,'overtime_hours':sum(r['overtime_hours'] for r in valid) if valid else None,'labor_people':sum(r['labor_hours'] is not None for r in rows),'labor_hours':sum(r['labor_hours'] for r in rows if r['labor_hours'] is not None) if any(r['labor_hours'] is not None for r in rows) else None}
    def breakdown(self,rows):
        if self.f['tab']=='skills':
            grouped=defaultdict(list)
            for r in rows:grouped[r['process']].append(r)
            required=defaultdict(set);gaps=[]
            matching_people={r['employee_id'] for r in rows}
            for eid,p in self.people.items():
                r=p['row'];f=self.f
                if f['department'] and r['department_id']!=f['department']:continue
                if f['q'] and eid not in matching_people and f['q'].casefold() not in (' '.join(str(r.get(k,'')) for k in ['id','name','department'])+' '+' '.join(x.get('process','') for x in self.by['production_resources'][eid])).casefold():continue
                for resource in self.by['production_resources'][eid]:
                    if f['process'] and resource['process']!=f['process']:continue
                    try:
                        if day(resource['effective'])>self.today:continue
                    except (KeyError,ValueError,TypeError):continue
                    required[resource['process']].add(eid)
            for process,people in required.items():
                matched={r['employee_id'] for r in grouped[process] if r['effective']}
                for eid in sorted(people-matched):gaps.append({'employee_id':eid,'name':self.people[eid]['row']['name'],'process':process})
            return {'processes':[{'process':k,'grants':len(grouped[k]),'effective_people':len({r['employee_id'] for r in grouped[k] if r['effective']}),'expiring_people':len({r['employee_id'] for r in grouped[k] if 'soon' in r['flags'] or 'today' in r['flags']}),'inactive_grants':sum(not r['effective'] for r in grouped[k]),'assigned_people':len(required[k]),'unmatched_assigned':sum(g['process']==k for g in gaps)} for k in sorted(set(grouped)|set(required))],'assignment_gaps':gaps}
        valid=[r for r in rows if r['total_hours'] is not None];daily=defaultdict(lambda:dict(hours=0,people=0));departments=defaultdict(lambda:dict(hours=0,people=0))
        for r in valid:
            departments[r['department']]['hours']+=r['total_hours'];departments[r['department']]['people']+=1
            for d in self.people[r['id']]['daily']:daily[d['date']]['hours']+=d['total'];daily[d['date']]['people']+=1
        days=[]
        if daily:
            cursor=day(self.f['from'] or min(daily));end=day(self.f['to'] or max(daily))
            while cursor<=end:
                key=cursor.isoformat();days.append({'day':key,**daily.get(key,{'hours':None,'people':0})});cursor+=timedelta(days=1)
        return {'categories':[{'name':label,'value':sum(r['categories'][k] for r in valid)} for k,label in HOURS.items()] if valid else [],'daily':days,'departments':[{'name':k,**v} for k,v in sorted(departments.items())]}
def current(f):
    data={k:[] for k in TABLES}
    for ds,value in Record.objects.filter(dataset__in=TABLES).values_list('dataset','values').iterator():data[ds].append(value)
    return Workforce(data,f)
