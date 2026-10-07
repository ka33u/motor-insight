"""Order-line evidence over a selected material rehearsal; never allocate SNs."""
from collections import defaultdict
from .models import Record

STAGES={'all':'关联订单行','open':'仍有未交','short':'未交且关联缺料','covered':'选中待投料均可覆盖','attention':'分配或资料待核对'}
NOTE='订单影响仅按截止前明确生效的工单订单分配追查。分配量是计划关系，备料覆盖量/缺料关联量不是已产出、可发货或预测延期台数；共用工单不推断SN归属。发货按订单行有效流水汇总，未交量不分摊给某一缺料工单。'

def integer(value,positive=True):
    if type(value) is not int or value<(1 if positive else 0):raise ValueError('数量须为正整数' if positive else '数量须为非负整数')
    return value

class OrderImpact:
    def __init__(self,planning):
        from .material_planning import day,stamp,refs,unique
        self.planning=planning;d=planning.data;cutoff=planning.cutoff;today=cutoff[:10];self.rows=[];self.index={};self.unlinked=[]
        self.work={r['id']:r for r in d.get('work_orders',[])};self.lines={r['id']:r for r in d.get('order_lines',[])};self.orders={r['id']:r for r in d.get('orders',[])};self.customers={r['id']:r for r in d.get('customers',[])}
        by_wo=defaultdict(list);by_line=defaultdict(list);wo_issues=defaultdict(list);line_issues=defaultdict(list);by_ship=defaultdict(list);ignored_future=0
        seen=set();alloc=[]
        for source in d.get('allocations',[]):
            a={**source,'issues':[]};wid=a.get('work_order_id');lid=a.get('order_line_id');wo=self.work.get(wid);line=self.lines.get(lid)
            try:
                if day(a.get('effective')).isoformat()>today:ignored_future+=1;continue
            except (ValueError,TypeError):a['issues'].append('分配生效日期无效')
            try:integer(a.get('qty'))
            except ValueError as e:a['issues'].append(str(e))
            if not wo:a['issues'].append('分配引用工单不存在')
            if not line:a['issues'].append('分配引用订单行不存在')
            if wo and line and wo.get('product_id')!=line.get('product_id'):a['issues'].append('分配工单与订单行配置不一致')
            identity=(wid,lid,a.get('effective'))
            if identity in seen:
                a['issues'].append('同工单、订单行、生效日存在重复分配')
                wo_issues[wid].append('同工单、订单行、生效日存在重复分配');line_issues[lid].append('同工单、订单行、生效日存在重复分配')
            seen.add(identity);alloc.append(a);by_wo[wid].append(a);by_line[lid].append(a)
        for wid,aa in by_wo.items():
            wo=self.work.get(wid)
            try:
                if not wo:raise ValueError('分配引用工单不存在')
                capacity=integer(wo.get('planned_qty'))
                if all(type(a.get('qty')) is int and a['qty']>0 for a in aa) and sum(a['qty'] for a in aa)>capacity:raise ValueError('工单全部订单分配量超过计划数量')
            except ValueError as e:wo_issues[wid].append(str(e))
            wo_issues[wid]+=list(dict.fromkeys(x for a in aa for x in a['issues']))
        for lid,aa in by_line.items():
            line=self.lines.get(lid)
            try:
                if not line:raise ValueError('分配引用订单行不存在')
                qty=integer(line.get('qty'))
                if all(type(a.get('qty')) is int and a['qty']>0 for a in aa) and sum(a['qty'] for a in aa)>qty:raise ValueError('订单行全部工单分配量超过订单数量')
            except ValueError as e:line_issues[lid].append(str(e))
        for s in d.get('shipments',[]):
            try:
                if stamp(s.get('shipped'))>cutoff:continue
            except (ValueError,TypeError):line_issues[s.get('order_line_id')].append('发货日期无效，当前未交量不可核对')
            by_ship[s.get('order_line_id')].append(s)
        touched={a.get('order_line_id') for a in alloc if a.get('work_order_id') in planning.orders and a.get('order_line_id') in self.lines}
        for lid in touched:
            line=self.lines[lid];order=self.orders.get(line.get('order_id'));p=planning.products.get(line.get('product_id'));customer=self.customers.get(order.get('customer_id')) if order else None
            aa=by_line[lid];selected=[a for a in aa if a['work_order_id'] in planning.orders];issues=list(line_issues[lid]);sources=refs('order_lines',[line])+refs('allocations',aa)+refs('shipments',by_ship[lid])
            for wid in {a['work_order_id'] for a in aa}:
                sources+=refs('allocations',by_wo[wid])+refs('order_lines',[self.lines[x['order_line_id']] for x in by_wo[wid] if x['order_line_id'] in self.lines])
            for a in aa:issues+=a['issues']+wo_issues[a['work_order_id']]
            if not order:issues.append('订单主表缺失')
            else:
                sources+=refs('orders',[order])
                try:
                    if day(order.get('order_date')).isoformat()>today:raise ValueError('订单尚未在截止前建立')
                except (ValueError,TypeError) as e:issues.append(str(e))
                if order.get('status') not in ['待生产','部分交付','已交付','已完成']:issues.append('订单状态未映射，未自动解释取消或暂停')
            if not customer:issues.append('客户档案缺失')
            else:sources+=refs('customers',[customer])
            if not p:issues.append('产品配置档案缺失')
            else:sources+=refs('products',[p])
            qty=None;shipped=None;remaining=None;due=None
            try:qty=integer(line.get('qty'));due=day(line.get('due')).isoformat()
            except (ValueError,TypeError) as e:issues.append(str(e))
            ship_issues=[];shipment_qty=0
            for s in by_ship[lid]:
                try:
                    integer(s.get('qty'));stamp(s.get('shipped'));shipment_qty+=s['qty']
                    if order and s['shipped'][:10]<order.get('order_date',''):raise ValueError('发货早于订单建立')
                except (ValueError,TypeError) as e:ship_issues.append(s['id']+'：'+str(e))
            if qty is not None and shipment_qty>qty:ship_issues.append('发货台数超过订单数量')
            if not ship_issues and not any('发货日期' in x for x in issues) and qty is not None:shipped=shipment_qty;remaining=qty-shipped
            issues+=ship_issues;links=[]
            for a in aa:
                wid=a['work_order_id'];w=self.work.get(wid);calc=planning.orders.get(wid);local=list(dict.fromkeys(a['issues']+wo_issues[wid]));sources+=refs('work_orders',[w]) if w else []
                if calc and calc['issues']:local+=calc['issues']
                late=None
                try:
                    if w and due:late=day(w.get('planned_end')).isoformat()>due
                except (ValueError,TypeError):local.append('工单计划完工日期无效')
                links.append({'id':a['id'],'work_order_id':wid,'qty':a.get('qty'),'effective':a.get('effective'),'selected':bool(calc),'state':calc['state'] if calc else 'outside','sequence':calc['sequence'] if calc else None,'planned_end':w.get('planned_end') if w else None,'plan_after_due':late,'shared':len({x['order_line_id'] for x in by_wo[wid]})>1,'issues':list(dict.fromkeys(local)),
                              'short_materials':[{'id':i['material_id'],'material':i['material'],'unit':i['unit'],'remaining_required':i['remaining_required'],'before_pool':i['before_pool'],'gap':i['gap']} for i in calc['items'] if i['gap'] and i['gap']>0] if calc else []})
            # Relationship quantities are unavailable if any global allocation guard fails.
            relation_ok=not issues and not any(x['issues'] for x in links)
            issues=list(dict.fromkeys(issues+[x for a in links for x in a['issues']]))
            buckets={key:0 if relation_ok else None for key in ['covered','short','attention','excluded','outside']}
            if relation_ok:
                for a in links:buckets[a['state']]+=a['qty']
            selected_ids=sorted({a['work_order_id'] for a in links if a['selected']});outside_ids=sorted({a['work_order_id'] for a in links if not a['selected']});active=[a for a in links if a['selected'] and a['state']!='excluded']
            short_ids=sorted({a['work_order_id'] for a in active if a['state']=='short'}) if relation_ok else []
            flags=['all']+(['open'] if remaining is not None and remaining>0 else [])+(['short'] if remaining and short_ids else [])+(['attention'] if issues else [])+(['covered'] if relation_ok and active and all(a['state']=='covered' for a in active) else [])
            row={'id':lid,'order_id':line.get('order_id'),'customer_id':order.get('customer_id') if order else None,'customer':customer.get('name') if customer else '档案缺失','product_id':line.get('product_id'),'family':p.get('family') if p else '未知','due':line.get('due'),'qty':qty,'shipped_qty':shipped,'remaining_qty':remaining,'overdue_remaining_qty':remaining if due and due<today else 0 if due else None,
                 'selected_allocated_qty':sum(a['qty'] for a in selected) if relation_ok else None,'all_allocated_qty':sum(a['qty'] for a in aa) if relation_ok else None,'unallocated_qty':max(0,qty-sum(a['qty'] for a in aa)) if relation_ok else None,'short_link_qty':buckets['short'],'covered_link_qty':buckets['covered'],'excluded_link_qty':buckets['excluded'],'outside_link_qty':buckets['outside'],
                 'work_orders':selected_ids,'outside_work_orders':outside_ids,'short_work_orders':short_ids,'plan_after_due_count':len({a['work_order_id'] for a in links if a['selected'] and a['plan_after_due'] is True}),'issues':issues,'flags':flags,'state':'attention' if issues else 'short' if 'short' in flags else 'covered' if 'covered' in flags else 'open' if 'open' in flags else 'closed','links':links,'sources':unique(sources)}
            self.rows.append(row);self.index[lid]=row
        for wid in planning.orders:
            aa=by_wo[wid];problems=list(wo_issues[wid])
            if not aa:problems.append('截止前没有明确订单分配，未按型号补配')
            related=[self.index.get(a['order_line_id']) for a in aa]
            if any(r and r['issues'] for r in related):problems.append('关联订单行资料待核对')
            if problems:self.unlinked.append({'id':wid,'issues':list(dict.fromkeys(problems))})
        self.rows.sort(key=lambda r:(r['due'] or '9999-12-31',r['id']));self.ignored_future=ignored_future

    def summary(self):
        r=self.rows
        return {'lines':len(r),'orders':len({x['order_id'] for x in r}),'open_lines':sum('open' in x['flags'] for x in r),'short_lines':sum('short' in x['flags'] for x in r),'short_link_qty':sum(x['short_link_qty'] or 0 for x in r if 'short' in x['flags']),
                'attention_lines':sum('attention' in x['flags'] for x in r),'outside_lines':sum(bool(x['outside_work_orders']) for x in r),'unlinked_work_orders':len(self.unlinked),'selected_work_orders':len(self.planning.orders)}

    def detail(self,key):
        from .material_planning import unique
        if key not in self.index:raise Record.DoesNotExist()
        row=self.index[key];sources=list(row['sources'])
        for wid in row['work_orders']:sources+=self.planning.detail('orders',wid)['sources']
        return {'row':row,'sources':unique(sources),'impact_note':NOTE}
