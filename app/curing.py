"""Furnace conditions supported by adjacent discrete points, never release."""
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

NOTICE = ('全部为合成演练。炉温不等于工件内部温度；相邻有效采样仅支持区间估计，不能证明区间内无波动或固化程度。'
          '所列条件达到不等于质量合格、工艺批准或生产放行。升降温低于保温下限不自动算超限。')
STATES = {'ready':'所列曲线条件达到','out':'所列条件未达到','missing':'采样依据不完整',
          'attention':'关系或条件待核对','open':'采集未闭合','future':'截止外登记','voided':'已作废'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def rule_hash():
    return hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('curing_schema.py').read_bytes()).hexdigest()


def dt(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo is None else None
    except (TypeError, ValueError):
        return None


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def channel_result(run, spec, samples, profile, cutoff):
    """Do not interpolate through missing points or join disjoint hold episodes."""
    issues=[]; missing=[]; start=dt(run.get('started')); end=dt(run.get('finished'))
    low, high, maximum = (spec.get(k) for k in ('hold_lsl','hold_usl','max_temp_c'))
    required, gap = profile.get('min_hold_minutes'), profile.get('max_gap_minutes')
    valid_spec = all(number(v) for v in (low,high,maximum,required,gap)) and low<=high<=maximum and required>0 and gap>0
    if not valid_spec: issues.append('规范上下限、连续分钟或间隔无效')
    if spec.get('sensor_kind')!='炉温': issues.append('传感器类型不支持炉温核对')
    rows=sorted(samples,key=lambda r:(r.get('sequence',0) if isinstance(r.get('sequence'),int) else 0,r['id']))
    sequences=[p.get('sequence') for p in rows]
    if any(not isinstance(s,int) or isinstance(s,bool) for s in sequences) or sequences!=list(range(1,len(rows)+1)):issues.append('通道序号重复、缺号或未从1开始')
    times=[dt(p.get('measured')) for p in rows]
    if any(t is None for t in times) or any(a>=b for a,b in zip(times,times[1:]) if a and b):issues.append('采样时间无效、重复或倒序')
    points=[]
    for row,t in zip(rows,times):
        in_window=bool(t and start and t>=start and t<=cutoff and (end is None or t<=end))
        valid=bool(in_window and row.get('quality')=='有效' and row.get('unit')=='℃' and number(row.get('value')))
        if not in_window:issues.append('采样时间在炉次窗口或业务截止之外')
        if row.get('unit')!='℃':issues.append('原始温度单位不是℃；未自动换算')
        if row.get('quality') not in ('有效','缺测','不可信'):issues.append('采样状态未知')
        if not number(row.get('value')) or row.get('quality')!='有效':missing.append('缺测或不可信采样')
        points.append(dict(id=row['id'],sequence=row.get('sequence'),measured=row.get('measured'),
                           value=row.get('value') if number(row.get('value')) else None,unit=row.get('unit'),quality=row.get('quality'),
                           value_c=row['value'] if valid else None,valid=valid))
    if not rows:missing.append('必需通道未采集')
    if end and (not times or times[0]!=start or times[-1]!=end):missing.append('曲线未覆盖声明起止边界')
    segments=[];active=None;gaps=[]
    if valid_spec:
        for i,(a,b) in enumerate(zip(points,points[1:])):
            ta,tb=times[i:i+2]
            delta=(tb-ta).total_seconds()/60 if ta and tb else None
            consecutive=isinstance(a['sequence'],int) and not isinstance(a['sequence'],bool) and isinstance(b['sequence'],int) and not isinstance(b['sequence'],bool) and b['sequence']==a['sequence']+1
            usable=bool(a['valid'] and b['valid'] and consecutive and delta is not None and 0<delta<=gap)
            if delta is not None and delta>gap:
                gaps.append(dict(started=a['measured'],finished=b['measured'],minutes=delta));missing.append('相邻采样间隔超过规范')
            inside=usable and low<=a['value_c']<=high and low<=b['value_c']<=high
            if inside:
                if active and active['finished']==a['measured']:active['finished']=b['measured'];active['minutes']+=delta
                else:
                    active=dict(started=a['measured'],finished=b['measured'],minutes=delta);segments.append(active)
            else:active=None
    longest=max((s['minutes'] for s in segments),default=0) if valid_spec else None
    hot=[p['id'] for p in points if valid_spec and p['valid'] and p['value_c']>maximum]
    state='attention' if issues else 'missing' if missing else 'out' if hot or longest<required else 'ready'
    return dict(profile_id=profile['id'],product_id=profile['product_id'],channel_code=spec['channel_code'],position=spec['position'],
                hold_lsl=low,hold_usl=high,max_temp_c=maximum,min_hold_minutes=required,max_gap_minutes=gap,
                state=state,issues=sorted(set(issues)),missing=sorted(set(missing)),points=points,gaps=gaps,
                segments=segments,longest_hold_minutes=longest,overtemp_ids=hot,
                max_observed_c=max((p['value_c'] for p in points if p['valid']),default=None))


def analyze(tables, refs, as_of):
    cutoff=dt(as_of)
    if cutoff is None:raise ValueError('业务截止时间无效')
    grouped=defaultdict(lambda:defaultdict(list))
    for ds,field in [('cure_loads','run_id'),('cure_samples','run_id'),('cure_channels','profile_id')]:
        for r in tables[ds]:grouped[ds][r[field]].append(r)
    runs=sorted(tables['cure_runs'],key=lambda r:r['id']);conflicts=defaultdict(set)
    # Calculate global resource conflicts BEFORE any display filter.
    for i,a in enumerate(runs):
        for b in runs[i+1:]:
            if a.get('voided') or b.get('voided') or a['resource_id']!=b['resource_id']:continue
            aa,az,ba,bz=(dt(r.get(k)) for r,k in [(a,'started'),(a,'finished'),(b,'started'),(b,'finished')])
            if all((aa,az,ba,bz)) and aa<cutoff and ba<cutoff and dt(a.get('registered')) and dt(b.get('registered')) and dt(a['registered'])<=cutoff and dt(b['registered'])<=cutoff and max(aa,ba)<min(az,bz):
                conflicts[a['id']].add(b['id']);conflicts[b['id']].add(a['id'])
    results=[]
    for run in runs:
        loads=grouped['cure_loads'][run['id']];samples=grouped['cure_samples'][run['id']]
        issues=[];missing=[];channels=[];bindings=[];profiles={};start=dt(run.get('started'));end=dt(run.get('finished'));registered=dt(run.get('registered'))
        if not start or not registered or (run.get('finished') and not end) or (end and start and end<=start):issues.append('炉次起止或登记时间无效')
        if registered and start and registered<start or end and registered and registered<end:issues.append('登记时间早于曲线记录')
        if run.get('capture_state') not in ('完整','部分','未采集'):issues.append('采集闭合状态未知')
        for field,n in [('load_count',len(loads)),('sample_count',len(samples)),('channel_count',len({p['channel_code'] for p in samples}))]:
            if not isinstance(run.get(field),int) or isinstance(run.get(field),bool) or run[field]<0 or run[field]!=n:missing.append('声明行数与实际不符：'+field)
        if not loads:missing.append('缺少装炉批次对应')
        resource=refs.get('production_resources',{}).get(run['resource_id']);equipment=refs.get('equipment',{}).get(run['equipment_id'])
        if not resource or resource.get('equipment_id')!=run['equipment_id'] or resource.get('process')!='浸漆固化' or resource.get('capacity')!=1:issues.append('独立资源位、设备或容量待核对')
        if resource and (not start or not dt(resource.get('effective','')+'T00:00:00') or start.date().isoformat()<resource['effective']):issues.append('资源位尚未生效')
        if not equipment or equipment.get('process')!='浸漆固化':issues.append('设备工序不是浸漆固化')
        if conflicts[run['id']]:issues.append('同一资源位炉次时间重叠')
        seen=set()
        for load in loads:
            op=refs.get('operations',{}).get(load['operation_id']);batch=refs.get('batches',{}).get(load['batch_id'])
            wo=refs.get('work_orders',{}).get(batch.get('work_order_id')) if batch else None
            product=refs.get('products',{}).get(wo.get('product_id')) if wo else None
            bound=bool(op and batch and wo and product and op.get('process')=='浸漆固化' and op.get('object_type')=='生产批次' and
                       op.get('object_id')==batch['id'] and op.get('work_order_id')==wo['id'] and op.get('equipment_id')==run['equipment_id'] and
                       op.get('resource_id')==run['resource_id'] and op.get('started')==run['started'] and (end is None or op.get('finished')==run['finished']))
            if not bound:issues.append('装炉批次与工单、报工、设备、资源位或起止不一致：'+load['id'])
            if (load['operation_id'],load['batch_id']) in seen:issues.append('同一炉次装载对应重复')
            seen.add((load['operation_id'],load['batch_id']))
            qty=load.get('qty')
            if load.get('unit')!='件' or not isinstance(qty,int) or isinstance(qty,bool) or qty<=0 or (op and qty>op.get('input_qty',0)) or (batch and qty>batch.get('qty',0)) or (resource and qty>resource.get('max_batch_qty',0)):issues.append('装载数量、单位或容量待核对：'+load['id'])
            route_ok=bool(wo and batch and any(r.get('product_id')==wo['product_id'] and r.get('version')==wo['route_version'] and r.get('process')=='浸漆固化' and r.get('branch')==batch['kind'] for r in refs.get('routes',{}).values()))
            if not route_ok:issues.append('工单配置路线缺少本批浸漆固化工序')
            matches=[p for p in tables['cure_profiles'] if wo and p['product_id']==wo['product_id'] and p['route_version']==wo['route_version'] and p['program_code']==run['program_code'] and p['program_version']==run['program_version']]
            if len(matches)!=1:issues.append('实际程序版本无唯一适用规范：'+load['id'])
            else:
                p=matches[0];effective=dt(p.get('effective'));expiry=dt(p.get('expires'))
                if not effective or (p.get('expires') and not expiry) or not start or start<effective or (expiry and (end or cutoff)>=expiry):issues.append('规范未覆盖整个曲线区间：'+p['id'])
                profiles[p['id']]=p
            orders=[]
            if bound:
                for a in refs.get('allocations',{}).values():
                    line=refs.get('order_lines',{}).get(a.get('order_line_id'))
                    if a.get('work_order_id')==wo['id'] and line and line.get('product_id')==wo['product_id'] and isinstance(a.get('qty'),int) and a['qty']>0 and a.get('effective','9999')<=start.date().isoformat():
                        orders.append(dict(allocation_id=a['id'],order_line_id=line['id'],order_id=line['order_id'],allocated_qty=a['qty']))
            bindings.append(dict(**load,linked=bound,work_order_id=wo['id'] if bound else None,product_id=wo['product_id'] if bound else None,
                                 orders=sorted(orders,key=lambda a:a['allocation_id']),order_notice='工单分配关系；未证明本炉每件与订单一一对应'))
        expected=set()
        for p in profiles.values():
            specs=grouped['cure_channels'][p['id']];codes=[s['channel_code'] for s in specs]
            if not specs or len(codes)!=len(set(codes)):issues.append('规范通道缺失或重复：'+p['id'])
            for spec in specs:
                expected.add(spec['channel_code'])
                channels.append(channel_result(run,spec,[s for s in samples if s['channel_code']==spec['channel_code']],p,cutoff))
        if profiles and set(p['channel_code'] for p in samples)-expected:issues.append('采样存在未声明规范通道')
        if resource and sum(l.get('qty',0) for l in loads if isinstance(l.get('qty'),int))>resource.get('max_batch_qty',0):issues.append('同炉装载合计超过独立资源位容量')
        issues+= [v for c in channels for v in c['issues']];missing+=[v for c in channels for v in c['missing']]
        future=bool(start and start>cutoff or registered and registered>cutoff)
        state='voided' if run.get('voided') else 'future' if future else 'attention' if issues else 'open' if not end or run.get('capture_state')!='完整' else 'missing' if missing else 'out' if any(c['state']=='out' for c in channels) else 'ready'
        results.append(dict(run=run,state=state,label=STATES[state],issues=sorted(set(issues)),missing=sorted(set(missing)),
                            loads=bindings,channels=channels,profiles=list(profiles.values()),conflict_ids=sorted(conflicts[run['id']]),sample_rows=len(samples)))
    return dict(rows=results,as_of=as_of,notice=NOTICE,synthetic=True)


def filters(value):
    allowed=('state','resource','product','from','to','q')
    if not isinstance(value,dict) or set(value)-set(allowed):raise ValueError('固化范围字段无效')
    result={k:value.get(k,'') for k in allowed}
    if any(not isinstance(v,str) or len(v)>120 for v in result.values()):raise ValueError('范围值必须为不超过120字的文字')
    if result['state'] and result['state'] not in STATES:raise ValueError('固化状态无效')
    for k in ('from','to'):
        if result[k] and (len(result[k])!=10 or dt(result[k]+'T00:00:00') is None):raise ValueError('曲线起点日期须为YYYY-MM-DD')
    if result['from'] and result['to'] and result['from']>result['to']:raise ValueError('起点日期范围倒置')
    return result


def scoped(result, scope):
    selected=[]
    for r in result['rows']:
        run=r['run'];day=run['started'][:10]
        if scope['state'] and r['state']!=scope['state'] or scope['resource'] and run['resource_id']!=scope['resource']:continue
        if scope['product'] and not any(l['product_id']==scope['product'] for l in r['loads']):continue
        if scope['from'] and day<scope['from'] or scope['to'] and day>scope['to']:continue
        text=' '.join([run['id'],*[' '.join(str(l.get(k,'')) for k in ('batch_id','operation_id','work_order_id','product_id')) for l in r['loads']]])
        if scope['q'] and scope['q'].casefold() not in text.casefold():continue
        selected.append(r)
    return dict(**{k:v for k,v in result.items() if k!='rows'},rows=selected,scope=scope,
                summary=dict(runs=len(selected),states=dict(Counter(r['state'] for r in selected)),sample_rows=sum(r['sample_rows'] for r in selected),
                             load_rows=sum(len(r['loads']) for r in selected),grain='炉次计数；装載件数不合并为整机台数；日期筛选按曲线起点'))
