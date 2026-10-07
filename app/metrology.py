"""Calibration-register evidence over explicit instrument uses.

These are synthetic workflow checks, not measurement suitability, product
judgments, approved releases, or a replacement for the original quality result.
"""
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime

TABLES=('metrology_instruments','metrology_rules','metrology_calibrations',
        'metrology_uses','metrology_notices','metrology_reviews')
BASE=('measurements','test_sessions','test_specs','incoming_readings','incoming_checks',
      'incoming_check_plans','incoming_inspections','incoming_specs','receipts',
      'process_readings','process_checks','process_check_plans','process_specs','operations',
      'units','batches','work_orders','products','allocations','order_lines','orders',
      'genealogy','shipment_units','shipments','equipment','tools','inventory_opening','inventory_movements')
STAGES={'test':'终检','incoming':'来料','process':'工序'}
SOURCE={'test':('measurements','measurement_id'),
        'incoming':('incoming_readings','incoming_reading_id'),
        'process':('process_readings','process_reading_id')}
CAL_STATES={
    'valid':'测量时校准登记适用','missing':'未见校准登记','expired':'测量时已到登记失效起点',
    'pending':'校准后登记尚未生效','failed':'最近校准不符合登记范围','withdrawn':'最近校准登记已撤销',
    'conflict':'同刻校准记录冲突','invalid':'校准登记待核对','unknown_use':'仪器使用关系待核对',
    'unknown_rule':'适用要求待核对','not_required':'模拟要求不需校准登记','voided':'源测量已作废',
}
IMPACT_STATES={'matched':'命中已登记影响区间','potential':'命中起点未知的潜在范围',
               'unknown':'影响尚无法核定','none':'未命中现行登记范围','voided':'源测量已作废'}
REVIEW_STATES={'none':'未登记核查','in_progress':'核查登记处理中','checked':'资料核对已登记',
               'retest':'登记建议复测','stale':'旧版本依据需重新核查','invalid':'核查登记待核对',
               'not_matched':'无现行范围命中'}
NOTE='合成Excel台账。按已登记测量项目核查校准登记和影响范围，不是应检覆盖或整机产量。登记适用不证明真实证书、测量能力或产品合格；原检测、隔离、放行和发货事实保持原值。'
TIME_NOTE='源测量截至业务截止；新增完整版本截至登记截止。原测量、规范、对象及谱系仍用当前已导入记录，登记时间不是平台导入时间，不构成全厂历史数据库。有效和影响区间均左闭右开。'
ORDER_NOTE='工单分配只表示候选订单；已装箱SN与截止前发货行另列明确发运对应。不虚分共享工单，不把核查名单解释为缺陷、召回指令或已批准处置。'


def clock(v):
    try:
        d=datetime.fromisoformat(v)
        return d if isinstance(v,str) and len(v)==19 and d.tzinfo is None and d.isoformat(timespec='seconds')==v else None
    except (ValueError,TypeError):return None


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def refs(ds,rows):
    return [dict(dataset=ds,key=r['id']) for r in rows if r and r.get('id')]


def unique_sources(values):
    return [dict(dataset=d,key=k) for d,k in sorted({(x['dataset'],x['key']) for x in values})]


def resolve_versions(rows,known,identity):
    """Choose a complete known version; malformed/latest withdrawn never falls back."""
    grouped=defaultdict(list)
    for r in rows:grouped[r.get('series')].append(r)
    out=[]
    for series,history in sorted(grouped.items(),key=lambda x:str(x[0])):
        known_rows=[r for r in history if clock(r.get('registered')) and r['registered']<=known]
        candidates=[r for r in known_rows if r.get('status')!='草稿']
        bad_clock=[r for r in history if not clock(r.get('registered'))]
        issues=[];chosen=None
        if bad_clock:issues.append('登记时间无效，不能确定版本可知性')
        if candidates:
            if any(type(r.get('version')) is not int or r['version']<1 for r in candidates):issues.append('版本必须为正整数')
            else:
                latest=max(r['version'] for r in candidates)
                latest_rows=[r for r in candidates if r['version']==latest]
                if len(latest_rows)!=1:issues.append('最新版本重复')
                else:
                    chosen=latest_rows[0];by_id={r.get('id'):r for r in known_rows};chain=[];cur=chosen;seen=set()
                    while cur:
                        if cur.get('id') in seen:issues.append('前版链循环');break
                        seen.add(cur.get('id'));chain.append(cur)
                        if cur.get('status') not in ['已登记','撤销']:issues.append('登记状态无效')
                        if tuple(cur.get(k) for k in identity)!=tuple(chosen.get(k) for k in identity):issues.append('完整版本的对象身份改变')
                        if cur.get('version')==1:
                            if cur.get('previous_id'):issues.append('首版不应引用前版')
                            break
                        prev=by_id.get(cur.get('previous_id'))
                        if not prev or prev.get('series')!=series or type(prev.get('version')) is not int or prev['version']!=cur['version']-1:
                            issues.append('版本前序缺失或不连续');break
                        if prev.get('status')=='草稿' or prev['registered']>cur['registered']:issues.append('前序状态或登记顺序无效');break
                        cur=prev
                    if len({r['version'] for r in candidates})!=len(candidates):issues.append('已知登记版本重复')
        if not candidates and not issues:continue
        out.append(dict(series=series,selected=chosen,issues=list(dict.fromkeys(issues)),
                        history=sorted(history,key=lambda r:(r.get('registered') or '',str(r.get('version')),r.get('id','')))))
    return out


class Metrology:
    def __init__(self,data=None,cutoff=None,known_cutoff=None):
        from .analytics import AS_OF
        self.cutoff=cutoff or AS_OF;self.known_cutoff=known_cutoff or self.cutoff
        if not clock(self.cutoff) or not clock(self.known_cutoff) or self.known_cutoff<self.cutoff:raise ValueError('截止时点无效')
        if data is None:
            from .models import Record
            data={k:[] for k in TABLES+BASE}
            for k,v in Record.objects.filter(dataset__in=TABLES+BASE).values_list('dataset','values'):data[k].append(v)
        self.data=data;self.idx={k:{r['id']:r for r in data.get(k,[])} for k in TABLES+BASE}
        self.global_issues=[]
        self.rules=resolve_versions(data.get('metrology_rules',[]),self.known_cutoff,('stage','parameter','unit'))
        self.calibrations=resolve_versions(data.get('metrology_calibrations',[]),self.known_cutoff,('instrument_id',))
        self.uses=resolve_versions(data.get('metrology_uses',[]),self.known_cutoff,
                                   ('stage','measurement_id','incoming_reading_id','process_reading_id'))
        self.use_history_by_series={g['series']:g['history'] for g in self.uses}
        self.notices=resolve_versions(data.get('metrology_notices',[]),self.known_cutoff,('instrument_id',))
        self.reviews=resolve_versions(data.get('metrology_reviews',[]),self.known_cutoff,('use_id','notice_id'))
        self.rule_groups=defaultdict(list);self.cal_groups=defaultdict(list);self.use_groups=defaultdict(list);self.notice_groups=defaultdict(list);self.review_groups=defaultdict(list)
        for g in self.rules:
            identities={(r.get('stage'),r.get('parameter'),r.get('unit'))for r in g['history']}
            for identity in identities:self.rule_groups[identity].append(g)
        for groups,target,key in [(self.calibrations,self.cal_groups,'instrument_id'),(self.notices,self.notice_groups,'instrument_id')]:
            for g in groups:
                for identity in {r.get(key) for r in g['history']}:target[identity].append(g)
        for g in self.uses:
            for h in g['history']:
                for stage,(dataset,field) in SOURCE.items():
                    if h.get(field) and g not in self.use_groups[(stage,h[field])]:self.use_groups[(stage,h[field])].append(g)
        for g in self.reviews:
            for uid in {r.get('use_id') for r in g['history']}:self.review_groups[uid].append(g)
        self.sn_by_batch=defaultdict(list);self.ship_by_sn=defaultdict(list);self.alloc_by_wo=defaultdict(list);self.gene_by_lot=defaultdict(list)
        for u in data.get('units',[]):
            if clock(u.get('assembly_at')) and u['assembly_at']<=self.cutoff:
                for k in ['stator_batch','rotor_batch','assembly_batch']:
                    if u.get(k):self.sn_by_batch[u[k]].append(u['id'])
        for s in data.get('shipment_units',[]):
            shipment=self.idx['shipments'].get(s.get('shipment_id'))
            if shipment and clock(shipment.get('shipped')) and shipment['shipped']<=self.cutoff:self.ship_by_sn[s.get('unit_id')].append((s,shipment))
        for a in data.get('allocations',[]):
            if isinstance(a.get('effective'),str) and a['effective']<=self.cutoff[:10]:self.alloc_by_wo[a.get('work_order_id')].append(a)
        for g in data.get('genealogy',[]):
            if g.get('parent_type')=='材料批次' and clock(g.get('occurred')) and g['occurred']<=self.cutoff:self.gene_by_lot[g.get('parent_id')].append(g)
        self.materials_by_lot=defaultdict(set)
        for ds in ['receipts','inventory_opening','inventory_movements']:
            for r in data.get(ds,[]):self.materials_by_lot[r.get('lot')].add(r.get('material_id'))
        self.rows=[]
        for stage,(ds,field) in SOURCE.items():
            for raw in sorted(data.get(ds,[]),key=lambda x:x['id']):
                r=self.measurement(stage,raw)
                if r:self.rows.append(r)
        self.index={r['id']:r for r in self.rows}

    def rule(self,stage,parameter,unit,at):
        groups=self.rule_groups[(stage,parameter,unit)];sources=[];issues=[];applicable=[]
        for g in groups:
            sources+=refs('metrology_rules',g['history']);r=g['selected']
            if g['issues']:issues+=g['issues'];continue
            if not r or r['status']=='撤销':continue
            if not clock(r.get('effective')) or r.get('expires') and (not clock(r['expires']) or r['expires']<=r['effective']):issues.append('要求有效区间无效');continue
            if type(r.get('required')) is not bool:issues.append('要求校准字段须为布尔值');continue
            if r['effective']<=at and (not r.get('expires') or at<r['expires']):applicable.append(r)
        if len(applicable)!=1:issues.append('缺少唯一适用要求')
        chosen=applicable[0] if len(applicable)==1 and not issues else None
        return dict(required=chosen['required'] if chosen else None,selected=chosen,sources=sources,issues=list(dict.fromkeys(issues)))

    def calibration(self,instrument,at,required):
        out=dict(state='unknown_rule' if required is None else 'not_required' if not required else 'missing',selected=None,issues=[],sources=[])
        if required is not True:return out
        if not instrument:out['state']='unknown_use';return out
        if not clock(instrument.get('active_from')) or instrument['active_from']>at or instrument.get('retired') and (not clock(instrument['retired']) or instrument['retired']<=instrument['active_from'] or at>=instrument['retired']):
            out.update(state='unknown_use',issues=['测量时间不在仪器通道启用区间']);return out
        applicable=[]
        for g in self.cal_groups[instrument['id']]:
            out['sources']+=refs('metrology_calibrations',g['history']);r=g['selected']
            times=[h.get('performed') for h in g['history'] if clock(h.get('registered')) and h['registered']<=self.known_cutoff and h.get('status')!='草稿']
            # A wholly future calibration never invalidates an earlier measurement.
            if times and all(clock(t) and t>at for t in times):continue
            if g['issues'] or not r or not clock(r.get('performed')):out['issues']+=g['issues'] or ['校准实施时间待核对'];continue
            if r['performed']<=at:applicable.append(r)
        if out['issues']:out['state']='invalid';return out
        if not applicable:return out
        latest=max(r['performed'] for r in applicable);rr=[r for r in applicable if r['performed']==latest]
        if len(rr)!=1:out.update(state='conflict',issues=['同刻存在多个校准系列']);return out
        r=rr[0];out['selected']=r
        if r['status']=='撤销':out['state']='withdrawn';return out
        a,b=r.get('valid_from'),r.get('valid_until')
        if not clock(a) or not clock(b) or not r['performed']<=a<b or r['performed']>r['registered']:
            out.update(state='invalid',issues=['校准实施、有效区间或登记顺序无效']);return out
        if (r.get('parameter'),r.get('unit'))!=(instrument.get('parameter'),instrument.get('unit')) or not r.get('certificate_no') or not r.get('reference'):
            out.update(state='invalid',issues=['校准登记范围或依据缺失/不一致']);return out
        if r.get('result') not in ['符合登记范围','不符合登记范围']:out.update(state='invalid',issues=['登记范围结论无效']);return out
        out['state']='failed' if r['result']=='不符合登记范围' else 'pending' if at<a else 'expired' if at>=b else 'valid'
        return out

    def usage(self,stage,key,measured,parameter,unit):
        groups=self.use_groups[(stage,key)];out=dict(selected=None,instrument=None,issues=[],sources=[],versions=groups)
        if not groups:out['issues']=['未见已知的显式使用登记'];return out
        candidates=[]
        for g in groups:
            out['sources']+=refs('metrology_uses',g['history']);r=g['selected']
            if g['issues']:out['issues']+=g['issues']
            if r:candidates.append(r)
        if len(candidates)!=1 or out['issues']:out['issues'].append('无法选择唯一完整使用版本');return out
        r=candidates[0];out['selected']=r
        if r['status']=='撤销':out['issues'].append('当前使用对应已撤销');return out
        populated=[s for s,(ds,field) in SOURCE.items() if r.get(field)]
        if populated!=[stage] or r.get('stage')!=stage or r.get(SOURCE[stage][1])!=key:out['issues'].append('使用版本须唯一对应同环节原测量')
        if not clock(r.get('measured')) or r['measured']!=measured or r['registered']<r['measured']:out['issues'].append('使用时间与原测量或登记顺序不一致')
        instrument=self.idx['metrology_instruments'].get(r.get('instrument_id'))
        if not instrument:out['issues'].append('使用登记缺仪器通道身份')
        elif (instrument.get('stage'),instrument.get('parameter'),instrument.get('unit'))!=(stage,parameter,unit):out['issues'].append('仪器通道的环节、特性或单位不匹配')
        if not out['issues']:out['instrument']=instrument;out['sources']+=refs('metrology_instruments',[instrument])
        return out

    def impact(self,instrument,at):
        out=dict(state='unknown' if not instrument else 'none',matched=[],issues=[],sources=[])
        if not instrument:return out
        for g in self.notice_groups[instrument['id']]:
            out['sources']+=refs('metrology_notices',g['history']);r=g['selected']
            if g['issues']:out['issues']+=g['issues'];continue
            if not r or r['status']=='撤销':continue
            if not clock(r.get('discovered')) or r['discovered']>r['registered']:out['issues'].append('影响发现及登记顺序无效');continue
            a,b=r.get('impact_from'),r.get('impact_until');mode=r.get('lower_mode')
            if not clock(b) or mode not in ['明确起点','起点未知'] or mode=='明确起点' and (not clock(a) or a>=b) or mode=='起点未知' and a is not None:
                out['issues'].append('影响区间或起点声明无效');continue
            cal=self.idx['metrology_calibrations'].get(r.get('calibration_id')) if r.get('calibration_id') else None
            if r.get('calibration_id') and (not cal or cal.get('instrument_id')!=instrument['id']):out['issues'].append('影响引用校准与仪器不一致');continue
            if at<b and (mode=='起点未知' or a<=at):out['matched'].append(r)
        out['issues']=list(dict.fromkeys(out['issues']))
        out['state']='unknown' if out['issues'] else 'potential' if any(r['lower_mode']=='起点未知' for r in out['matched']) else 'matched' if out['matched'] else 'none'
        return out

    def review(self,use,calibration,impact,source_digest):
        out=dict(state='not_matched' if not impact['matched'] else 'none',rows=[],issues=[],sources=[])
        if not use:return out
        results=[]
        current_notices={r['id'] for r in impact['matched']}
        historical_ids={h['id'] for h in self.use_history_by_series.get(use['series'],[])}
        groups={g['series']:g for uid in historical_ids for g in self.review_groups[uid]}
        for g in groups.values():
            out['sources']+=refs('metrology_reviews',g['history']);r=g['selected']
            if g['issues']:out['issues']+=g['issues'];continue
            if not r or r['status']=='撤销':continue
            out['rows'].append(r)
            expected_cal=calibration['selected']['id'] if calibration['selected'] else None
            if r['use_id']!=use['id'] or r['notice_id'] not in current_notices or r.get('calibration_id')!=expected_cal or r.get('source_digest')!=source_digest:
                results.append('stale');continue
            notice=self.idx['metrology_notices'].get(r['notice_id'])
            basis_times=[use['registered'],use['measured'],notice['registered']]
            if calibration['selected']:basis_times.append(calibration['selected']['registered'])
            if r['registered']<max(basis_times):out['issues'].append('核查登记早于其引用依据');continue
            result={'处理中':'in_progress','资料已核对':'checked','建议复测':'retest'}.get(r.get('result'))
            if result:results.append(result)
            else:out['issues'].append('核查登记结果无效')
        # A review covers only its explicitly referenced notice/use/version.
        covered={r['notice_id'] for r in out['rows'] if r['notice_id'] in current_notices}
        if out['issues']:out['state']='invalid'
        elif 'stale' in results:out['state']='stale'
        elif current_notices-covered:out['state']='none'
        elif results:out['state']=next((s for s in ['retest','in_progress','checked'] if s in results),'none')
        return out

    def measurement(self,stage,raw):
        ds,field=SOURCE[stage];issues=[];sources=refs(ds,[raw]);parent=spec=plan=operation=None;at=None;batch_ids=[];sn_ids=[];wo_ids=[];receipt=None
        if stage=='test':
            parent=self.idx['test_sessions'].get(raw.get('session_id'));spec=self.idx['test_specs'].get(raw.get('spec_id'))
            sources+=refs('test_sessions',[parent])+refs('test_specs',[spec]);at=parent.get('tested') if parent else None
            u=self.idx['units'].get(parent.get('unit_id')) if parent else None
            if u:sn_ids=[u['id']];wo_ids=[u['work_order_id']]
            else:issues.append('源检测缺SN身份')
            parameter=spec.get('test_code') if spec else None
        elif stage=='incoming':
            parent=self.idx['incoming_checks'].get(raw.get('check_id'));spec=self.idx['incoming_specs'].get(raw.get('spec_id'))
            plan=self.idx['incoming_check_plans'].get(parent.get('plan_id')) if parent else None
            inspection=self.idx['incoming_inspections'].get(plan.get('inspection_id')) if plan else None
            receipt=self.idx['receipts'].get(inspection.get('receipt_id')) if inspection else None
            sources+=refs('incoming_checks',[parent])+refs('incoming_specs',[spec])+refs('incoming_check_plans',[plan])+refs('incoming_inspections',[inspection])+refs('receipts',[receipt])
            at=parent.get('checked') if parent else None;parameter=spec.get('parameter') if spec else None
            if not receipt:issues.append('源来料测量缺到货关系')
            elif len(self.materials_by_lot[receipt.get('lot')])!=1:issues.append('材料批次号对应多个或未知物料，影响关系待核')
            else:
                for g in self.gene_by_lot[receipt['lot']]:
                    if g.get('child_type')=='生产批次' and g.get('child_id') in self.idx['batches']:
                        batch_ids.append(g['child_id']);sources+=refs('genealogy',[g])
        else:
            parent=self.idx['process_checks'].get(raw.get('check_id'));spec=self.idx['process_specs'].get(raw.get('spec_id'))
            plan=self.idx['process_check_plans'].get(parent.get('plan_id')) if parent else None
            operation=self.idx['operations'].get(plan.get('operation_id')) if plan else None
            sources+=refs('process_checks',[parent])+refs('process_specs',[spec])+refs('process_check_plans',[plan])+refs('operations',[operation])
            at=parent.get('checked') if parent else None;parameter=spec.get('parameter') if spec else None
            if not operation:issues.append('源工序测量缺报工关系')
            else:
                wo_ids=[operation.get('work_order_id')];oid=operation.get('object_id')
                if oid in self.idx['batches']:batch_ids=[oid]
                elif oid in self.idx['units']:sn_ids=[oid]
                else:issues.append('原报工对象尚不能对应批次或SN')
        if not clock(at):
            self.global_issues.append(dict(stage=stage,key=raw['id'],message='源测量时间缺失或无效，未纳入时点清单'));return None
        if at>self.cutoff:return None
        if not spec:issues.append('源测量缺特性规范')
        unit=spec.get('unit') if spec else raw.get('unit')
        if spec and 'unit' in raw and raw.get('unit')!=unit:issues.append('源实测单位与规范不一致')
        source_digest=digest([raw,parent,spec,plan,operation])
        batch_ids=sorted(set(batch_ids));sources+=refs('batches',[self.idx['batches'][b] for b in batch_ids])
        for b in batch_ids:
            wo_ids.append(self.idx['batches'][b]['work_order_id']);sn_ids+=self.sn_by_batch[b]
        sn_ids=sorted(set(sn_ids));wo_ids=sorted(set(w for w in wo_ids if w));sources+=refs('units',[self.idx['units'].get(s) for s in sn_ids])+refs('work_orders',[self.idx['work_orders'].get(w) for w in wo_ids])
        use=self.usage(stage,raw['id'],at,parameter,unit);rule=self.rule(stage,parameter,unit,at)
        cal=self.calibration(use['instrument'],at,rule['required']);impact=self.impact(use['instrument'],at)
        if use['issues'] and rule['required'] is True:cal['state']='unknown_use'
        if issues:cal['state']='invalid';impact['state']='unknown'
        voided=bool(parent and parent.get('voided'))
        if voided:cal['state']=impact['state']='voided'
        review=self.review(use['selected'],cal,impact,source_digest)
        sources+=use['sources']+rule['sources']+cal['sources']+impact['sources']+review['sources']
        r=dict(id=stage+':'+raw['id'],stage=stage,source_dataset=ds,source_key=raw['id'],measured=at,
               parameter=parameter,unit=unit,value=raw.get('value'),raw_reference=raw.get('file_reference') or raw.get('instrument'),
               unit_basis='原实测单位' if 'unit' in raw else '规范登记单位，源工序表未另列单位',
               source_result=raw.get('result'),source_context_result=parent.get('result') if parent else None,
               required=rule['required'],instrument_id=use['instrument']['id'] if use['instrument'] else None,
               use_id=use['selected']['id'] if use['selected'] else None,
               calibration_id=cal['selected']['id'] if cal['selected'] else None,
               calibration_state=cal['state'],impact_state=impact['state'],review_state=review['state'],
               notice_ids=[n['id'] for n in impact['matched']],voided=voided,source_digest=source_digest,
               sn_ids=sn_ids,batch_ids=batch_ids,work_order_ids=wo_ids,receipt_id=receipt['id'] if receipt else None,
               issues=list(dict.fromkeys(issues+use['issues']+rule['issues']+cal['issues']+impact['issues']+review['issues'])),
               sources=unique_sources(sources))
        return r

    def cohort(self,f):
        rows=[]
        for r in self.rows:
            if f.get('stage') and r['stage']!=f['stage']:continue
            if f.get('instrument_id') and r['instrument_id']!=f['instrument_id']:continue
            if f.get('parameter') and r['parameter']!=f['parameter']:continue
            if f.get('from') and r['measured'][:10]<f['from'] or f.get('to') and r['measured'][:10]>f['to']:continue
            if f.get('q') and f['q'].lower() not in json.dumps({k:r[k] for k in ['id','instrument_id','parameter','sn_ids','batch_ids','work_order_ids','receipt_id']},ensure_ascii=False).lower():continue
            rows.append(r)
        return rows

    def downstream(self,rows):
        sns=sorted({s for r in rows for s in r['sn_ids']});batches=sorted({b for r in rows for b in r['batch_ids']});wos=sorted({w for r in rows for w in r['work_order_ids']})
        candidate=[];confirmed=[];sources=[]
        for w in wos:
            for a in self.alloc_by_wo[w]:
                line=self.idx['order_lines'].get(a.get('order_line_id'));work=self.idx['work_orders'].get(w)
                if line and work and line.get('product_id')==work.get('product_id'):
                    candidate.append(dict(work_order_id=w,allocation_id=a['id'],order_line_id=line['id'],order_id=line.get('order_id')))
                    sources+=refs('allocations',[a])+refs('order_lines',[line])
        for sn in sns:
            for unit,shipment in self.ship_by_sn[sn]:
                confirmed.append(dict(unit_id=sn,shipment_id=shipment['id'],order_line_id=shipment.get('order_line_id')))
                sources+=refs('shipment_units',[unit])+refs('shipments',[shipment])
        return dict(sn_ids=sns,batch_ids=batches,work_order_ids=wos,candidate_orders=candidate,
                    shipment_orders=confirmed,sources=unique_sources(sources),boundary=ORDER_NOTE)


def summary(rows):
    active=[r for r in rows if not r['voided']]
    required=[r for r in active if r['required'] is True]
    return dict(readings=len(rows),active_readings=len(active),voided=len(rows)-len(active),
                required=len(required),not_required=sum(r['required'] is False for r in active),
                unknown_requirement=sum(r['required'] is None for r in active),
                calibration_counts=dict(Counter(r['calibration_state'] for r in required)),
                valid_register=sum(r['calibration_state']=='valid' for r in required),
                matched=sum(r['impact_state']=='matched' for r in active),
                potential=sum(r['impact_state']=='potential' for r in active),
                unknown_impact=sum(r['impact_state']=='unknown' for r in active),
                review_counts=dict(Counter(r['review_state'] for r in active if r['notice_ids'])),
                stages=[dict(stage=s,readings=sum(r['stage']==s for r in rows),active=sum(r['stage']==s for r in active),
                             required=sum(r['stage']==s for r in required),valid=sum(r['stage']==s and r['calibration_state']=='valid' for r in required))for s in STAGES])
