"""Independent calculation from raw registers; no imports from app or Django.

This acceptance ledger checks the actual generated source corpus, including
complete known versions, usage identities, measured-time validity and impacts.
It does not try to verify real certificates or unrecorded uses.
"""
from collections import defaultdict
from datetime import datetime

SOURCES={'test':('measurements','measurement_id','test_sessions','session_id','test_specs','test_code'),
         'incoming':('incoming_readings','incoming_reading_id','incoming_checks','check_id','incoming_specs','parameter'),
         'process':('process_readings','process_reading_id','process_checks','check_id','process_specs','parameter')}
def timestamp(v):
    try:
        p=datetime.fromisoformat(v);return isinstance(v,str) and len(v)==19 and p.tzinfo is None and p.isoformat(timespec='seconds')==v
    except (ValueError,TypeError):return False
def registers(rows,known,identity):
    series=defaultdict(list);out=[]
    for r in rows:series[r['series']].append(r)
    for sid,history in series.items():
        choices=[r for r in history if timestamp(r.get('registered')) and r['registered']<=known and r.get('status')!='草稿']
        invalid=any(not timestamp(r.get('registered')) for r in history);chosen=None
        if choices:
            if any(type(r['version']) is not int or r['version']<=0 for r in choices):invalid=True
            else:
                newest=max(r['version'] for r in choices);current=[r for r in choices if r['version']==newest]
                invalid|=len(current)!=1 or len(choices)!=len({r['version'] for r in choices})
                if len(current)==1:
                    chosen=current[0];c=chosen;visited=set();known_ids={r['id']:r for r in history if timestamp(r.get('registered')) and r['registered']<=known}
                    while c:
                        if c['id'] in visited:invalid=True;break
                        visited.add(c['id'])
                        invalid|=c['status'] not in ['已登记','撤销'] or tuple(c.get(k) for k in identity)!=tuple(chosen.get(k) for k in identity)
                        if c['version']==1:invalid|=bool(c.get('previous_id'));break
                        prev=known_ids.get(c.get('previous_id'))
                        if not prev or prev['series']!=sid or prev['version']!=c['version']-1 or prev['registered']>c['registered'] or prev['status']=='草稿':invalid=True;break
                        c=prev
        if choices or invalid:out.append((chosen,invalid,history))
    return out
def rows_at(data,business,known):
    idx={ds:{r['id']:r for r in rows} for ds,rows in data.items()};grouped={}
    configs=[('metrology_rules',['stage','parameter','unit']),('metrology_calibrations',['instrument_id']),('metrology_uses',['stage','measurement_id','incoming_reading_id','process_reading_id']),('metrology_notices',['instrument_id'])]
    for ds,identity in configs:grouped[ds]=registers(data.get(ds,[]),known,identity)
    uses=defaultdict(dict);cals=defaultdict(list);notes=defaultdict(list);rules=defaultdict(list)
    for group in grouped['metrology_uses']:
        for stage,(_,field,*_) in SOURCES.items():
            for h in group[2]:
                if h.get(field):uses[stage,h[field]][h['series']]=group
    for ds,target,fields in [('metrology_calibrations',cals,['instrument_id']),('metrology_notices',notes,['instrument_id']),('metrology_rules',rules,['stage','parameter','unit'])]:
        for g in grouped[ds]:
            for key in {tuple(h.get(k) for k in fields) for h in g[2]}:target[key[0] if len(key)==1 else key].append(g)
    out={};materials=defaultdict(set)
    for ds in ['receipts','inventory_opening','inventory_movements']:
        for r in data.get(ds,[]):materials[r.get('lot')].add(r.get('material_id'))
    for stage,(ds,field,parent_ds,parent_field,spec_ds,param_field) in SOURCES.items():
        for raw in data.get(ds,[]):
            parent=idx.get(parent_ds,{}).get(raw.get(parent_field));spec=idx.get(spec_ds,{}).get(raw.get('spec_id'));at=parent.get('tested' if stage=='test' else 'checked') if parent else None
            if not timestamp(at) or at>business:continue
            param=spec.get(param_field) if spec else None;unit=spec.get('unit') if spec else raw.get('unit');required=None
            source_bad=not spec or ('unit' in raw and raw['unit']!=unit)
            if stage=='test':source_bad|=parent.get('unit_id') not in idx.get('units',{})
            elif stage=='incoming':
                plan=idx.get('incoming_check_plans',{}).get(parent.get('plan_id'),{});inspection=idx.get('incoming_inspections',{}).get(plan.get('inspection_id'),{});receipt=idx.get('receipts',{}).get(inspection.get('receipt_id'))
                source_bad|=not receipt or len(materials[receipt.get('lot')])!=1
            else:
                plan=idx.get('process_check_plans',{}).get(parent.get('plan_id'),{});op=idx.get('operations',{}).get(plan.get('operation_id'))
                source_bad|=not op or (op.get('object_id') not in idx.get('batches',{}) and op.get('object_id') not in idx.get('units',{}))
            rr=[];rule_error=False
            for v,bad,history in rules[stage,param,unit]:
                rule_error|=bad
                if not v or v['status']=='撤销':continue
                rule_error|=not timestamp(v['effective']) or bool(v.get('expires') and (not timestamp(v['expires']) or v['expires']<=v['effective'])) or type(v.get('required')) is not bool
                if v['effective']<=at and (not v.get('expires') or at<v['expires']):rr.append(v)
            if len(rr)==1 and not rule_error:required=rr[0]['required']
            usage_groups=list(uses[stage,raw['id']].values());u=None;instrument=None
            if len(usage_groups)==1 and not usage_groups[0][1]:u=usage_groups[0][0]
            if u and u['status']=='已登记' and u['stage']==stage and u[field]==raw['id'] and sum(bool(u.get(s[1])) for s in SOURCES.values())==1 and timestamp(u['measured']) and u['measured']==at and u['registered']>=u['measured']:
                instrument=idx.get('metrology_instruments',{}).get(u.get('instrument_id'))
                if instrument and (instrument['stage'],instrument['parameter'],instrument['unit'])!=(stage,param,unit):instrument=None
            state='unknown_rule' if required is None else 'not_required' if required is False else 'unknown_use' if not instrument else 'missing';chosen=None
            if required is True and instrument:
                invalid=False;applicable=[]
                for c,bad,history in cals[instrument['id']]:
                    dates=[h.get('performed') for h in history if timestamp(h.get('registered')) and h['registered']<=known and h['status']!='草稿']
                    if dates and all(timestamp(v) and v>at for v in dates):continue
                    if bad or not c or not timestamp(c.get('performed')):invalid=True
                    elif c['performed']<=at:applicable.append(c)
                if invalid:state='invalid'
                elif applicable:
                    last=max(c['performed'] for c in applicable);matches=[c for c in applicable if c['performed']==last]
                    if len(matches)>1:state='conflict'
                    else:
                        chosen=matches[0];c=chosen
                        if c['status']=='撤销':state='withdrawn'
                        elif not timestamp(c.get('valid_from')) or not timestamp(c.get('valid_until')) or not c['performed']<=c['valid_from']<c['valid_until'] or c['performed']>c['registered'] or (c['parameter'],c['unit'])!=(param,unit) or not c.get('certificate_no') or not c.get('reference') or c.get('result') not in ['符合登记范围','不符合登记范围']:state='invalid'
                        elif c['result']=='不符合登记范围':state='failed'
                        elif at<c['valid_from']:state='pending'
                        elif at>=c['valid_until']:state='expired'
                        else:state='valid'
                if not timestamp(instrument.get('active_from')) or instrument['active_from']>at or instrument.get('retired') and (not timestamp(instrument['retired']) or instrument['retired']<=instrument['active_from'] or at>=instrument['retired']):state='unknown_use';chosen=None
            impact='none' if instrument else 'unknown';matched=[];notice_bad=False
            if instrument:
                for v,bad,history in notes[instrument['id']]:
                    if bad:notice_bad=True;continue
                    if not v or v['status']=='撤销':continue
                    a,b=v.get('impact_from'),v.get('impact_until');mode=v.get('lower_mode');cal=idx.get('metrology_calibrations',{}).get(v.get('calibration_id'))
                    if not timestamp(v.get('discovered')) or v['discovered']>v['registered'] or not timestamp(b) or mode not in ['明确起点','起点未知'] or mode=='明确起点' and (not timestamp(a) or a>=b) or mode=='起点未知' and a is not None or v.get('calibration_id') and (not cal or cal['instrument_id']!=instrument['id']):notice_bad=True;continue
                    if at<b and (mode=='起点未知' or a<=at):matched.append(v)
                impact='unknown' if notice_bad else 'potential' if any(v['lower_mode']=='起点未知' for v in matched) else 'matched' if matched else 'none'
            voided=bool(parent.get('voided'))
            if source_bad:state='invalid';impact='unknown'
            if voided:state=impact='voided'
            out[stage+':'+raw['id']]=dict(required=required,calibration_state=state,calibration_id=chosen['id'] if chosen else None,instrument_id=instrument['id'] if instrument else None,impact_state=impact,notice_ids=sorted(v['id'] for v in matched),voided=voided)
    return out
