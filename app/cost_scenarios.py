"""Fixed-quantity cost sensitivity. No capacity, profit or accounting-posting inference."""
import hashlib,json,uuid
from pathlib import Path
from collections import defaultdict,Counter
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from datetime import date
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from . import access,analytics
from .models import CostScenario,Record,AuditEvent
from .topic_workspace import digest,clean_text
from .import_review import ReviewConflict

MODEL='固定数量成本重估 v1'
NOTICE='这是对同一批工单活动的假设重估：产品配置、装配量、材料用量、工时和用工结构保持不变。材料按领料行×参考单价重估；直接人工及制造费用按原归集行同比调整；返工增耗保持原额。不改实际成本，不预测产能、采购现金流或毛利。'
COST_TYPES=('材料','直接人工','制造费用','返工增耗')
MAX_AMOUNT=900000000000000

def require(user):
    if not access.can_money(user):raise PermissionDenied('成本情景仅对有财务数据权限的账号开放')
def calculation_hash():return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
def amount(v):return int(v.quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def number(v,label,integer=False,positive=False):
    if type(v) not in [int,float,str,Decimal] or isinstance(v,str) and len(v)>60:raise ValidationError(label+'不是有效数值')
    try:n=Decimal(str(v))
    except InvalidOperation:raise ValidationError(label+'不是有效数值')
    if not n.is_finite() or n<0 or n>MAX_AMOUNT or positive and n==0 or integer and n!=n.to_integral_value():raise ValidationError(label+'数值或单位不合法')
    return n
def scope(data):
    if not isinstance(data,dict) or set(data)-{'family','product_id','from','to'}:raise ValidationError('范围仅支持产品族、配置和计划完工日期')
    result={}
    for key,value in data.items():
        if not isinstance(value,str) or not 1<=len(value)<=80:raise ValidationError('范围字段格式无效')
        if key in ['from','to'] and date.fromisoformat(value).isoformat()!=value:raise ValidationError('日期必须为YYYY-MM-DD')
        result[key]=value
    if result.get('from') and result.get('to') and result['from']>result['to']:raise ValidationError('开始日期不能晚于结束日期')
    return result

def sources(user,wanted):
    out={}
    for ds,keys in sorted(wanted.items()):
        if not access.allowed(user,ds):raise PermissionDenied('缺少情景来源权限')
        keys=sorted(keys);permitted={f['name'] for f in access.permitted_fields(user,ds)}
        for start in range(0,len(keys),400):
            for r in Record.objects.filter(dataset=ds,business_key__in=keys[start:start+400]).select_related('source_row__batch'):
                row=r.source_row;b=row.batch
                out[digest([ds,r.business_key])]={'dataset':ds,'key':r.business_key,'values':{k:v for k,v in r.values.items() if k in permitted},'revision':r.revision,'record_hash':r.record_hash,
                    'batch_id':str(b.pk),'filename':b.filename,'file_hash':b.file_hash,'sheet':row.sheet,'row':row.row_number}
        if any(digest([ds,key]) not in out for key in keys):raise ValidationError('情景来源记录缺失，请核对导入')
    if len(out)>25000:raise ValidationError('情景来源超过25000行，请缩小范围')
    return out

@transaction.atomic
def current_baseline(user,raw_scope):
    require(user);s=scope(raw_scope);revision=analytics.revision();d=analytics.tables()
    products={p['id']:p for p in d['products']};materials={m['id']:m for m in d['materials']}
    families=sorted({p['family'] for p in products.values()});categories=sorted({m['category'] for m in materials.values()})
    if s.get('family') and s['family'] not in families:raise ValidationError('产品族不存在，未回退为全部')
    if s.get('product_id') and s['product_id'] not in products:raise ValidationError('配置不存在，未回退为全部')
    if s.get('family') and s.get('product_id') and products[s['product_id']]['family']!=s['family']:raise ValidationError('配置不属于所选产品族')
    selected=[w for w in d['work_orders'] if (not s.get('family') or products.get(w['product_id'],{}).get('family')==s['family']) and (not s.get('product_id') or w['product_id']==s['product_id']) and (not s.get('from') or w['planned_end']>=s['from']) and (not s.get('to') or w['planned_end']<=s['to'])]
    if len(selected)>1000:raise ValidationError('本轮模型最多1000个工单，请缩小范围')
    units=defaultdict(list);costs=defaultdict(list);moves=defaultdict(list)
    for u in d['units']:
        if u['assembly_at']<=analytics.AS_OF:units[u['work_order_id']].append(u)
    for c in d['costs']:
        if c['occurred']<=analytics.DAY:costs[c['work_order_id']].append(c)
    for m in d['inventory_movements']:
        if m.get('work_order_id') and m['occurred']<=analytics.AS_OF:moves[m['work_order_id']].append(m)
    wanted=defaultdict(set);rows=[];problems=[];statuses=Counter()
    for w in sorted(selected,key=lambda r:r['id']):
        key=w['id'];p=products.get(w['product_id']);errors=[];refs=defaultdict(set);refs['work_orders'].add(key)
        if p:refs['products'].add(p['id'])
        else:errors.append('配置档案缺失')
        row={'id':key,'product_id':w['product_id'],'family':p['family'] if p else '未知','planned_end':w['planned_end'],'produced_qty':len(units[key]),'materials':[],'costs':[],
             'base_cents':0,'components':{c:0 for c in COST_TYPES},'eligible':False,'errors':errors}
        for u in units[key]:
            refs['units'].add(u['id'])
            if u['product_id']!=w['product_id']:errors.append('整机配置与工单不一致')
        for c in costs[key]:
            refs['costs'].add(c['id']);statuses[c['status']]+=1
            try:
                n=int(number(c['amount_cents'],'成本金额',integer=True));row['base_cents']+=n
                if c['category'] not in COST_TYPES:errors.append('成本类别未定义：'+str(c['category']))
                else:row['components'][c['category']]+=n
                row['costs'].append({'id':c['id'],'category':c['category'],'amount_cents':n,'status':c['status'],'basis':c['basis']})
            except ValidationError as ex:errors.extend(ex.messages)
        for m in moves[key]:
            refs['inventory_movements'].add(m['id']);material=materials.get(m['material_id'])
            if not material:errors.append('领料物料档案缺失');continue
            refs['materials'].add(material['id'])
            try:
                if m['movement']!='生产领料':raise ValidationError('当前模型不支持关联的库存业务：'+str(m['movement']))
                qty=number(-Decimal(str(m['qty_signed'])),'领料数量',integer=material['unit']=='件',positive=True)
                if material['unit'] not in ['kg','件']:raise ValidationError('材料单位未适配：'+str(material['unit']))
                price=number(material['unit_cost_cents'],'参考单价',integer=True,positive=True)
                row['materials'].append({'id':m['id'],'material_id':material['id'],'material':material['name'],'category':material['category'],'unit':material['unit'],'qty':str(qty),
                    'unit_cost_cents':int(price),'base_cents':amount(qty*price)})
            except (ValidationError,InvalidOperation) as ex:errors.extend(ex.messages if isinstance(ex,ValidationError) else ['领料数量格式无效'])
        row['material_recomputed_cents']=sum(m['base_cents'] for m in row['materials'])
        has_activity=bool(units[key] or costs[key] or moves[key])
        if has_activity:
            if row['produced_qty']==0:errors.append('已有投入或成本但没有装配台数，不能计算固定产量情景')
            if set(c['category'] for c in row['costs'])!=set(COST_TYPES):errors.append('四类成本归集不完整，缺失不能当作零')
            if row['material_recomputed_cents']!=row['components']['材料']:errors.append('领料参考金额与材料归集金额不一致')
            if row['produced_qty'] and not row['materials']:errors.append('已有产出但缺少领料明细')
        row['eligible']=has_activity and not errors;row['excluded_reason']='尚无装配、领料或成本，不推算未来工单' if not has_activity and not errors else ''
        row['source_keys']=[digest([ds,k]) for ds,keys in refs.items() for k in sorted(keys)]
        for ds,keys in refs.items():wanted[ds].update(keys)
        problems.extend({'work_order_id':key,'message':message} for message in dict.fromkeys(errors));rows.append(row)
    base={'model':MODEL,'calculation_hash':calculation_hash(),'as_of':analytics.AS_OF,'facts_token':digest(revision),'scope':s,'categories':categories,'rows':rows,'problems':problems,
          'statuses':dict(statuses),'sources':sources(user,wanted),'notice':NOTICE}
    if revision!=analytics.revision():raise ReviewConflict('基线读取期间数据变化，请重新加载')
    if sum(r['base_cents'] for r in rows)>MAX_AMOUNT:raise ValidationError('金额超过演示模型的数值范围')
    return base

def get(user,scenario_id):
    require(user);r=CostScenario.objects.get(pk=scenario_id,owner=user)
    receipt={'name':r.name,'note':r.note,'owner_id':r.owner_id,'parent_id':str(r.parent_id) if r.parent_id else None,'request_id':str(r.request_id)}
    if digest(r.payload)!=r.payload_hash or r.payload.get('receipt')!=receipt:raise ReviewConflict('情景完整性核验失败，请检查备份')
    fields=defaultdict(set)
    for source in r.payload['baseline']['sources'].values():fields[source['dataset']].update(source['values'])
    for ds,names in fields.items():
        if not access.allowed(user,ds) or not names<={f['name'] for f in access.permitted_fields(user,ds)}:raise PermissionDenied('当前身份不再具备已保存来源权限')
    return r

def baseline(user,data):
    if set(data)!={'scope','parent_id'}:raise ValidationError('基线请求参数无效')
    require(user)
    if data['parent_id'] is not None:
        old=get(user,uuid.UUID(str(data['parent_id']))).payload['baseline']
        if scope(data['scope'])!=old['scope']:raise ValidationError('沿用保存基线时不能更改范围；请另取当前基线')
        if old['calculation_hash']!=calculation_hash():raise ReviewConflict('计算模型已改版，原情景仍可查看；请重新核对当前基线')
        return old
    return current_baseline(user,data['scope'])

def public_baseline(b):
    ready=[r for r in b['rows'] if r['eligible']]
    return {k:v for k,v in b.items() if k not in ['sources','rows']}|{'baseline_token':digest(b),'source_count':len(b['sources']),
        'rows':[{k:v for k,v in r.items() if k not in ['materials','costs','source_keys']} for r in b['rows']],
        'totals':{'selected':len(b['rows']),'eligible':len(ready),'excluded':sum(bool(r['excluded_reason']) for r in b['rows']),'produced_qty':sum(r['produced_qty'] for r in ready),'base_cents':sum(r['base_cents'] for r in ready)}}

def assumptions(data,categories):
    if not isinstance(data,list) or len(data)!=2:raise ValidationError('请提供A/B两组假设')
    result=[]
    for case in data:
        if not isinstance(case,dict) or set(case)!={'name','material_rates','labor_rate','overhead_rate'} or not isinstance(case['material_rates'],dict) or set(case['material_rates'])!=set(categories):raise ValidationError('假设字段或材料类别不完整')
        def rate(v):
            if not isinstance(v,str) or len(v)>20:raise ValidationError('变化率须为数字文本')
            try:n=Decimal(v)
            except InvalidOperation:raise ValidationError('变化率须为有效数字')
            if not n.is_finite() or not Decimal('-80')<=n<=Decimal('200') or n!=n.quantize(Decimal('.01')):raise ValidationError('变化率允许−80%至200%，最多两位小数')
            return str(n.quantize(Decimal('.01')))
        result.append({'name':clean_text(case['name'],'情景名称',30),'material_rates':{k:rate(v) for k,v in sorted(case['material_rates'].items())},'labor_rate':rate(case['labor_rate']),'overhead_rate':rate(case['overhead_rate'])})
    if result[0]['name']==result[1]['name']:raise ValidationError('A/B情景名称应不同')
    return result

def simulate(b,cases):
    if b['problems']:raise ValidationError('基线存在待核对项目，请先处理，未自动忽略异常工单')
    ready=[r for r in b['rows'] if r['eligible']]
    if not ready:raise ValidationError('当前范围没有具备完整投入与产出的工单')
    outputs=[]
    for case in cases:
        rows=[];bridge=defaultdict(lambda:{'base_cents':0,'scenario_cents':0})
        for r in ready:
            contributions=defaultdict(lambda:[0,0]);material_lines=[]
            for m in r['materials']:
                simulated=amount(Decimal(m['qty'])*m['unit_cost_cents']*(1+Decimal(case['material_rates'][m['category']])/100))
                label='材料 · '+m['category'];contributions[label][0]+=m['base_cents'];contributions[label][1]+=simulated
                material_lines.append({'id':m['id'],'baseline_cents':m['base_cents'],'scenario_cents':simulated,'delta_cents':simulated-m['base_cents']})
            for c in r['costs']:
                if c['category']=='材料':continue
                rate=case['labor_rate'] if c['category']=='直接人工' else case['overhead_rate'] if c['category']=='制造费用' else '0'
                contributions[c['category']][0]+=c['amount_cents'];contributions[c['category']][1]+=amount(Decimal(c['amount_cents'])*(1+Decimal(rate)/100))
            total=sum(v[1] for v in contributions.values());assert sum(v[0] for v in contributions.values())==r['base_cents']
            row={'id':r['id'],'product_id':r['product_id'],'family':r['family'],'produced_qty':r['produced_qty'],'baseline_cents':r['base_cents'],'scenario_cents':total,'delta_cents':total-r['base_cents'],
                 'baseline_unit_yuan':float(Decimal(r['base_cents'])/100/r['produced_qty']),'scenario_unit_yuan':float(Decimal(total)/100/r['produced_qty']),
                 'contributions':[{'label':k,'base_cents':v[0],'scenario_cents':v[1],'delta_cents':v[1]-v[0]} for k,v in sorted(contributions.items())],'material_lines':material_lines}
            for label,values in contributions.items():bridge[label]['base_cents']+=values[0];bridge[label]['scenario_cents']+=values[1]
            rows.append(row)
        total=sum(r['scenario_cents'] for r in rows);base=sum(r['baseline_cents'] for r in rows);qty=sum(r['produced_qty'] for r in rows)
        if total>MAX_AMOUNT:raise ValidationError('情景金额超过可用数值范围')
        by_config=defaultdict(lambda:{'qty':0,'baseline_cents':0,'scenario_cents':0,'orders':0})
        for r in rows:
            x=by_config[r['product_id']];x['qty']+=r['produced_qty'];x['baseline_cents']+=r['baseline_cents'];x['scenario_cents']+=r['scenario_cents'];x['orders']+=1;x['family']=r['family']
        outputs.append({'name':case['name'],'totals':{'baseline_cents':base,'scenario_cents':total,'delta_cents':total-base,'relative_pct':float(Decimal(total-base)/base*100) if base else None,'produced_qty':qty,'baseline_unit_yuan':float(Decimal(base)/100/qty),'scenario_unit_yuan':float(Decimal(total)/100/qty)},
            'bridge':[{'label':label,**v,'delta_cents':v['scenario_cents']-v['base_cents']} for label,v in sorted(bridge.items())],
            'by_config':[{'product_id':key,**v,'baseline_unit_yuan':float(Decimal(v['baseline_cents'])/100/v['qty']),'scenario_unit_yuan':float(Decimal(v['scenario_cents'])/100/v['qty'])} for key,v in sorted(by_config.items())],'rows':rows})
    return outputs

@transaction.atomic
def evaluate(user,data):
    if set(data)!={'scope','parent_id','baseline_token','assumptions'}:raise ValidationError('试算参数不完整')
    b=baseline(user,{k:data[k] for k in ['scope','parent_id']})
    if digest(b)!=data['baseline_token']:raise ReviewConflict('基线数据或计算口径已变化，请重新加载核对')
    cases=assumptions(data['assumptions'],b['categories']);results=simulate(b,cases)
    out={'baseline':b,'assumptions':cases,'results':results,'parent_id':data['parent_id'],'model':MODEL,'notice':NOTICE}
    out['calculation_token']=digest(out)
    return out

def public_run(p):return {**p,'baseline':public_baseline(p['baseline'])}

@transaction.atomic
def save(user,data):
    require(user)
    if set(data)!={'request_id','name','note','input','calculation_token'}:raise ValidationError('保存情景参数无效')
    rid=uuid.UUID(str(data['request_id']));fingerprint=digest(data);existing=CostScenario.objects.filter(request_id=rid).first()
    if existing:
        if existing.owner_id!=user.pk or existing.request_hash!=fingerprint:raise ReviewConflict('申请号已用于不同的情景内容')
        return get(user,existing.pk)
    name=clean_text(data['name'],'保存名称',120);note=clean_text(data['note'],'假设依据',1000)
    if len(note)<5:raise ValidationError('假设依据至少5字')
    if CostScenario.objects.filter(owner=user).count()>=100:raise ValidationError('本地演示每人最多100份情景，请规划归档容量')
    p=evaluate(user,data['input'])
    if data['calculation_token']!=p['calculation_token']:raise ReviewConflict('试算结果已变化，请重新计算并核对后保存')
    parent=uuid.UUID(str(data['input']['parent_id'])) if data['input']['parent_id'] else None
    p['receipt']={'name':name,'note':note,'owner_id':user.pk,'parent_id':str(parent) if parent else None,'request_id':str(rid)}
    if len(json.dumps(p,ensure_ascii=False,allow_nan=False).encode())>20*1024*1024:raise ValidationError('情景证据超过20MB，请缩小范围')
    saved=CostScenario.objects.create(owner=user,parent_id=parent,request_id=rid,request_hash=fingerprint,name=name,note=note,payload=p,payload_hash=digest(p))
    AuditEvent.objects.create(action='cost_scenario.create',actor=user.username,object_type='CostScenario',object_id=str(saved.pk),detail={'name':name,'payload_hash':saved.payload_hash,'parent_id':str(parent) if parent else None,'business_facts_changed':False})
    return saved

def info(r):return {'id':str(r.pk),'name':r.name,'note':r.note,'parent_id':str(r.parent_id) if r.parent_id else None,'created_at':r.created_at,'payload_hash':r.payload_hash}

def options(user):
    require(user);products=analytics.tables()['products']
    return {'families':sorted({p['family'] for p in products}),'products':[{'id':p['id'],'family':p['family'],'model':p['model']} for p in products],
            'saved':[info(r) for r in CostScenario.objects.filter(owner=user).order_by('-created_at')[:100]],'as_of':analytics.AS_OF,'model':MODEL,'notice':NOTICE}

def evidence(user,data,scenario_id=None):
    require(user)
    if scenario_id:
        if set(data)!={'work_order_id','page'}:raise ValidationError('来源参数无效')
        b=get(user,scenario_id).payload['baseline']
    else:
        if set(data)!={'scope','parent_id','baseline_token','work_order_id','page'}:raise ValidationError('来源参数无效')
        b=baseline(user,{k:data[k] for k in ['scope','parent_id']})
        if digest(b)!=data['baseline_token']:raise ReviewConflict('基线已变，请重新加载')
    row=next((r for r in b['rows'] if r['id']==data['work_order_id']),None);page=data['page']
    if row is None or type(page) is not int or not 1<=page<=100000:raise ValidationError('工单或页码无效')
    keys=row['source_keys'];selected=[b['sources'][k] for k in keys[(page-1)*20:page*20]]
    return {'row':row,'sources':selected,'total':len(keys),'page':page,'size':20,'fields':{s['dataset']:access.permitted_fields(user,s['dataset']) for s in selected}}

def csv_rows(r):
    p=r.payload;rows=[['保存名称','情景标识','保存时间','完整性摘要','模型','状态截止','范围','方案','工单','产品配置','产品族','固定装配台数','基线金额分','假设金额分','差额分','基线元每台','假设元每台','假设参数']]
    for case,params in zip(p['results'],p['assumptions']):
        for row in case['rows']:
            rows.append([r.name,str(r.pk),r.created_at.isoformat(),r.payload_hash,p['model'],p['baseline']['as_of'],json.dumps(p['baseline']['scope'],ensure_ascii=False),case['name'],row['id'],row['product_id'],row['family'],row['produced_qty'],row['baseline_cents'],row['scenario_cents'],row['delta_cents'],row['baseline_unit_yuan'],row['scenario_unit_yuan'],json.dumps(params,ensure_ascii=False)])
    return rows
