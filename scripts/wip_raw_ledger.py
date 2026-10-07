"""Independent raw XLSX-journal ledger; imports no application engine."""
from collections import defaultdict,Counter
from datetime import datetime
ACTIVE={"生产缓冲","返工区","隔离区"}

def rows_at(data,cutoff,known_cutoff=None):
    known_cutoff=known_cutoff or cutoff
    roots={r['id']:r for r in data['batches'] if r['kind'] in ['定子','转子'] and r['created']<=cutoff}
    master={k:{r['id']:r for r in data[k]} for k in ['wip_lots','wip_locations','units','work_orders','operations','employees','products']}
    lines=defaultdict(list);series=defaultdict(list);opens=defaultdict(list)
    for x in data['wip_event_lines']:lines[x['event_id']].append(x)
    for x in data['wip_event_versions']:series[x['series']].append(x)
    for x in data['wip_openings']:
        if x['occurred']<=cutoff and x['recorded']<=known_cutoff:opens[x['root_batch_id']].append(x)
    balance={};born=set();base={};begins={};bad=set();entered={};last={};members=defaultdict(set);used=set();consumed=Counter();scrap=Counter()
    def lot_ok(lot,root,at):
        l=master['wip_lots'].get(lot);r=roots.get(root);w=master['work_orders'].get(r['work_order_id']) if r else None
        return bool(l and w and l['product_id']==w['product_id'] and l['kind']==r['kind'] and l['created']<=at and l['container'] and l['note'])
    for key,r in roots.items():
        oo=opens[key]
        for o in oo:members[o['lot_id']].add(key)
        valid=bool(oo) and sum(o['qty'] for o in oo)==r['qty'] and len({(o['lot_id'],o['location_id']) for o in oo})==len(oo) and len({o['occurred'] for o in oo})==1
        valid=valid and all(type(o['qty']) is int and o['qty']>0 and r['created']<=o['occurred']<=o['recorded']<=known_cutoff and o['owner_id'] in master['employees'] and o['reference'] and o['note'] and lot_ok(o['lot_id'],key,o['occurred']) and master['wip_locations'][o['location_id']]['kind'] in ACTIVE for o in oo)
        if not valid:bad.add(key);continue
        base[key]=sum(o['qty'] for o in oo);begins[key]=oo[0]['occurred']
        for o in oo:
            balance[o['lot_id'],o['location_id'],key]=o['qty'];born.add(o['lot_id']);entered[o['lot_id'],o['location_id']]=o['occurred'];last[o['lot_id']]=o['occurred']
    events=[]
    for s,vv in series.items():
        known=[v for v in vv if v['recorded']<=known_cutoff];published=[v for v in known if v['status']!='草稿']
        if not published:continue
        if all(cutoff<v['occurred']<=v['recorded'] for v in published):continue
        h=max(published,key=lambda v:v['recorded']);ll=lines[h['id']];inputs=h['input_lots'].split(',');outputs=h['output_lots'].split(',')
        scope={x['root_batch_id'] for x in ll if x['root_batch_id'] in roots}
        prefix=sorted([v for v in known if v['version']<=h['version']],key=lambda v:v['version'])
        valid=len({v['recorded'] for v in published})==len(published) and len({v['version'] for v in known})==len(known)
        valid=valid and [v['version'] for v in prefix]==list(range(1,h['version']+1))
        valid=valid and all(v['previous_id']==(prefix[i-1]['id'] if i else None) and (i==0 or v['recorded']>prefix[i-1]['recorded']) for i,v in enumerate(prefix))
        valid=valid and h['line_count']==len(ll) and h['sequence']>0 and h['occurred']<=h['recorded'] and h['status'] in ['登记','作废'] and h['sender_id'] in master['employees'] and h['receiver_id'] in master['employees'] and bool(h['reference'] and h['note'])
        if valid and (h['occurred']>cutoff or h['status']=='作废'):continue
        events.append(dict(h=h,lines=ll,inputs=inputs,outputs=outputs,roots=scope,invalid=not valid))
    # Forward membership propagation anchors malformed downstream containers.
    changed=True
    while changed:
        changed=False
        for e in events:
            scope=e['roots']|set().union(*(members[l] for l in e['inputs']))
            if scope!=e['roots']:e['roots']=scope;changed=True
            for l in e['outputs']:
                declared={x['root_batch_id'] for x in e['lines'] if x['side']=='入' and x['lot_id']==l and x['root_batch_id'] in roots}
                old=len(members[l]);members[l]|=declared or scope;changed=changed or len(members[l])!=old
    touching=defaultdict(list)
    for i,e in enumerate(events):
        for l in set(e['inputs']+e['outputs']):touching[e['h']['occurred'],e['h']['sequence'],l].append(i)
    for ids in touching.values():
        if len(ids)>1:
            for i in ids:events[i]['invalid']=True
    applied=0
    for e in sorted(events,key=lambda e:(e['h']['occurred'],e['h']['sequence'],e['h']['series'])):
        h=e['h'];ll=e['lines'];out=[x for x in ll if x['side']=='出'];inc=[x for x in ll if x['side']=='入'];at=h['occurred'];kind=h['kind']
        ok=not e['invalid'] and not (e['roots']&bad) and all(r in begins and at>=begins[r] for r in e['roots'])
        ok=ok and len({(x['side'],x['lot_id'],x['location_id'],x['root_batch_id'],x['unit_id']) for x in ll})==len(ll)
        ok=ok and all(x['side'] in ['入','出'] and type(x['qty']) is int and x['qty']>0 and lot_ok(x['lot_id'],x['root_batch_id'],at) and x['location_id'] in master['wip_locations'] for x in ll)
        ok=ok and set(x['lot_id'] for x in out)==set(e['inputs']) and set(x['lot_id'] for x in inc)==set(e['outputs'])
        debit=Counter();credit=Counter();takes=Counter();pending=set();terminal=[];active_in=[]
        for x in out:
            debit[x['root_batch_id']]+=x['qty'];takes[x['lot_id'],x['location_id'],x['root_batch_id']]+=x['qty']
            ok=ok and not x['unit_id'] and master['wip_locations'][x['location_id']]['kind'] in ACTIVE
        for x in inc:
            credit[x['root_batch_id']]+=x['qty'];loc=master['wip_locations'][x['location_id']]['kind'];r=roots.get(x['root_batch_id'])
            if loc in ACTIVE:
                active_in.append(x);ok=ok and not x['unit_id']
            elif loc=='装配耗用':
                terminal.append(x);u=master['units'].get(x['unit_id']);identity=(x['unit_id'],r['kind']) if r else None
                field='stator_batch' if r and r['kind']=='定子' else 'rotor_batch'
                ok=ok and bool(u and r and x['qty']==1 and u[field]==r['id'] and u['product_id']==master['work_orders'][r['work_order_id']]['product_id'] and u['assembly_at']==at and identity not in used and identity not in pending)
                pending.add(identity)
            elif loc=='报废登记':terminal.append(x);ok=ok and not x['unit_id']
            else:ok=False
        expected={k:q for k,q in balance.items() if k[0] in e['inputs'] and q>0}
        ok=ok and bool(debit) and debit==credit and dict(takes)==expected
        source=set(e['inputs']);dest=set(e['outputs'])
        if kind=='拆批':ok=ok and len(source)==1 and len(dest)>=2 and not source&dest and not terminal
        elif kind=='合批':ok=ok and len(source)>=2 and len(dest)==1 and not source&dest and not terminal
        else:
            ok=ok and len(source)==1 and source==dest
            if kind in ['装配耗用','报废登记']:
                ok=ok and bool(terminal) and all(master['wip_locations'][x['location_id']]['kind']==kind for x in terminal) and all(x['location_id'] in {y['location_id'] for y in out} for x in active_in)
            else:ok=ok and not terminal and {x['location_id'] for x in out}!={x['location_id'] for x in active_in}
        if kind in ['拆批','合批']:ok=ok and not born&dest
        ok=ok and all(len({x['location_id'] for x in active_in if x['lot_id']==l})<=1 for l in dest)
        if kind in ['返工转入','隔离转入']:
            category='返工区' if kind=='返工转入' else '隔离区';ok=ok and all(master['wip_locations'][x['location_id']]['kind']==category for x in active_in)
        if kind in ['返工返回','隔离解除']:
            category='返工区' if kind=='返工返回' else '隔离区';ok=ok and all(master['wip_locations'][x['location_id']]['kind']==category for x in out) and all(master['wip_locations'][x['location_id']]['kind']=='生产缓冲' for x in active_in)
        if h['operation_id']:
            o=master['operations'].get(h['operation_id'])
            ok=ok and bool(o and o['status']=='完成' and o['object_type']=='生产批次' and o['object_id'] in e['roots'] and o['finished']<=at)
            if o and kind=='工序交接':ok=ok and all(master['wip_locations'][x['location_id']]['process']==o['process'] for x in active_in)
        if not ok:bad|=e['roots'];continue
        for k,q in takes.items():balance[k]-=q
        for x in active_in:
            k=(x['lot_id'],x['location_id'],x['root_batch_id']);balance[k]=balance.get(k,0)+x['qty']
            p=k[:2];retained=kind in ['装配耗用','报废登记'] and any(y['lot_id']==x['lot_id'] and y['location_id']==x['location_id'] for y in out)
            if not retained or p not in entered:entered[p]=at
        for x in terminal:
            if master['wip_locations'][x['location_id']]['kind']=='装配耗用':consumed[x['root_batch_id']]+=x['qty']
            else:scrap[x['root_batch_id']]+=x['qty']
        used|=pending;born|=dest
        for l in dest:last[l]=at
        applied+=1
    expected=defaultdict(set)
    for u in data['units']:
        if u['assembly_at']>cutoff:continue
        for field in ['stator_batch','rotor_batch']:
            r=u[field]
            if r in roots:
                expected[r].add(u['id'])
                if (u['id'],roots[r]['kind']) not in used:bad.add(r)
    changed=True
    while changed:
        changed=False
        for l in born:
            shares={r for (lot,z,r),q in balance.items() if lot==l and q>0}
            if shares&bad and not shares<=bad:bad|=shares;changed=True
    result={}
    for key,r in roots.items():
        positions=[]
        if key not in bad:
            for (lot,z,k),q in balance.items():
                if k!=key or q<=0:continue
                whole=sum(v for (ll,zz,rr),v in balance.items() if ll==lot and zz==z and v>0)
                positions.append(dict(lot_id=lot,location_id=z,qty=q,whole_lot_qty=whole,root_count=len({rr for (ll,zz,rr),v in balance.items() if ll==lot and zz==z and v>0}),entered_at=entered[lot,z],last_movement=last[lot],dwell_hours=(datetime.fromisoformat(cutoff)-datetime.fromisoformat(entered[lot,z])).total_seconds()/3600))
        active=None if key in bad else sum(p['qty'] for p in positions);baseline=base.get(key)
        state='missing' if baseline is None else 'attention' if key in bad else 'active' if active else 'consumed' if consumed[key]==baseline else 'closed'
        if active is not None:assert baseline==active+consumed[key]+scrap[key]
        result[key]=dict(state=state,baseline_qty=baseline,wip_qty=active,prefix_consumed_qty=consumed[key],prefix_scrap_qty=scrap[key],unknown_remainder=None if baseline is None else baseline-consumed[key]-scrap[key] if key in bad else 0,positions=positions,expected_consumption_sn=sorted(expected[key]),missing_consumption_sn=sorted(sn for sn in expected[key] if (sn,r['kind']) not in used))
    return result,applied
