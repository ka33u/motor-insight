"""Versioned whole-factory daily assembly commitments and observed SN counts.

Plans are full snapshots. A baseline is the last published snapshot available
at its declared freeze time; later edits never replace that baseline. Coverage
confirmation binds the entire day's raw SN facts, including the empty set.
"""
import hashlib,json,re
from collections import defaultdict
from datetime import date,datetime
from . import analytics
from .models import Record

DATASETS=['assembly_plan_versions','assembly_plan_lines','assembly_data_checks']
SOURCES=DATASETS+['work_orders','products','units']
NOTE='全厂装配日口径，以整机档案的装配时间计台数，不表示质检合格、完工入库或交付。冻结基线取冻结时点前最后发布的完整版本；当前计划取业务截止前最后发布版本。每工单当日兑现量取实际与计划的较小值，超产和未排产量不抵其他工单欠量。'

def day(x):
    try:return isinstance(x,str) and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}',x)) and date.fromisoformat(x)
    except ValueError:return False
def stamp(x):
    try:return isinstance(x,str) and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}',x)) and datetime.fromisoformat(x)
    except ValueError:return False
def count(x):return type(x) is int and x>=0
def text(x):return isinstance(x,str) and bool(x.strip())
def signature(rows):return hashlib.sha256(json.dumps(sorted(rows,key=lambda x:x['id']),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def ref(ds,key):return dict(dataset=ds,key=key)
def params(p):
    out={k:str(p.get(k,'')).strip() for k in ['from','to','family','q','attention']}
    if any(out[k] and not day(out[k]) for k in ['from','to']) or out['from'] and out['to'] and out['from']>out['to']:raise ValueError('计划日期范围无效')
    if out['attention'] not in ['','short','changed','extra','issues']:raise ValueError('计划核对范围不可用')
    if any(len(v)>150 for v in out.values()):raise ValueError('查询条件过长')
    return out

class Plans:
    def __init__(self,tables=None,as_of=None):
        self.cutoff=as_of or analytics.AS_OF
        if not stamp(self.cutoff):raise ValueError('业务截止时间无效')
        self.tables=tables if tables is not None else {ds:list(Record.objects.filter(dataset=ds).values_list('values',flat=True)) for ds in SOURCES}
        self.maps={ds:{r['id']:r for r in self.tables.get(ds,[])} for ds in SOURCES};self.global_issues=[];self.days={};self.rows={}
        headers=defaultdict(list);lines=defaultdict(list);units=defaultdict(list);checks=defaultdict(list)
        for h in self.tables.get(DATASETS[0],[]):
            if not day(h.get('production_date')):self.global_issues.append(h['id']+'：装配日期无效')
            else:headers[h['production_date']].append(h)
        for line in self.tables.get(DATASETS[1],[]):
            lines[line.get('version_id')].append(line)
            if line.get('version_id') not in self.maps[DATASETS[0]]:self.global_issues.append(line['id']+'：计划版本缺失')
        invalid_units=[]
        for u in self.tables.get('units',[]):
            if not stamp(u.get('assembly_at')):invalid_units.append(u['id']);continue
            units[u['assembly_at'][:10]].append(u)
        self.global_issues += [uid+'：装配时间无效，无法确认日期范围' for uid in invalid_units]
        for c in self.tables.get(DATASETS[2],[]):
            if day(c.get('production_date')):checks[c['production_date']].append(c)
            else:self.global_issues.append(c['id']+'：资料确认日期无效')
        for date_key in sorted(set(headers)|set(units)|set(checks)):
            self.build_day(date_key,headers[date_key],lines,units[date_key],checks[date_key],bool(invalid_units))
        # A work order may be split across days, but cannot be planned above its
        # registered total in the simultaneous chosen daily snapshots.
        for mode in ['baseline','current']:
            by_order=defaultdict(list)
            for d in self.days.values():
                selected=d.get(mode)
                if selected and not selected['issues']:
                    for line in selected['lines']:by_order[line['work_order_id']].append((d,line))
            for wo,parts in by_order.items():
                registered=self.maps['work_orders'].get(wo,{}).get('planned_qty')
                if count(registered) and sum(line['qty'] for _,line in parts)>registered:
                    for d,_ in parts:
                        issue=('冻结基线' if mode=='baseline' else '当前计划')+'跨日累计超过工单登记总量：'+wo
                        if issue not in d['issues']:d['issues'].append(issue)
                        for row in d['rows']:row['issues']=list(dict.fromkeys([*row['issues'],issue]));row[mode+'_eligible']=False
        self.rows={r['id']:r for d in self.days.values() for r in d['rows']}

    def build_day(self,date_key,headers,all_lines,all_units,checks,invalid_units):
        issues=[];versions=[];ordered=sorted(headers,key=lambda h:(h.get('version') if type(h.get('version')) is int else -1,h['id']))
        if len({h.get('series') for h in headers})>1:issues.append('同一装配日存在多个计划系列，不能合并')
        if len({h.get('freeze_at') for h in headers})>1:issues.append('同系列冻结时点变化，基线无法核对')
        previous=None;last_release=None
        for i,h in enumerate(ordered):
            errors=[];items=all_lines[h['id']];release=h.get('released');freeze=h.get('freeze_at')
            if not text(h.get('series')) or type(h.get('version')) is not int or h['version']!=i+1 or h.get('supersedes_id')!=(previous['id'] if previous else None):issues.append('版本链不连续、重复或引用错误')
            if not stamp(freeze) or freeze>=date_key+'T00:00:00':issues.append('冻结时间必须早于计划日开始')
            if h.get('status') not in ['已发布','草稿','作废']:issues.append('版本发布状态无效')
            if h.get('status')=='已发布':
                if not stamp(release):issues.append('已发布版本缺少有效发布时间')
                elif last_release and release<=last_release:issues.append('发布时间未按版本递增')
                else:last_release=release
            if not text(h.get('owner')) or not text(h.get('reason')) or not text(h.get('basis')):errors.append('计划岗位、依据或调整说明缺失')
            if not count(h.get('line_count')) or h['line_count']!=len(items):errors.append('完整明细行数与实际导入不符')
            seen=set()
            for line in items:
                wo=self.maps['work_orders'].get(line.get('work_order_id'));product=self.maps['products'].get(line.get('product_id'))
                if line.get('work_order_id') in seen:errors.append('同版本同工单重复安排')
                seen.add(line.get('work_order_id'))
                if not wo or not product or wo.get('product_id')!=line.get('product_id'):errors.append('计划明细的工单与配置无法核对')
                if not count(line.get('qty')):errors.append('计划台数不是非负整数')
                elif wo and (not count(wo.get('planned_qty')) or line['qty']>wo['planned_qty']):errors.append('计划台数超过工单登记总量或工单数量无效')
                if not text(line.get('reason')):errors.append('计划明细缺少安排说明')
            versions.append({**h,'lines':items,'issues':list(dict.fromkeys(errors)),'qty':sum(x['qty'] for x in items) if not errors else None,'after_freeze':bool(stamp(release) and stamp(freeze) and release>freeze),'after_day':bool(stamp(release) and release[:10]>date_key)})
            previous=h
        published=[h for h in versions if h['status']=='已发布' and stamp(h.get('released')) and h['released']<=self.cutoff]
        baseline=[h for h in published if stamp(h.get('freeze_at')) and h['released']<=h['freeze_at']]
        base=baseline[-1] if baseline else None;current=published[-1] if published else None
        if issues:base=current=None
        issues=list(dict.fromkeys(issues))
        if not headers:issues.append('该日没有导入计划版本')
        elif not base:issues.append('缺少可核对的事前冻结基线')
        if not current:issues.append('截止时点没有可核对的已发布计划')
        for label,h in [('冻结基线',base),('当前计划',current)]:
            if h and h['issues']:issues += [label+'：'+x for x in h['issues']]
        observed=[u for u in all_units if u['assembly_at']<=self.cutoff];unit_issues=[]
        for u in observed:
            wo=self.maps['work_orders'].get(u.get('work_order_id'))
            if not wo or wo.get('product_id')!=u.get('product_id') or u.get('product_id') not in self.maps['products']:unit_issues.append('装配SN的工单或配置无法核对：'+u['id'])
        if invalid_units:unit_issues.append('存在无法归日的装配时间记录')
        actual_signature=signature(all_units);valid_checks=[]
        for c in checks:
            if c.get('voided') is False and stamp(c.get('confirmed')) and c['confirmed']<=self.cutoff:valid_checks.append(c)
        latest=max((c['confirmed'] for c in valid_checks),default=None);latest_checks=[c for c in valid_checks if c['confirmed']==latest]
        confirmation=latest_checks[0] if len(latest_checks)==1 else None
        confirmed=bool(confirmation and confirmation.get('status')=='完整' and stamp(confirmation.get('through')) and confirmation['through']>=date_key+'T23:59:59' and confirmation['confirmed']>=confirmation['through'] and confirmation.get('data_signature')==actual_signature and text(confirmation.get('owner')) and text(confirmation.get('note')))
        state='future' if date_key>self.cutoff[:10] else 'in_progress' if date_key==self.cutoff[:10] else 'confirmed' if confirmed and not unit_issues else 'unconfirmed'
        if state=='unconfirmed':issues.append('装配资料确认缺失、待补、冲突或与当前SN事实不符')
        issues+=unit_issues
        bmap={x['work_order_id']:x for x in base['lines']} if base and not base['issues'] else {};cmap={x['work_order_id']:x for x in current['lines']} if current and not current['issues'] else {}
        actual=defaultdict(list)
        for u in observed:actual[str(u.get('work_order_id') or '未关联工单')].append(u)
        orders=set(bmap)|set(cmap)|set(actual)
        # Keep malformed version lines visible so broken imports cannot produce
        # a healthy empty worklist or disappear from the day's issue count.
        for h in versions:
            for line in h['lines']:orders.add(str(line.get('work_order_id') or '未关联工单'))
        rows=[]
        for wo_id in sorted(orders):
            wo=self.maps['work_orders'].get(wo_id,{});pid=wo.get('product_id');product=self.maps['products'].get(pid,{})
            bq=bmap.get(wo_id,{}).get('qty',0) if base and not base['issues'] else None;cq=cmap.get(wo_id,{}).get('qty',0) if current and not current['issues'] else None
            qty=len(actual[wo_id]) if state!='future' else None
            # A missing baseline does not invalidate comparison with a valid
            # current plan. Version integrity and actual coverage still apply.
            actual_ok=state=='confirmed' and not unit_issues
            refs=[ref(DATASETS[0],h['id']) for h in versions]+[ref(DATASETS[2],c['id']) for c in checks]+[ref('units',u['id']) for u in actual[wo_id]]
            refs += [ref(DATASETS[1],line['id']) for h in versions for line in h['lines'] if line.get('work_order_id')==wo_id]
            if wo:refs.append(ref('work_orders',wo_id))
            if product:refs.append(ref('products',pid))
            rows.append(dict(id=date_key+'~'+wo_id,date=date_key,work_order_id=wo_id,product_id=pid,family=product.get('family','未关联配置'),baseline_qty=bq,current_qty=cq,observed_qty=qty,baseline_eligible=bool(actual_ok and bq is not None),current_eligible=bool(actual_ok and cq is not None),changed=None if bq is None or cq is None else bq!=cq,adjustment=None if bq is None or cq is None else cq-bq,baseline_fulfilled=min(qty,bq) if qty is not None and bq is not None else None,current_fulfilled=min(qty,cq) if qty is not None and cq is not None else None,baseline_short=max(bq-qty,0) if qty is not None and bq is not None else None,current_extra=max(qty-cq,0) if qty is not None and cq is not None else None,state=state,issues=list(issues),sources=refs,units=actual[wo_id]))
        self.days[date_key]=dict(date=date_key,baseline=base,current=current,versions=versions,checks=checks,confirmation=confirmation,actual_signature=actual_signature,state=state,issues=list(dict.fromkeys(issues)),rows=rows,excluded_future_units=len(all_units)-len(observed))

    def selected(self,f,date_key=None):
        rows=list(self.rows.values())
        if date_key:rows=[r for r in rows if r['date']==date_key]
        for key,op in [('from',lambda a,b:a>=b),('to',lambda a,b:a<=b)]:
            if f[key]:rows=[r for r in rows if op(r['date'],f[key])]
        if f['family']:rows=[r for r in rows if r['family']==f['family']]
        if f['q']:rows=[r for r in rows if f['q'].lower() in ' '.join(str(r.get(k) or '') for k in ['id','work_order_id','product_id','family']).lower()]
        a=f['attention']
        if a=='short':rows=[r for r in rows if r['baseline_eligible'] and r['baseline_short']>0]
        if a=='changed':rows=[r for r in rows if r['changed']]
        if a=='extra':rows=[r for r in rows if r['current_eligible'] and r['current_extra']>0]
        if a=='issues':rows=[r for r in rows if r['issues']]
        return sorted(rows,key=lambda r:(r['date'],r['work_order_id']))

def summary(rows):
    out={'rows':len(rows),'dates':len({r['date'] for r in rows}),'observed_qty':sum(r['observed_qty'] or 0 for r in rows) if any(r['observed_qty'] is not None for r in rows) else None,'changed_rows':sum(r['changed'] is True for r in rows),'issue_rows':sum(bool(r['issues']) for r in rows)}
    for mode in ['baseline','current']:
        valid=[r for r in rows if r[mode+'_eligible']];planned=sum(r[mode+'_qty'] for r in valid);fulfilled=sum(r[mode+'_fulfilled'] for r in valid)
        out.update({mode+'_known_rows':len(valid),mode+'_unknown_rows':len(rows)-len(valid),mode+'_planned':planned,mode+'_fulfilled':fulfilled,mode+'_rate':fulfilled/planned*100 if planned else None})
        scheduled=[r[mode+'_qty'] for r in rows if r[mode+'_qty'] is not None]
        out[mode+'_scheduled']=sum(scheduled) if scheduled else None
        out[mode+'_scheduled_unknown_rows']=len(rows)-len(scheduled)
    out['baseline_short']=sum(r['baseline_short'] for r in rows if r['baseline_eligible']);out['current_extra']=sum(r['current_extra'] for r in rows if r['current_eligible'])
    return out
def safe(row):return {k:v for k,v in row.items() if k not in ['sources','units']}
