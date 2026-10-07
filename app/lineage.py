"""Reverse material/batch genealogy, using explicit evidence, never WO expansion.

An affected SN means potentially associated, not proven defective. Source lot
codes lack a material key in the legacy sheet; warehouse issue evidence must
disambiguate them. Uncertain paths remain visible and are never called clear.
"""
from collections import defaultdict,deque,Counter
from decimal import Decimal
from functools import lru_cache
from . import analytics,delivery
from .models import Record

TYPES={'材料批次':'material_lot','生产批次':'batch','整机':'unit'}
LABELS={'material_lot':'材料批次','batch':'生产批次','unit':'电机SN'}
NOTICE='潜在关联不代表已经不合格。本页只依据已导入谱系，缺关联、换件、退货和现场未录入的流转仍须核验；不会自动冻结库存、停止发货或通知客户。材料消耗量不按比例分摊到SN。'
POLICY='reverse-genealogy-v1'

def idx(rows):return {r['id']:r for r in rows}
def groups(rows,key):
    out=defaultdict(list)
    for r in rows:out[r[key]].append(r)
    return out
def ref(ds,key):return {'dataset':ds,'key':key}

class Graph:
    def __init__(self,d):
        self.d=d;self.as_of=analytics.AS_OF;self.materials=idx(d['materials']);self.batches=idx(d['batches']);self.units=idx(d['units'])
        self.lots=defaultdict(set);self.issue_rows=defaultdict(list)
        for dataset in ['inventory_opening','inventory_movements','receipts']:
            for r in d[dataset]:
                when=r.get('occurred',r.get('received',r.get('as_of','')))
                if when>self.as_of:continue
                self.lots[r['lot']].add(r['material_id'])
                if dataset=='inventory_movements' and r['qty_signed']<0 and r.get('work_order_id'):self.issue_rows[(r['lot'],r['work_order_id'])].append(r)
        self.edges=[];self.children=defaultdict(list)
        for raw in d['genealogy']:
            if raw['occurred']>self.as_of:continue
            parent=(TYPES.get(raw['parent_type'],'unsupported'),raw['parent_id']);child=(TYPES.get(raw['child_type'],'unsupported'),raw['child_id'])
            errors=[]
            if parent[0]=='unsupported' or child[0]=='unsupported':errors.append('来源或目标类型未定义')
            if (parent[0],child[0]) not in {('material_lot','batch'),('batch','batch'),('batch','unit')}:errors.append('此类型之间的流转方向未定义')
            if raw['qty']<=0:errors.append('谱系消耗数量不是正数')
            if child[0]=='batch':
                b=self.batches.get(child[1])
                if not b:errors.append('目标生产批次缺失')
                elif b['work_order_id']!=raw['work_order_id'] or b['created']>raw['occurred']:errors.append('目标批次工单或时间不一致')
            if child[0]=='unit':
                u=self.units.get(child[1])
                if not u:errors.append('目标SN档案缺失')
                else:
                    if u['work_order_id']!=raw['work_order_id']:errors.append('目标SN工单与谱系不一致')
                    if u['assembly_at']>raw['occurred']:errors.append('谱系关联早于SN装配')
                    if parent[0]=='batch' and parent[1] not in [u.get('stator_batch'),u.get('rotor_batch'),u.get('assembly_batch')]:errors.append('谱系与SN批次档案不一致')
            if parent[0]=='batch':
                b=self.batches.get(parent[1])
                if not b:errors.append('来源生产批次缺失')
                elif b['work_order_id']!=raw['work_order_id'] or b['created']>raw['occurred']:errors.append('来源批次工单或时间不一致')
            evidence=[];materials=set()
            if parent[0]=='material_lot':
                movement=[m for m in self.issue_rows[(parent[1],raw['work_order_id'])] if m['occurred']<=raw['occurred']]
                materials={m['material_id'] for m in movement}
                evidence=[ref('inventory_movements',m['id']) for m in movement]
                if not movement:errors.append('缺少该工单在关联前的领料证据');materials=set(self.lots[parent[1]])
                if len(materials)!=1:errors.append('批号未能唯一对应物料')
                if len(materials)==1 and self.materials.get(next(iter(materials)),{}).get('unit')!=raw['unit']:errors.append('谱系单位与物料单位不一致')
            edge={**raw,'parent':parent,'child':child,'materials':sorted(materials),'issues':errors,'issue_sources':evidence}
            self.edges.append(edge);self.children[parent].append(edge)
        # Compare only unique material assignments; uncertainty is not distributed.
        assigned=defaultdict(list)
        for e in self.edges:
            if e['parent'][0]=='material_lot' and len(e['materials'])==1:assigned[(e['parent'][1],e['materials'][0],e['work_order_id'])].append(e)
        self.reconciliation=[]
        for (lot,material,wo),edges in sorted(assigned.items()):
            movements=[m for m in self.issue_rows[(lot,wo)] if m['material_id']==material]
            issued=sum((Decimal(str(-m['qty_signed'])) for m in movements),Decimal(0));linked=sum((Decimal(str(e['qty'])) for e in edges),Decimal(0));unit=self.materials.get(material,{}).get('unit')
            valid=abs(issued-linked)<=Decimal('0.001') and all(e['unit']==unit for e in edges)
            if not valid:
                for e in edges:e['issues'].append('工单同物料同批号的领料量与谱系量未对平')
            self.reconciliation.append({'lot':lot,'material_id':material,'work_order_id':wo,'unit':unit,'issued_qty':float(issued),'linked_qty':float(linked),'matched':valid,'source_ids':[m['id'] for m in movements]})
        for (lot,wo),movements in self.issue_rows.items():
            for mid in {m['material_id'] for m in movements}:
                if (lot,mid,wo) in assigned:continue
                selected=[m for m in movements if m['material_id']==mid]
                self.reconciliation.append({'lot':lot,'material_id':mid,'work_order_id':wo,'unit':self.materials.get(mid,{}).get('unit'),'issued_qty':float(sum(Decimal(str(-m['qty_signed'])) for m in selected)),'linked_qty':None,'matched':False,'source_ids':[m['id'] for m in selected]})

    def search(self,kind,q):
        if kind not in ['material_lot','batch']:raise ValueError('请选择材料批次或生产批次')
        q=q.strip().lower()
        if len(q)>100:raise ValueError('搜索内容过长')
        found=[]
        if kind=='material_lot':
            for lot,materials in sorted(self.lots.items()):
                for mid in sorted(materials):
                    m=self.materials.get(mid,{})
                    row={'kind':kind,'id':lot,'material_id':mid,'label':m.get('name',mid),'unit':m.get('unit'),'detail':mid+' · '+m.get('category','')}
                    if q in ' '.join(str(v) for v in row.values()).lower():found.append(row)
        else:
            for b in sorted(self.batches.values(),key=lambda r:r['id']):
                if b['created']>self.as_of:continue
                row={'kind':kind,'id':b['id'],'material_id':'','label':b['kind'],'detail':b['work_order_id']+' · '+str(b['qty'])+'件'}
                if q in ' '.join(str(v) for v in row.values()).lower():found.append(row)
        return {'rows':found[:40],'total':len(found),'limit':40}

    def build(self,kind,key,material_id=''):
        if kind not in ['material_lot','batch']:raise ValueError('反查对象类型不可用')
        if not isinstance(key,str) or not 1<=len(key)<=150:raise ValueError('请输入有效批次编号')
        if kind=='material_lot':
            materials=self.lots.get(key,set())
            if not materials:raise Record.DoesNotExist()
            if not material_id and len(materials)==1:material_id=next(iter(materials))
            if material_id not in materials:raise ValueError('此批号需明确选择物料编码，不能合并同名批号')
            material=self.materials.get(material_id,{})
            root={'kind':kind,'id':key,'material_id':material_id,'label':material.get('name',material_id),'unit':material.get('unit')}
        else:
            if key not in self.batches or self.batches[key]['created']>self.as_of:raise Record.DoesNotExist()
            root={'kind':kind,'id':key,'material_id':'','label':self.batches[key]['kind'],'unit':'件'}
        start=(kind,key);queue=deque([(start,False,[])]);visited={};reachable={};paths={};warnings=[];nodes={start}
        while queue:
            node,uncertain,path=queue.popleft();state=(node,uncertain)
            arrival=reachable[path[-1]]['occurred'] if path else ''
            # An earlier valid arrival may unlock downstream events that a
            # later path could not justify. Keep results independent of row order.
            if state in visited and visited[state]<=arrival:continue
            visited[state]=arrival
            if len(visited)>20000:raise ValueError('关联范围超过当前演示容量，请缩小到生产批次核对')
            if node[0]=='unit':
                if node not in paths or (paths[node]['uncertain'] and not uncertain):paths[node]={'uncertain':uncertain,'path':path}
            for e in self.children[node]:
                if node==start and kind=='material_lot' and e['materials'] and material_id not in e['materials']:continue
                reachable[e['id']]=e;nodes.add(e['child']);bad=uncertain or bool(e['issues'])
                if path and e['occurred']<reachable[path[-1]]['occurred']:
                    bad=True;warnings.append({'kind':'time_chain','object':e['id'],'message':'此路径下游关联早于上游消耗，不能确认物料已用于该SN。'})
                queue.append((e['child'],bad,path+[e['id']]))
        # Kahn's algorithm identifies cycles (including their downstream tail).
        degree={n:0 for n in nodes};adj=defaultdict(set)
        for e in reachable.values():
            if e['child'] not in adj[e['parent']]:adj[e['parent']].add(e['child']);degree[e['child']]+=1
        zeros=deque(n for n,v in degree.items() if not v)
        while zeros:
            n=zeros.popleft()
            for child in adj[n]:
                degree[child]-=1
                if degree[child]==0:zeros.append(child)
        cycles={n for n,v in degree.items() if v}
        if cycles:warnings.append({'kind':'cycle','object':key,'message':'存在循环谱系或受循环影响的路径，请核对原始关联；相关SN按待核对范围保留。'})
        for e in reachable.values():
            for message in e['issues']:warnings.append({'kind':'edge','object':e['id'],'message':message})
        selected=[]
        for node,path in sorted(paths.items()):
            u=self.units.get(node[1])
            if not u or u['assembly_at']>self.as_of:
                warnings.append({'kind':'missing_unit','object':node[1],'message':'关联目标SN不存在或尚未在快照前装配，无法纳入已识别SN数量。'});continue
            selected.append((u,{**path,'uncertain':path['uncertain'] or node in cycles}))
        # Missing genealogy cannot be replaced with a same-WO inference.
        reached_batches={n[1] for n in nodes if n[0]=='batch'};linked_ids={u['id'] for u,_ in selected}
        unmatched=[u for u in self.units.values() if u['assembly_at']<=self.as_of and reached_batches.intersection([u.get('stator_batch'),u.get('rotor_batch'),u.get('assembly_batch')]) and u['id'] not in linked_ids]
        for u in unmatched:warnings.append({'kind':'missing_link','object':u['id'],'message':'SN档案引用相关批次但缺少可达谱系，单列为档案待核对候选。'})
        candidates=selected+[(u,{'uncertain':True,'path':[]}) for u in sorted(unmatched,key=lambda r:r['id'])]
        rows=self.unit_rows(candidates)
        unresolved_leaves=[n for n in nodes if n[0]=='batch' and not self.children[n]]
        for n in unresolved_leaves:warnings.append({'kind':'batch_leaf','object':n[1],'message':'相关批次尚无下游谱系；可能在制或漏录，须核查。'})
        warnings=list({(w['kind'],w['object'],w['message']):w for w in warnings}.values())
        source_refs={('genealogy',e['id']) for e in reachable.values()}
        source_refs.update((x['dataset'],x['key']) for e in reachable.values() for x in e['issue_sources'])
        source_refs.update(('batches',b) for b in reached_batches if b in self.batches)
        source_refs.update((x['dataset'],x['key']) for r in rows for x in r.pop('_sources'))
        if material_id:source_refs.add(('materials',material_id))
        summary={'unit_count':len(rows),'clear_path_count':sum(r['relation']=='谱系可核对' for r in rows),'uncertain_count':sum(r['relation']!='谱系可核对' for r in rows),'shipped_count':sum(r['shipped'] for r in rows),'unshipped_count':sum(not r['shipped'] for r in rows),'quality_attention_count':sum(r['quality_attention'] for r in rows),'work_order_count':len({r['work_order_id'] for r in rows}),'order_count':len({o for r in rows for o in r['order_ids']}),'customer_count':len({c['id'] for r in rows for c in r['customers']}),'batch_count':len(reached_batches),'edge_count':len(reachable),'warning_count':len(warnings)}
        batch_rows=[{k:b[k] for k in ['id','work_order_id','kind','qty','created','status']} for b in self.batches.values() if b['id'] in reached_batches]
        edges=[{k:e[k] for k in ['id','parent_type','parent_id','child_type','child_id','qty','unit','occurred','work_order_id','issues']} for e in sorted(reachable.values(),key=lambda e:(e['occurred'],e['id']))]
        reconciliation=[r for r in self.reconciliation if kind=='material_lot' and r['lot']==key and r['material_id']==material_id]
        for r in reconciliation:
            source_refs.update(('inventory_movements',key) for key in r['source_ids'])
            if r['linked_qty'] is None:warnings.append({'kind':'missing_material_link','object':r['work_order_id'],'message':'有此物料批次领料，但没有唯一可核对的材料谱系；不按同工单推算受影响SN。'})
        summary['warning_count']=len(warnings)
        return {'root':root,'as_of':self.as_of,'policy':POLICY,'summary':summary,'units':rows,'batches':sorted(batch_rows,key=lambda b:b['id']),'edges':edges,'warnings':warnings,'reconciliation':reconciliation,'sources':[ref(ds,k) for ds,k in sorted(source_refs)],'notice':NOTICE,'release_rule':delivery.RELEASE_RULE}

    def unit_rows(self,selected):
        d=self.d;as_of=self.as_of;products=idx(d['products']);orders=idx(d['orders']);lines=idx(d['order_lines']);customers=idx(d['customers'])
        alloc=groups([a for a in d['allocations'] if a['effective']<=as_of[:10]],'work_order_id')
        sessions,inconsistent=analytics.quality_state(d);bad=set(inconsistent);measurements=groups(d['measurements'],'session_id')
        releases=groups([r for r in d['releases'] if r['released']<=as_of],'unit_id')
        shipments=idx([s for s in d['shipments'] if s['shipped']<=as_of]);packing=groups([p for p in d['shipment_units'] if p['shipment_id'] in shipments],'unit_id')
        out=[]
        for u,evidence in selected:
            uid=u['id'];ss=sessions[uid];latest=ss[-1] if ss else None;release=max(releases[uid],key=lambda r:(r['released'],r['id']),default=None)
            quality=latest['calculated_result'] if latest else '未检测'
            valid=bool(latest and release and quality=='合格' and latest['tested']>=u['assembly_at'] and release['status']=='批准放行' and release['session_id']==latest['id'] and release['released']>=max(latest['tested'],u['assembly_at']))
            ships=[shipments[s] for s in sorted({p['shipment_id'] for p in packing[uid]})];line_ids={a['order_line_id'] for a in alloc[u['work_order_id']]};ownership='工单唯一分配' if len(line_ids)==1 else '订单归属待核对'
            confirmed_lines=set(line_ids) if len(line_ids)==1 else set()
            shipped_lines={s['order_line_id'] for s in ships};confirmed_lines.update(shipped_lines)
            if len(line_ids)==1 and shipped_lines and not shipped_lines.issubset(line_ids):ownership='装箱与分配冲突'
            elif len(line_ids)!=1 and ships:ownership='装箱明确，生产分配待核对'
            order_ids=sorted({lines[l]['order_id'] for l in confirmed_lines if l in lines});customer_ids=sorted({orders[o]['customer_id'] for o in order_ids if o in orders})
            issues=[]
            if len(ships)>1 or len(packing[uid])>len(ships):issues.append('同一SN有重复装箱或多个发货行')
            if any(s['shipped']<u['assembly_at'] for s in ships):issues.append('发货早于装配')
            if any(s['id'] in bad or s['tested']<u['assembly_at'] or any(m['id'] in bad for m in measurements[s['id']]) for s in ss):issues.append('检测结论或时间待核对')
            if '冲突' in ownership:issues.append('订单归属冲突')
            sources=[ref('units',uid),ref('work_orders',u['work_order_id']),ref('products',u['product_id'])]+[ref('test_sessions',s['id']) for s in ss]+[ref('releases',r['id']) for r in releases[uid]]+[ref('shipments',s['id']) for s in ships]+[ref('shipment_units',p['id']) for p in packing[uid]]+[ref('allocations',a['id']) for a in alloc[u['work_order_id']]]+[ref('order_lines',l) for l in confirmed_lines]+[ref('orders',o) for o in order_ids]+[ref('customers',c) for c in customer_ids]
            sources.extend(ref('measurements',m['id']) for s in ss for m in measurements[s['id']])
            sources.extend(ref('test_specs',m['spec_id']) for s in ss for m in measurements[s['id']])
            out.append({'id':uid,'work_order_id':u['work_order_id'],'product_id':u['product_id'],'family':products.get(u['product_id'],{}).get('family','未知'),'assembly_at':u['assembly_at'],'relation':'档案候选，缺少谱系' if not evidence['path'] else '关联待核对' if evidence['uncertain'] else '谱系可核对','path':evidence['path'],'quality':quality,'session_id':latest['id'] if latest else None,'release_id':release['id'] if release else None,'release_valid':valid,'shipped':bool(ships),'shipment_ids':[s['id'] for s in ships],'shipment_dates':[s['shipped'] for s in ships],'quality_attention':not valid or bool(issues),'ownership':ownership,'order_line_ids':sorted(confirmed_lines),'order_ids':order_ids,'customers':[{'id':c,'name':customers.get(c,{}).get('name',c)} for c in customer_ids],'issues':issues,'_sources':sources})
        return out

@lru_cache(maxsize=1)
def graph(revision):return Graph(analytics._tables(revision))

def current(kind,key,material_id=''):
    revision=analytics.revision();result=graph(revision).build(kind,key,material_id);result['data_revision']=list(revision);return result

def select(snapshot,query):
    allowed={'stage','q','page','kind','id','material_id','case_id'}
    if set(query)-allowed:raise ValueError('不支持的反查筛选')
    stage=query.get('stage','all');q=query.get('q','').strip().lower()
    if stage not in ['all','shipped','unshipped','quality','uncertain']:raise ValueError('对象状态不可用')
    if len(q)>150:raise ValueError('检索内容过长')
    units=[r for r in snapshot['units'] if (stage=='all' or stage=='shipped' and r['shipped'] or stage=='unshipped' and not r['shipped'] or stage=='quality' and r['quality_attention'] or stage=='uncertain' and r['relation']!='谱系可核对') and q in ' '.join([r['id'],r['work_order_id'],r['product_id'],*r['order_ids'],*(c['name'] for c in r['customers'])]).lower()]
    return units,{'stage':stage,'q':q}
