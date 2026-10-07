"""Same-population descriptive breakdowns for pinned operating targets.

No subgroup budgets or causal attribution are inferred. Every path selects a
mutually exclusive bucket from the already authorized target population.
"""
import json,re
from collections import defaultdict
from decimal import Decimal
from . import targets as k,access,analysis_engine as engine,derived_metrics as dm
from .models import Record

NOTICE='分组解释实际构成，不将总目标分摊给各组，也不单独判断各组达标。组间差异仅提示核查方向，不能证明原因；每层保留目标期间、模型筛选和来源粒度。'
PREFERRED={'units':['product.family','product_id','work_order_id','status'],'labor_entries':['activity','product.family','work_order_id','started'],'invoices':['customer_id','issued','status'],'bi_units':['family','product_id','first_equipment','latest_result'],'bi_order_lines':['family','customer','region'],'bi_equipment_day':['workshop','equipment_id','date'],'bi_energy_day':['workshop','date']}
FAMILY_DIRECT={'units','work_orders','order_lines','products'}
FAMILY_WORK_ORDER={'labor_entries','operations','costs'}

def parse_path(raw):
    if not isinstance(raw,str) or len(raw)>6000:raise ValueError('分组路径过长')
    try:path=json.loads(raw)
    except (ValueError,TypeError):raise ValueError('分组路径格式无效')
    if not isinstance(path,list) or len(path)>3:raise ValueError('最多进入3个上层分组')
    for p in path:
        if not isinstance(p,dict) or set(p)!={'dimension','grain','token'} or not isinstance(p['token'],str) or not re.fullmatch('[a-f0-9]{64}',p['token']):raise ValueError('分组路径字段无效')
    return path

class Breakdown:
    def __init__(self,user,key,targets=None):
        self.user=user;self.targets=targets or k.Targets(user);self.target=self.targets.detail(key)
        if self.target['state']=='blocked':raise ValueError('目标或模型规则待核对，暂不能进行分组分析')
        self.e=self.targets.calculate(self.targets.targets[key]);self.dataset=self.e['dataset'];self.rows=self.e['rows']
        self.definition=engine.validate_definition(user,self.dataset,self.e['definition']);self.fields={f['name']:f for f in access.permitted_fields(user,self.dataset)}
        self.options=[dict(name=f['name'],label=f['label'],type=f['type'],contextual=False) for f in self.fields.values() if f['type'] in ['str','bool','date','datetime']]
        self.lookups={};self.family_mode=None
        # A unique authoritative lookup adds context without multiplying facts.
        if 'family' not in self.fields and self.dataset in FAMILY_DIRECT|FAMILY_WORK_ORDER and access.allowed(user,'products') and 'family' in {f['name'] for f in access.permitted_fields(user,'products')}:
            self.family_mode='direct' if self.dataset in FAMILY_DIRECT else 'work_order'
            if self.family_mode=='work_order' and not access.allowed(user,'work_orders'):self.family_mode=None
            if self.family_mode:
                self.lookups['products']={r['id']:r for r in Record.objects.filter(dataset='products').values_list('values',flat=True)}
                if self.family_mode=='work_order':self.lookups['work_orders']={r['id']:r for r in Record.objects.filter(dataset='work_orders').values_list('values',flat=True)}
                self.options.append(dict(name='product.family',label='产品族（配置档案）',type='str',contextual=True))
        preferred=PREFERRED.get(self.dataset,[]);self.options.sort(key=lambda x:(preferred.index(x['name']) if x['name'] in preferred else len(preferred),x['label']))
        self.option_map={o['name']:o for o in self.options};self.factor=Decimal(self.e['unit_factor']);self.compiled=dm.compile_definitions(self.dataset,self.definition,self.fields)
        measure=self.target['measure'];self.metric=self.definition['metrics'][int(measure[1:])] if measure.startswith('m') else None
        self.kind=self.metric['agg'] if self.metric else 'derived';self.selected_compiled=next((x for x in self.compiled if x['key']==measure),None)
        used=[self.metric] if self.metric else [self.definition['metrics'][int(ref[1:])] for ref in self.selected_compiled['refs']]
        self.required={f for m in used if m['agg']!='count' for f in [m.get('field'),*([m['denominator']] if m['agg']=='ratio' else [])]}

    def axis(self,dimension,grain):
        if not isinstance(dimension,str) or dimension not in self.option_map:raise ValueError('分组字段不存在或无权访问')
        field=self.option_map[dimension]
        if grain not in ['value','day','month'] or (grain!='value' and field['type'] not in ['date','datetime']):raise ValueError('分组日期粒度不可用')
        return {'dimension':dimension,'grain':grain,'label':field['label']+{'value':'','day':' · 按日','month':' · 按月'}[grain]}

    def context(self,row):
        refs=[]
        if self.family_mode=='work_order':
            wo=self.lookups['work_orders'].get(row.get('work_order_id'))
            if not wo:return None,'missing_link',refs
            refs.append({'dataset':'work_orders','key':wo['id']});pid=wo.get('product_id')
        else:pid=row.get('product_id')
        product=self.lookups['products'].get(pid)
        if not product:return None,'missing_link',refs
        refs.append({'dataset':'products','key':product['id']});value=product.get('family')
        return value,'missing_value' if value is None else 'value',refs

    def bucket(self,row,axis):
        field=axis['dimension'];kind='value'
        if field=='product.family':value,kind,_=self.context(row)
        else:
            value=row.get(field)
            if value is None:kind='missing_value'
        if value is not None and axis['grain']!='value':value=str(value)[:10 if axis['grain']=='day' else 7]
        label='关联配置缺失' if kind=='missing_link' else '未填写' if kind=='missing_value' else '是' if value is True else '否' if value is False else str(value)
        if kind=='value' and label in ['未填写','关联配置缺失']:label='原值：'+label
        token=k.digest([field,axis['grain'],kind,type(value).__name__,value])
        return {'token':token,'label':label,'missing_kind':kind if kind!='value' else None}

    def partition(self,rows,axis):
        grouped={}
        for r in rows:
            b=self.bucket(r,axis);entry=grouped.setdefault(b['token'],{**b,'rows':[]});entry['rows'].append(r)
        return grouped

    def selection(self,path):
        rows=self.rows;breadcrumbs=[];seen=set()
        for item in path:
            axis=self.axis(item['dimension'],item['grain']);pair=(axis['dimension'],axis['grain'])
            if pair in seen:raise ValueError('同一分组维度和粒度不能重复进入')
            seen.add(pair);g=self.partition(rows,axis).get(item['token'])
            if g is None:raise ValueError('分组已不存在或不属于当前上层范围，请返回刷新')
            rows=g['rows'];breadcrumbs.append({**axis,'token':item['token'],'value':g['label'],'rows':len(rows)})
        return rows,breadcrumbs

    def aggregate(self,rows):
        missing=sum(any(r.get(f) is None for f in self.required) for r in rows)
        if not rows:return dict(actual=None,source_rows=0,valid_rows=0,missing_rows=0,numerator=None,denominator=None,quantile=None,notes=[])
        out,parts,notes=engine.aggregate_group(self.dataset,self.definition,self.fields,self.compiled,rows,'当前范围');scalar=out.get(self.target['measure'])
        if scalar is not None and k.number(scalar) is None:raise ValueError('分组结果不是可比较的有限数字')
        part=next((c for c in parts if self.target['measure']==f"m{c['metric_index']}"),{})
        return dict(actual=float(Decimal(str(scalar))*self.factor) if scalar is not None else None,source_rows=len(rows),valid_rows=len(rows)-missing,missing_rows=missing,numerator=part.get('numerator'),denominator=part.get('denominator'),quantile=out.get('quantiles',{}).get(self.target['measure']),notes=[n['reason'] for n in notes if n['metric']==self.target['measure']])

    def prepare(self,p):
        path=parse_path(p.get('path','[]'));rows,breadcrumbs=self.selection(path);used={(x['dimension'],x['grain']) for x in path}
        options=[o for o in self.options if any((o['name'],grain) not in used for grain in (['day','month','value'] if o['type'] in ['date','datetime'] else ['value']))]
        dimension=p.get('dimension') or (options[0]['name'] if options else None)
        default='day' if self.option_map.get(dimension,{}).get('type') in ['date','datetime'] else 'value'
        axis=self.axis(dimension,p.get('grain') or default)
        if (axis['dimension'],axis['grain']) in used:raise ValueError('当前维度已在上层路径中使用，请选择另一维度或日期粒度')
        grouped=self.partition(rows,axis);sort=p.get('sort','desc')
        if sort not in ['asc','desc','label','samples']:raise ValueError('分组排序不可用')
        return rows,breadcrumbs,options,axis,grouped,sort,path

    def calculate(self,p):
        rows,breadcrumbs,options,axis,grouped,sort,path=self.prepare(p);parent=self.aggregate(rows);total=self.aggregate(self.rows);results=[]
        for g in grouped.values():
            a=self.aggregate(g['rows']);a.update({key:g[key] for key in ['token','label','missing_kind']});a['difference']=a['actual']-parent['actual'] if self.kind not in ['count','sum'] and a['actual'] is not None and parent['actual'] is not None else None;results.append(a)
        additive=self.kind in ['count','sum'];known=[r['actual'] for r in results if r['actual'] is not None]
        share_ok=bool(additive and parent['actual'] is not None and parent['actual']>0 and parent['missing_rows']==0 and len(known)==len(results) and all(v>=0 for v in known))
        for r in results:r['share_pct']=r['actual']/parent['actual']*100 if share_ok else None
        if sort=='label':results.sort(key=lambda r:(r['label'],r['token']))
        elif sort=='samples':results.sort(key=lambda r:(-r['source_rows'],r['label'],r['token']))
        else:results.sort(key=lambda r:(r['actual'] is None,(r['actual'] or 0)*(-1 if sort=='desc' else 1),r['label'],r['token']))
        if sum(r['source_rows'] for r in results)!=len(rows):raise ValueError('分组来源未能守恒，请核对')
        additive_sum=sum(known) if known else None
        reconciles=additive and ((parent['actual'] is None and additive_sum is None) or (parent['actual'] is not None and additive_sum is not None and abs(parent['actual']-additive_sum)<=max(1e-8,abs(parent['actual'])*1e-12)))
        if additive and not reconciles:raise ValueError('分组加总与同范围实际不一致，暂停展示')
        explanation={'count':'互斥分组的记录数可相加。','sum':'互斥分组的数值总量可相加；有空缺时只代表有效部分。','ratio':'总比率按全范围分子合计÷分母合计计算；不能平均各组百分比。','avg':'总体均值从全部有效记录重算，不能等权平均各组均值。','median':'总体中位数从全部有效记录排序重算，不平均各组中位数。','percentile':'总体分位数从全部有效记录排序重算，不平均各组分位数。','distinct':'同一对象可能跨组出现，分组去重数不能直接相加。','min':'总体最小值从全范围有效记录重算。','max':'总体最大值从全范围有效记录重算。','derived':'派生公式在每组分别执行；总体从全范围基础度量重算，不推定可加总。'}[self.kind]
        filters=[]
        ops={'eq':'等于','ne':'不等于','contains':'包含','gte':'不早于 / 不小于','lte':'不晚于 / 不大于'}
        for f in self.definition.get('filters',[]):filters.append({'field':self.fields[f['field']]['label'],'operator':ops[f['op']],'value':f.get('value')})
        return dict(target=k.safe(self.target),total=total,parent=parent,axis=axis,path=path,breadcrumbs=breadcrumbs,options=options,sort=sort,rows=results,groups=len(results),source_conserved=True,additive=additive,additive_sum=additive_sum,reconciles=reconciles,share_available=share_ok,kind=self.kind,explanation=explanation,note=NOTICE,filters=filters,difference_unit='百分点' if self.target['unit']=='%' else self.target['unit'],context_note='产品族按唯一配置档案关联；缺失关系单列，未按型号或日期猜测。' if self.family_mode else '',can_drill=len(path)<3)

    def evidence(self,p):
        rows,breadcrumbs,options,axis,grouped,sort,path=self.prepare(p);token=p.get('group')
        if not isinstance(token,str) or token not in grouped:raise ValueError('所选分组已不存在或不属于当前范围')
        return grouped[token]['rows'],axis,breadcrumbs,grouped[token]['label']

    def source_refs(self,row,p,axis):
        refs=row.get('_sources') or [{'dataset':self.dataset,'key':row['id']}]
        used=[axis['dimension'],*[x['dimension'] for x in parse_path(p.get('path','[]'))]]
        if 'product.family' in used:refs=[*refs,*self.context(row)[2]]
        return [dict(dataset=ds,key=key) for ds,key in sorted({(r['dataset'],r['key']) for r in refs if access.allowed(self.user,r['dataset'])})]
