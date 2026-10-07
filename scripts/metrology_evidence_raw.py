"""Independent acceptance ledger: raw SQL/CSV only, no app or Django imports."""
import csv,hashlib,io,re,uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from metrology_raw_register import registers,timestamp

FIELDS=['certificate_no','instrument_id','parameter','unit','performed','valid_from','valid_until','result','laboratory']
HEADERS=FIELDS+['issued','reference']


def certificates_at(data,known,files,root,user_id):
    docs={r['id']:r for r in data.get('metrology_certificates',[])}
    links=defaultdict(list)
    for group in registers(data.get('metrology_certificate_links',[]),known,['calibration_id']):
        for key in {r['calibration_id'] for r in group[2]}:links[key].append(group)
    result={}
    for cal in data.get('metrology_calibrations',[]):
        if not timestamp(cal.get('registered')) or cal['registered']>known:continue
        groups=links[cal['id']];chosen=None;doc=None
        if len(groups)>1 or any(g[1] for g in groups):state='record_attention'
        elif not groups or not groups[0][0]:state='missing_link'
        else:
            chosen=groups[0][0];doc=docs.get(chosen.get('certificate_id'))
            state='withdrawn' if chosen['status']=='撤销' else 'consistent'
        if state=='consistent':
            problem=not doc
            if doc:
                problem|=any(doc.get(k)!=cal.get(k) for k in FIELDS)
                problem|=not all(timestamp(doc.get(k)) for k in ['performed','valid_from','valid_until','issued'])
                if not problem:
                    problem|=not doc['performed']<=doc['valid_from']<doc['valid_until'] or doc['issued']<doc['performed'] or doc['issued']>chosen['registered'] or doc['issued']>known
                problem|=chosen['registered']<cal['registered'] or not doc.get('reference') or not chosen.get('reference')
                problem|=bool(doc.get('file_id') and not re.fullmatch('[0-9a-f]{64}',doc.get('file_sha256') or ''))
            if problem:state='record_attention'
        registration_problem=state=='record_attention'
        if state in ['consistent','record_attention'] and doc:
            if not doc.get('file_id'):state='file_missing'
            else:
                try:key=uuid.UUID(doc['file_id']).hex
                except ValueError:key=None
                f=files.get(key);path=Path(root)/(str(uuid.UUID(key))+'.bin') if key else None
                if not key:state='file_attention'
                elif not f:state='file_missing'
                elif f['owner_id']!=user_id:state='no_access'
                elif not path.exists():state='file_missing'
                else:
                    raw=path.read_bytes()
                    if len(raw)!=f['size'] or hashlib.sha256(raw).hexdigest()!=f['file_hash'] or f['file_hash']!=doc['file_sha256']:state='file_attention'
                    elif f['kind']!='csv':state='unparsed'
                    else:
                        try:
                            text=raw.decode('utf-8-sig')
                            reader=csv.DictReader(io.StringIO(text));rows=list(reader)
                            correct=(reader.fieldnames is not None and len(reader.fieldnames)==len(set(reader.fieldnames)) and set(reader.fieldnames)==set(HEADERS) and len(rows)==1 and '\x00' not in text)
                            if correct:
                                original={k:v.strip() for k,v in rows[0].items()}
                                correct=all(original.get(k)==doc.get(k) for k in HEADERS)
                                correct&=all(timestamp(original.get(k)) for k in ['performed','valid_from','valid_until','issued'])
                            state='consistent' if correct else 'content_attention'
                        except (UnicodeError,csv.Error,AttributeError):state='content_attention'
        if registration_problem:state='record_attention'
        result[cal['id']]=dict(state=state,link_id=chosen['id'] if chosen else None,certificate_id=doc['id'] if doc else None)
    return result


def instruments_at(data,business,known,checks,window=30):
    rule_groups=registers(data.get('metrology_rules',[]),known,['stage','parameter','unit'])
    calibration_groups=registers(data.get('metrology_calibrations',[]),known,['instrument_id'])
    result={}
    for instrument in data.get('metrology_instruments',[]):
        iid=instrument['id'];required=None;chosen=None;hours=None
        if instrument['stage']=='档案':
            result[iid]=dict(required=None,calibration_state='unknown_rule',calibration_id=None,evidence_state='archive',due_state='archive',hours_to_expiry=None);continue
        identity=tuple(instrument.get(k) for k in ['stage','parameter','unit'])
        applicable_rules=[];bad=False
        for r,invalid,history in rule_groups:
            if identity not in {tuple(h.get(k) for k in ['stage','parameter','unit']) for h in history}:continue
            bad|=invalid
            if not r or r['status']=='撤销':continue
            bad|=not timestamp(r['effective']) or bool(r.get('expires') and (not timestamp(r['expires']) or r['expires']<=r['effective'])) or type(r['required']) is not bool
            if r['effective']<=business and (not r.get('expires') or business<r['expires']):applicable_rules.append(r)
        if len(applicable_rules)==1 and not bad:required=applicable_rules[0]['required']
        state='unknown_rule' if required is None else 'not_required' if required is False else 'missing'
        if required is True:
            applicable=[];bad=False
            for c,invalid,history in calibration_groups:
                if iid not in {h['instrument_id'] for h in history}:continue
                performed=[h['performed'] for h in history if timestamp(h.get('registered')) and h['registered']<=known and h['status']!='草稿']
                if performed and all(timestamp(t) and t>business for t in performed):continue
                if invalid or not c or not timestamp(c['performed']):bad=True
                elif c['performed']<=business:applicable.append(c)
            if bad:state='invalid'
            elif applicable:
                newest=max(c['performed'] for c in applicable);selected=[c for c in applicable if c['performed']==newest]
                if len(selected)!=1:state='conflict'
                else:
                    chosen=selected[0];c=chosen
                    if c['status']=='撤销':state='withdrawn'
                    elif not all(timestamp(c.get(k)) for k in ['performed','valid_from','valid_until']) or not c['performed']<=c['valid_from']<c['valid_until'] or c['performed']>c['registered'] or (c['parameter'],c['unit'])!=(instrument['parameter'],instrument['unit']) or not c.get('certificate_no') or not c.get('reference') or c['result'] not in ['符合登记范围','不符合登记范围']:state='invalid'
                    elif c['result']=='不符合登记范围':state='failed'
                    elif business<c['valid_from']:state='pending'
                    elif business>=c['valid_until']:state='expired'
                    else:state='valid'
            if not timestamp(instrument.get('active_from')) or instrument['active_from']>business or instrument.get('retired') and (not timestamp(instrument['retired']) or instrument['retired']<=instrument['active_from'] or instrument['retired']<=business):state='unknown_use';chosen=None
        evidence='not_required' if required is False else 'unknown_rule' if required is None else 'no_calibration' if not chosen else checks[chosen['id']]['state']
        due='not_required' if required is False else state if state in ['expired','failed','withdrawn'] else 'attention'
        if chosen and timestamp(chosen.get('valid_until')):hours=round((datetime.fromisoformat(chosen['valid_until'])-datetime.fromisoformat(business)).total_seconds()/3600,3)
        if state=='valid':due='due' if hours<=window*24 else 'later'
        result[iid]=dict(required=required,calibration_state=state,calibration_id=chosen['id'] if chosen else None,evidence_state=evidence,due_state=due,hours_to_expiry=hours)
    return result
