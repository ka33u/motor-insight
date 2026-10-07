"""Atomic, root-share WIP journal. Reporting quantities are never stock inputs."""
from collections import defaultdict,Counter
from datetime import datetime,date
from . import analytics
from .engineering import refs,unique_sources

TABLES=['wip_locations','wip_lots','wip_openings','wip_event_versions','wip_event_lines']
BASE=['batches','work_orders','products','units','operations','employees','allocations','order_lines','orders','customers']
ACTIVE={'生产缓冲','返工区','隔离区'};TERMINAL={'装配耗用','报废登记'}
KINDS={'工序交接','拆批','合批','返工转入','返工返回','隔离转入','隔离解除','装配耗用','报废登记'}
STATES={'all':'全部原批次','active':'有在制份额','consumed':'全部登记耗用','closed':'含报废的闭合批次','attention':'位置或资料待核查','missing':'缺有效基准'}
NOTE='全部合成模拟。以原生产批次份额核对基准、交接及去向；定子/转子件数分列，不累加为电机台数。完整版本一次应用，错误最新版不回退，缺口和依赖未知会阻止受影响批次当前位置判断。已登记位置不是现场实盘；位置停留是自然历时，不直接归因排队或人员工时。位置导出同一整批件数会在各来源行重复，只汇总份额件数，不累加整批列。'
TIME_NOTE='业务截止决定已发生的基准、流转与装配引用；登记截止决定可采用的台账版本。仅重放在制基准和流转的登记时间，主数据、原批次、SN、报工及订单关系采用当前导入记录，不构成全厂历史数据库快照；台账登记时点也不是平台导入时点。'

def clock(v):
    if not isinstance(v,str) or len(v)!=19:return None
    try:d=datetime.fromisoformat(v);return d if d.tzinfo is None and d.isoformat(timespec='seconds')==v else None
    except ValueError:return None
def positive(v):return type(v) is int and v>0
def names(v):
    if not isinstance(v,str):return None
    ids=v.split(',')
    return ids if 1<=len(ids)<=50 and len(set(ids))==len(ids) and all(x and x==x.strip() and len(x)<=150 for x in ids) else None
def grouping(rows,key):
    out=defaultdict(list)
    for r in rows:out[r.get(key)].append(r)
    return out
def unique(v):return list(dict.fromkeys(v))

class Wip:
    def __init__(self,data=None,cutoff=None,known_cutoff=None):
        self.data=data if data is not None else analytics.tables();self.cutoff=cutoff or analytics.AS_OF;self.end=clock(self.cutoff)
        if not self.end:raise ValueError('在制截止格式无效')
        self.known_cutoff=known_cutoff or self.cutoff;self.known_end=clock(self.known_cutoff)
        if not self.known_end or self.known_end<self.end:raise ValueError('登记截止须为标准本地时间且不早于业务截止')
        self.idx={ds:{r['id']:r for r in self.data.get(ds,[])} for ds in TABLES+BASE}
        self.lines=grouping(self.data.get('wip_event_lines',[]),'event_id');self.versions=grouping(self.data.get('wip_event_versions',[]),'series')
        self.openings=grouping(self.data.get('wip_openings',[]),'root_batch_id');self.inv={};self.members=defaultdict(set);self.born=set()
        self.begin={};self.origins={};self.tainted=defaultdict(list);self.global_issues=[];self.events=[];self.last={};self.entered={};self.parents=defaultdict(list)
        self.terminal=[];self.sn_used=set();self.roots={};self.future_roots=0;self.expected=defaultdict(set)
        for r in self.data.get('batches',[]):
            when=clock(r.get('created'))
            if when and when>self.end:self.future_roots+=1;continue
            if r.get('kind') not in ['定子','转子']:continue
            self.roots[r['id']]=r
        self.initialize()
        for series,versions in self.versions.items():self.events.append(self.select(series,versions))
        # Conservative scope propagation includes declared parents even if a
        # malformed complete version omitted all detailed lines for that parent.
        relevant=[e for e in self.events if not e['future'] and not e['withdrawn']]
        changed=True
        while changed:
            changed=False
            for e in relevant:
                roots=set(e['roots'])
                for lot in e['inputs']:roots|=self.members[lot]
                for lot in e['outputs']:
                    declared={x['root_batch_id'] for x in e['lines'] if x.get('side')=='入' and x.get('lot_id')==lot and x.get('root_batch_id') in self.roots}
                    before=len(self.members[lot]);self.members[lot]|=declared or roots;changed|=len(self.members[lot])!=before
                if roots!=e['roots']:e['roots']=roots;changed=True
        for e in self.events:
            if not e['roots']:
                for lot in e['inputs']+e['outputs']:e['roots']|=self.members[lot]
            if not e['future'] and not e['withdrawn'] and not e['roots']:self.global_issues.append(e['series']+'无法确定受影响原批次范围')
        self.detect_ties(relevant)
        for e in sorted(relevant,key=lambda e:(e['occurred'] or '',e['sequence'] if positive(e['sequence']) else 0,e['series'])):self.apply(e)
        for u in self.data.get('units',[]):
            at=clock(u.get('assembly_at'))
            if at and at>self.end:continue
            for field,kind in [('stator_batch','定子'),('rotor_batch','转子')]:
                root=u.get(field)
                if root in self.roots:
                    self.expected[root].add(u['id'])
                    if not at:self.tainted[root].append('引用SN装配时间缺失或无效')
                    if (u['id'],kind) not in self.sn_used:self.tainted[root].append('已装配SN缺有效耗用登记')
        # A current physical container cannot claim a verified whole quantity
        # when another root's share in that same position is unresolved.
        changed=True
        while changed:
            changed=False
            for lot in self.born:
                active_roots={r for (l,z,r),q in self.inv.items() if l==lot and q>0 and self.idx['wip_locations'][z]['kind'] in ACTIVE}
                if any(r in self.tainted for r in active_roots):
                    for r in active_roots:
                        if r not in self.tainted:self.tainted[r].append('同周转批次其他来源份额待核查');changed=True
        self.index={key:self.result(r) for key,r in self.roots.items()};self.rows=list(self.index.values())
        for ds,parent,key in [('wip_openings','batches','root_batch_id'),('wip_event_lines','wip_event_versions','event_id')]:
            for r in self.data.get(ds,[]):
                if r.get(key) not in self.idx[parent]:self.global_issues.append(r['id']+'缺少'+parent+'引用')

    def lot_errors(self,lot,root=None,at=None):
        issues=[];l=self.idx['wip_lots'].get(lot)
        if not l:return ['周转批次档案缺失']
        if l.get('kind') not in ['定子','转子'] or l.get('product_id') not in self.idx['products']:issues.append('周转批次配置或分支缺失')
        created=clock(l.get('created'))
        if not created or (at and created>at):issues.append('周转批次建立时间缺失或晚于流转')
        if not l.get('container') or not l.get('note'):issues.append('周转箱或批次说明缺失')
        if root:
            r=self.idx['batches'].get(root);w=self.idx['work_orders'].get(r.get('work_order_id')) if r else None
            if not r or not w or r.get('kind')!=l.get('kind') or w.get('product_id')!=l.get('product_id'):issues.append('原批次与周转批次配置、分支不一致')
        return issues

    def initialize(self):
        for key,r in self.roots.items():
            issues=[];rows=[];w=self.idx['work_orders'].get(r.get('work_order_id'));created=clock(r.get('created'))
            if not w or w.get('product_id') not in self.idx['products']:issues.append('原批次工单或配置缺失')
            if not created or not positive(r.get('qty')):issues.append('原批次建立时间或数量无效')
            for o in self.openings[key]:
                t,known=clock(o.get('occurred')),clock(o.get('recorded'))
                if (t and t>self.end) or (known and known>self.known_end):continue
                rows.append(o);self.members[o.get('lot_id')].add(key)
                if not t or not known or known<t or (created and t and t<created):issues.append('基准发生、登记或原批次时间不一致')
                if not positive(o.get('qty')):issues.append('基准件数须为正整数')
                if o.get('owner_id') not in self.idx['employees'] or not o.get('reference') or not o.get('note'):issues.append('基准人员或依据缺失')
                loc=self.idx['wip_locations'].get(o.get('location_id'))
                if not loc or loc.get('kind') not in ACTIVE:issues.append('基准位置缺失或属于耗用/报废端点')
                issues+=self.lot_errors(o.get('lot_id'),key,t)
            if not rows:issues.append('缺截止前基准登记')
            if len({o.get('occurred') for o in rows})>1:issues.append('同原批次基准时间不一致')
            keys=[(o.get('lot_id'),o.get('location_id')) for o in rows]
            if len(keys)!=len(set(keys)):issues.append('同原批次基准位置重复')
            if rows and all(positive(o.get('qty')) for o in rows) and sum(o['qty'] for o in rows)!=r.get('qty'):issues.append('完整基准与原批次数量未对平')
            self.origins[key]=rows
            if issues:self.tainted[key]+=unique(issues);continue
            self.begin[key]=rows[0]['occurred']
            for o in rows:
                k=(o['lot_id'],o['location_id'],key);self.inv[k]=o['qty'];self.born.add(o['lot_id']);self.last[o['lot_id']]=o['occurred'];self.entered[o['lot_id'],o['location_id']]=o['occurred']
        for lot in self.born:
            locations={loc for (l,loc,r),q in self.inv.items() if l==lot and q>0}
            if len(locations)>1:
                for key in self.members[lot]:self.tainted[key].append('同一周转批次基准同时登记多个实物位置')
            times={o['occurred'] for rows in self.origins.values() for o in rows if o.get('lot_id')==lot and clock(o.get('occurred')) and o['occurred']<=self.cutoff}
            if len(times)>1:
                for key in self.members[lot]:self.tainted[key].append('同一周转批次不同根批次基准时间不一致')

    def select(self,series,versions):
        candidates=[v for v in versions if (not clock(v.get('recorded')) or v['recorded']<=self.known_cutoff) and v.get('status')!='草稿']
        eligible=[v for v in versions if not clock(v.get('recorded')) or v['recorded']<=self.known_cutoff];issues=[];chosen=None
        pure_future=bool(candidates) and all(clock(v.get('occurred')) and clock(v.get('recorded')) and self.end<clock(v['occurred'])<=clock(v['recorded']) for v in candidates)
        if any(not clock(v.get('recorded')) for v in candidates):issues.append('版本登记时间无法排序')
        if any(n>1 for n in Counter(v.get('recorded') for v in candidates).values()):issues.append('流转版本登记同刻并列')
        if any(n>1 for n in Counter(v.get('version') for v in eligible).values()):issues.append('流转版本号重复')
        if candidates and not issues:chosen=max(candidates,key=lambda v:v['recorded'])
        versions_for_scope=[chosen] if chosen else candidates
        lines=[line for v in versions_for_scope for line in self.lines[v['id']]]
        roots={x.get('root_batch_id') for x in lines if x.get('root_batch_id') in self.roots};inputs=[];outputs=[]
        for v in versions_for_scope:inputs+=names(v.get('input_lots')) or [];outputs+=names(v.get('output_lots')) or []
        e=dict(series=series,header=chosen,history=versions,lines=lines,roots=roots,inputs=unique(inputs),outputs=unique(outputs),
          issues=issues,occurred=chosen.get('occurred') if chosen else None,sequence=chosen.get('sequence') if chosen else None,
          future=pure_future or bool(chosen and clock(chosen.get('occurred')) and chosen['occurred']>self.cutoff),withdrawn=bool(chosen and chosen.get('status')=='作废'),applied=False)
        e['history_roots']={x.get('root_batch_id') for v in versions for x in self.lines[v['id']] if x.get('root_batch_id') in self.roots}
        if not candidates:e.update(future=True,issues=['尚无截止前有效登记版本']);return e
        if not chosen:return e
        prefix=sorted([v for v in eligible if positive(v.get('version')) and v['version']<=chosen.get('version',0)],key=lambda v:v['version']) if positive(chosen.get('version')) else []
        if not prefix or [v['version'] for v in prefix]!=list(range(1,chosen['version']+1)):issues.append('版本链不连续')
        for i,v in enumerate(prefix):
            if v.get('previous_id')!=(prefix[i-1]['id'] if i else None):issues.append('流转版本前序不一致')
            if i and (not clock(v.get('recorded')) or v['recorded']<=prefix[i-1].get('recorded','')):issues.append('流转版本登记时间未递增')
        t=clock(chosen.get('occurred'));known=clock(chosen.get('recorded'))
        if not t or not known or (t and known and known<t):issues.append('流转发生和登记时间不一致')
        if not positive(chosen.get('sequence')):issues.append('发生顺序须为正整数')
        if chosen.get('status') not in ['登记','作废']:issues.append('未知流转登记状态')
        if chosen.get('kind') not in KINDS:issues.append('未知流转类别')
        if not names(chosen.get('input_lots')) or not names(chosen.get('output_lots')):issues.append('输入/输出周转批次清单无效')
        if not positive(chosen.get('line_count')) or chosen.get('line_count')!=len(lines):issues.append('完整流转明细行数不符')
        if any(chosen.get(k) not in self.idx['employees'] for k in ['sender_id','receiver_id']) or not chosen.get('reference') or not chosen.get('note'):issues.append('移交、接收人员或依据缺失')
        if issues:e.update(future=pure_future,withdrawn=False)
        return e

    def detect_ties(self,events):
        times=grouping(events,'occurred')
        for group in times.values():
            for i,a in enumerate(group):
                for b in group[i+1:]:
                    if a['sequence']==b['sequence'] and set(a['inputs']+a['outputs'])&set(b['inputs']+b['outputs']):
                        a['issues'].append('同刻同顺序流转涉及同一周转批次');b['issues'].append('同刻同顺序流转涉及同一周转批次')

    def apply(self,e):
        issues=e['issues'];h=e['header'];rows=e['lines'];at=clock(e['occurred'])
        if not h or issues:self.pause(e);return
        if any(root in self.tainted for root in e['roots']):issues.append('关联原批次的前序位置已无法核定')
        if any(root not in self.begin or e['occurred']<self.begin[root] for root in e['roots']):issues.append('流转早于基准或缺有效基准')
        ins=[];outs=[];seen=set();root_out=Counter();root_in=Counter();take=Counter();give=Counter();new_sn=set()
        for line in rows:
            side=line.get('side');lot=line.get('lot_id');location=line.get('location_id');root=line.get('root_batch_id');sn=line.get('unit_id')
            loc=self.idx['wip_locations'].get(location);qty=line.get('qty')
            if side not in ['出','入'] or not positive(qty):issues.append('份额方向或件数无效');continue
            target=(lot,location,root,sn)
            if (side,target) in seen:issues.append('同方向、周转批次、位置、原批次和SN份额重复')
            seen.add((side,target));issues+=self.lot_errors(lot,root,at)
            if not loc or loc.get('kind') not in ACTIVE|TERMINAL:issues.append('流转位置或类别无效');continue
            if root not in self.roots:issues.append('原批次未知或晚于截止');continue
            if side=='出':
                outs.append(line);root_out[root]+=qty;take[lot,location,root]+=qty
                if sn or loc['kind'] not in ACTIVE:issues.append('出向份额必须来自实际在制位置且不附SN')
            else:
                ins.append(line);root_in[root]+=qty;give[lot,location,root]+=qty
                if loc['kind']=='装配耗用':
                    u=self.idx['units'].get(sn);r=self.roots[root];field='stator_batch' if r['kind']=='定子' else 'rotor_batch'
                    wo=self.idx['work_orders'].get(r.get('work_order_id'),{})
                    if not u or qty!=1 or u.get(field)!=root or u.get('product_id')!=wo.get('product_id') or not clock(u.get('assembly_at')) or u['assembly_at']!=e['occurred']:issues.append('耗用份额的SN、件数、原批次、配置或装配时间不一致')
                    identity=(sn,r['kind'])
                    if identity in new_sn or identity in self.sn_used:issues.append('同SN同半成品分支重复耗用')
                    new_sn.add(identity)
                elif sn:issues.append('非装配耗用份额不应附SN')
        if set(x['lot_id'] for x in outs)!=set(e['inputs']) or set(x['lot_id'] for x in ins)!=set(e['outputs']):issues.append('完整输入/输出批次清单与份额明细不符')
        if not root_out or root_out!=root_in:issues.append('原批次份额出入未逐项对平')
        # Consume each declared input container in full. A retained part must
        # be explicitly returned to its active location in the same event.
        existing={k:q for k,q in self.inv.items() if k[0] in e['inputs'] and q>0 and self.idx['wip_locations'][k[1]]['kind'] in ACTIVE}
        if dict(take)!=existing:issues.append('输入周转批次未完整耗用当前在制份额')
        for k,q in take.items():
            if q>self.inv.get(k,0):issues.append('出向份额超过当前已核定余额')
        kind=h['kind'];source_ids=set(e['inputs']);dest_ids=set(e['outputs'])
        active_in=[x for x in ins if self.idx['wip_locations'][x['location_id']]['kind'] in ACTIVE]
        terminal=[x for x in ins if self.idx['wip_locations'][x['location_id']]['kind'] in TERMINAL]
        if kind=='拆批':
            if len(source_ids)!=1 or len(dest_ids)<2 or source_ids&dest_ids or terminal:issues.append('拆批须一进多出，输出为新的在制周转批次')
        elif kind=='合批':
            if len(source_ids)<2 or len(dest_ids)!=1 or source_ids&dest_ids or terminal:issues.append('合批须多进一出，输出为新的在制周转批次')
        else:
            if len(source_ids)!=1 or source_ids!=dest_ids:issues.append('移交、返工、隔离或耗用必须保留同一周转批次标识')
            if kind in ['装配耗用','报废登记']:
                if not terminal or any(self.idx['wip_locations'][x['location_id']]['kind']!=kind for x in terminal):issues.append('耗用或报废端点与流转类别不一致')
                if any(x['location_id'] not in {y['location_id'] for y in outs} for x in active_in):issues.append('未耗用份额须明确返回原在制位置')
            elif terminal:issues.append('移交、返工及隔离不能进入耗用/报废端点')
            elif {x['location_id'] for x in outs}=={x['location_id'] for x in active_in}:issues.append('位置移交的来源与目的相同')
        if kind in ['拆批','合批'] and any(lot in self.born for lot in dest_ids):issues.append('拆合批输出标识已经使用，不重建旧周转批次')
        for lot in dest_ids:
            locations={x['location_id'] for x in active_in if x['lot_id']==lot}
            if len(locations)>1:issues.append('同周转批次流转后处于多个实物位置')
        for prefix,expected in [('返工转入','返工区'),('隔离转入','隔离区')]:
            if kind==prefix and any(self.idx['wip_locations'][x['location_id']]['kind']!=expected for x in active_in):issues.append(prefix+'目的位置类别不符')
        for prefix,expected in [('返工返回','返工区'),('隔离解除','隔离区')]:
            if kind==prefix and (any(self.idx['wip_locations'][x['location_id']]['kind']!=expected for x in outs) or any(self.idx['wip_locations'][x['location_id']]['kind']!='生产缓冲' for x in active_in)):issues.append(prefix+'来源或目的类别不符')
        op_id=h.get('operation_id')
        if op_id:
            op=self.idx['operations'].get(op_id)
            if not op or op.get('object_type')!='生产批次' or op.get('object_id') not in e['roots'] or not clock(op.get('finished')) or op['finished']>e['occurred'] or op.get('status')!='完成':issues.append('引用报工不属于原批次或晚于交接')
            elif kind=='工序交接' and any(self.idx['wip_locations'][x['location_id']].get('process')!=op.get('process') for x in active_in):issues.append('交接位置工序与引用报工不一致')
        if issues:self.pause(e);return
        for k,q in take.items():self.inv[k]-=q
        for k,q in give.items():self.inv[k]=self.inv.get(k,0)+q
        self.sn_used|=new_sn;self.terminal+=[dict(x,event_series=e['series'],occurred=e['occurred']) for x in terminal]
        self.born|=dest_ids
        for lot in dest_ids:self.last[lot]=e['occurred']
        for x in active_in:
            pos=(x['lot_id'],x['location_id'])
            retained=kind in ['装配耗用','报废登记'] and any(y['lot_id']==x['lot_id'] and y['location_id']==x['location_id'] for y in outs)
            if not retained or pos not in self.entered:self.entered[pos]=e['occurred']
        if kind in ['拆批','合批']:
            for lot in dest_ids:self.parents[lot].append(dict(series=e['series'],parents=e['inputs'],occurred=e['occurred'],kind=kind))
        e['applied']=True

    def pause(self,e):
        for root in e['roots']:self.tainted[root]+=unique(e['issues'])

    def result(self,r):
        key=r['id'];w=self.idx['work_orders'].get(r.get('work_order_id'),{});p=self.idx['products'].get(w.get('product_id'),{});issues=unique(self.tainted.get(key,[]))
        positions=[];consumed=0;scrap=0
        for (lot,loc,root),qty in self.inv.items():
            if root!=key or qty<=0:continue
            location=self.idx['wip_locations'][loc]
            if location['kind']=='装配耗用':consumed+=qty
            elif location['kind']=='报废登记':scrap+=qty
            elif not issues:
                whole=sum(q for (l,z,root2),q in self.inv.items() if l==lot and z==loc and q>0)
                positions.append(dict(lot_id=lot,location_id=loc,location=location['name'],workshop=location['workshop'],process=location.get('process'),kind=location['kind'],qty=qty,
                  whole_lot_qty=whole,last_movement=self.last.get(lot),entered_at=self.entered[lot,loc],dwell_hours=(self.end-clock(self.entered[lot,loc])).total_seconds()/3600,root_count=len({a for (l,z,a),q in self.inv.items() if l==lot and z==loc and q>0})))
        baseline=sum(o['qty'] for o in self.origins[key] if positive(o.get('qty'))) if key in self.begin else None
        active=sum(x['qty'] for x in positions) if not issues else None
        if baseline is not None and not issues and baseline!=active+consumed+scrap:issues.append('原批次基准与在制、耗用、报废未守恒');active=None;positions=[]
        state='missing' if key not in self.begin else 'attention' if issues else 'active' if active else 'consumed' if consumed==baseline else 'closed'
        return dict(id=key,work_order_id=r.get('work_order_id'),product_id=w.get('product_id'),family=p.get('family','未匹配'),model=p.get('model','未匹配'),kind=r['kind'],created=r.get('created'),baseline_qty=baseline,
          wip_qty=active,prefix_consumed_qty=consumed,prefix_scrap_qty=scrap,unknown_remainder=None if baseline is None else baseline-consumed-scrap if issues else 0,
          state=state,positions=positions,issues=issues,expected_consumption_sn=sorted(self.expected[key]),missing_consumption_sn=sorted(sn for sn in self.expected[key] if (sn,r['kind']) not in self.sn_used),events=sum(key in e['roots'] and not e['future'] for e in self.events),applied_events=sum(key in e['roots'] and e['applied'] for e in self.events))

    def cohort(self,f):
        rows=[]
        for r in self.rows:
            if any(f.get(k) and f[k]!=r.get(target) for k,target in [('family','family'),('product_id','product_id'),('work_order_id','work_order_id'),('kind','kind')]):continue
            if f.get('from') and r.get('created','')[:10]<f['from']:continue
            if f.get('to') and r.get('created','')[:10]>f['to']:continue
            if f.get('q') and f['q'].lower() not in (' '.join(str(r.get(k) or '') for k in ['id','work_order_id','product_id','model'])+' '+' '.join(l for l,roots in self.members.items() if r['id'] in roots)).lower():continue
            rows.append(r)
        return rows

    def evidence(self,key):
        r=self.roots[key];w=self.idx['work_orders'].get(r.get('work_order_id'),{});p=self.idx['products'].get(w.get('product_id'),{})
        rows=refs('batches',[r])+refs('work_orders',[w] if w else [])+refs('products',[p] if p else [])
        openings=self.openings[key];rows+=refs('wip_openings',openings)
        events=[e for e in self.events if key in e['roots'] or key in e['history_roots']]
        headers=[h for e in events for h in e['history']];lines=[line for h in headers for line in self.lines[h['id']]]
        rows+=refs('wip_event_versions',headers)+refs('wip_event_lines',lines)
        lots={x['lot_id'] for x in openings+lines};locations={x['location_id'] for x in openings+lines};people={x['owner_id'] for x in openings}|{x[k] for x in headers for k in ['sender_id','receiver_id']};ops={x['operation_id'] for x in headers if x.get('operation_id')}
        for ds,keys in [('wip_lots',lots),('wip_locations',locations),('employees',people),('operations',ops),('units',{x['unit_id'] for x in lines if x.get('unit_id')})]:rows+=refs(ds,[self.idx[ds][k] for k in keys if k in self.idx[ds]])
        rows+=refs('units',[self.idx['units'][k] for k in self.expected[key] if k in self.idx['units']])
        allocations=[a for a in self.data.get('allocations',[]) if a.get('work_order_id')==r['work_order_id'] and a.get('effective','')<=self.cutoff[:10]];rows+=refs('allocations',allocations)
        order_lines=[self.idx['order_lines'][a['order_line_id']] for a in allocations if a.get('order_line_id') in self.idx['order_lines']];rows+=refs('order_lines',order_lines)
        orders=[self.idx['orders'][x['order_id']] for x in order_lines if x.get('order_id') in self.idx['orders']];rows+=refs('orders',orders)
        return unique_sources(rows)

def summary(rows):
    counts=Counter(r['state'] for r in rows);groups=[]
    for kind in ['定子','转子']:
        selected=[r for r in rows if r['kind']==kind];valid=[r for r in selected if r['wip_qty'] is not None]
        groups.append(dict(kind=kind,objects=len(selected),verified=len(valid),baseline_qty=sum(r['baseline_qty'] for r in valid),wip_qty=sum(r['wip_qty'] for r in valid),consumed_qty=sum(r['prefix_consumed_qty'] for r in valid),scrap_qty=sum(r['prefix_scrap_qty'] for r in valid),unknown_objects=len(selected)-len(valid),
            known_baseline_qty=sum(r['baseline_qty'] for r in selected if r['baseline_qty'] is not None),prefix_consumed_all=sum(r['prefix_consumed_qty'] for r in selected),prefix_scrap_all=sum(r['prefix_scrap_qty'] for r in selected),
            unknown_remainder_qty=sum(r['unknown_remainder'] for r in selected if r['unknown_remainder'] is not None),missing_baseline_objects=sum(r['baseline_qty'] is None for r in selected)))
    return dict(objects=len(rows),states=dict(counts),active=counts['active'],attention=counts['attention']+counts['missing'],positions=len({(p['lot_id'],p['location_id']) for r in rows for p in r['positions']}),groups=groups)
