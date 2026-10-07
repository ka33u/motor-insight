"""POST scopes stay out of URLs; signed current snapshot for source/detail/export."""
import csv
import hashlib
import io
import json
from pathlib import Path
from django.core import signing
from django.db import transaction
from . import curing, curing_data, spc_data, access
from .curing_schema import DATASETS
from .models import AuditEvent, Record
from .views import api, body, reply, require
from .import_review import ReviewConflict

SALT='motor.curing.current.v1';MAX_AGE=600


def account(user):
    value=spc_data.account(user)
    for ds in (*DATASETS,'products','work_orders','operations','batches','production_resources','equipment','routes','allocations','order_lines'):
        require(access.allowed(user,ds),'岗位不能读取当前固化采集')
    return value


def params(request, extra=()):
    if request.GET:raise ValueError('固化筛选须通过JSON正文提交')
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise ValueError('固化JSON字段重复：'+k)
            d[k]=v
        return d
    try:json.loads(request.body or b'{}',object_pairs_hook=unique)
    except (UnicodeDecodeError,json.JSONDecodeError):raise ValueError('固化请求须为JSON对象')
    data=body(request)
    if set(data)-{'scope','receipt',*extra}:raise ValueError('固化请求字段无效')
    return data


def stamp(d,user,scope):
    return dict(source_hash=d['source_hash'],rule_hash=d['rule_hash'],result_hash=curing.digest(d['result']),
                account=account(user),scope=scope,view_hash=hashlib.sha256(Path(__file__).read_bytes()+Path(curing_data.__file__).read_bytes()).hexdigest())


def context(request,data,required=False):
    account(request.user);scope=curing.filters(data.get('scope',{}));d=curing_data.load();value=stamp(d,request.user,scope)
    given=data.get('receipt')
    if required and not given:raise ValueError('请先读取同范围固化结果，再查看明细、来源或导出')
    if given:
        if not isinstance(given,str) or len(given)>4096:raise ValueError('固化凭据无效')
        try:actual=signing.loads(given,salt=SALT,max_age=MAX_AGE)
        except signing.BadSignature:raise ReviewConflict('固化凭据无效或过期，请重新读取')
        if actual!=value:raise ReviewConflict('采集、来源、条件、范围或账号已变化，请重新读取')
    d.update(stamp=value,receipt=given or signing.dumps(value,salt=SALT,compress=True),selected=curing.scoped(d['result'],scope))
    return d


def finish(d,user):
    if stamp(d,user,d['stamp']['scope'])!=d['stamp'] or curing.rule_hash()!=d['rule_hash']:raise ReviewConflict('读取期间依据或账号变化，请重新读取')


def response(value):
    result=reply(value);result['Cache-Control']='no-store';return result


def page(data):
    p=data.get('page',1)
    if not isinstance(p,int) or isinstance(p,bool) or not 1<=p<=10000:raise ValueError('页码须为1至10000整数')
    return p


@api(('POST',))
@transaction.atomic
def board(request):
    data=params(request,('page',));p=page(data);d=context(request,data);r=d['selected'];rows=r['rows']
    cards=[dict(run=v['run'],state=v['state'],label=v['label'],issues=v['issues'],missing=v['missing'],loads=v['loads'],sample_rows=v['sample_rows']) for v in rows[(p-1)*25:p*25]]
    finish(d,request.user)
    return response(dict(**{k:v for k,v in r.items() if k!='rows'},rows=cards,total=len(rows),page=p,size=25,
                         receipt=d['receipt'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],receipt_seconds=MAX_AGE,
                         options=dict(resources=sorted({r['resource_id'] for r in d['tables']['cure_runs']}),products=sorted(d['refs']['products'])),
                         source_count=len(d['sources'])))


@api(('POST',))
@transaction.atomic
def detail(request,key):
    data=params(request,('page',));p=page(data);d=context(request,data,True)
    row=next((r for r in d['selected']['rows'] if r['run']['id']==key),None)
    if row is None:raise Record.DoesNotExist()
    samples=sorted([r for r in d['tables']['cure_samples'] if r['run_id']==key],key=lambda r:(r['channel_code'],r['sequence'],r['id']))
    # Charts contain all bounded points; the exact input table has independent paging.
    finish(d,request.user)
    return response(dict(row=row,samples=samples[(p-1)*40:p*40],total=len(samples),page=p,size=40,
                         sources=[s for s in d['sources'] if s['dataset']=='cure_samples' and s['key'] in {r['id'] for r in samples[(p-1)*40:p*40]}],
                         receipt=d['receipt'],notice=curing.NOTICE,can_download_original=access.can_import(request.user)))


@api(('POST',))
@transaction.atomic
def sources(request):
    data=params(request,('page',));p=page(data);d=context(request,data,True);finish(d,request.user)
    return response(dict(rows=d['sources'][(p-1)*40:p*40],total=len(d['sources']),page=p,size=40,receipt=d['receipt'],
                         can_download_original=access.can_import(request.user),notice='全局核对来源包括筛选外炉次及规范，以保留重叠和版本歧义核对；结果与导出只列所选炉次。'))


@api(('POST',))
@transaction.atomic
def export(request):
    data=params(request,('format',));fmt=data.get('format','json')
    if fmt not in ('csv','json'):raise ValueError('支持CSV或JSON')
    d=context(request,data,True);r=d['selected']
    keys={v['run']['id'] for v in r['rows']}
    inputs=dict(cure_runs=[v['run'] for v in r['rows']],
                cure_loads=[v for v in d['tables']['cure_loads'] if v['run_id'] in keys],
                cure_samples=[v for v in d['tables']['cure_samples'] if v['run_id'] in keys])
    if fmt=='json':
        doc=dict(format='motor-curing-current-v1',synthetic=True,result=r,inputs=inputs,sources=d['sources'],source_scope='全局核对来源，结果与原始采集输入仅所选炉次',
                 source_hash=d['source_hash'],rule_hash=d['rule_hash'],notice=curing.NOTICE)
        content=json.dumps(doc,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    else:
        rows=[['MotorInsight 合成固化曲线',r['as_of']],['范围',json.dumps(r['scope'],ensure_ascii=False)],['边界',curing.NOTICE],
              ['来源摘要',d['source_hash'],'规则摘要',d['rule_hash']],['炉次号','设备','资源位','曲线起点','曲线终点','程序','版本','状态','待核对','采样缺口']]
        for item in r['rows']:
            run=item['run'];rows.append([run[k] for k in ('id','equipment_id','resource_id','started','finished','program_code','program_version')]+[item['label'],'；'.join(item['issues']),'；'.join(item['missing'])])
            rows.append(['装载行','批次','报工','工单','配置','本炉件数','位置','对应可信','订单行（工单分配）'])
            for l in item['loads']:rows.append([l[k] for k in ('id','batch_id','operation_id','work_order_id','product_id','qty','position','linked')]+['；'.join(a['order_line_id'] for a in l['orders'])])
            rows.append(['规范','通道','所列条件状态','最长支持连续保温分钟','要求分钟','保温下限℃','保温上限℃','温度上限℃','超温采样号'])
            for c in item['channels']:rows.append([c[k] for k in ('profile_id','channel_code','state','longest_hold_minutes','min_hold_minutes','hold_lsl','hold_usl','max_temp_c')]+['；'.join(c['overtemp_ids'])])
            rows.append(['规范','通道','采样号','序号','采样时间','原始温度','原始单位','采样状态','可画曲线℃'])
            for c in item['channels']:
                for point in c['points']:rows.append([c['profile_id'],c['channel_code']]+[point[k] for k in ('id','sequence','measured','value','unit','quality','value_c')])
        for ds,values in inputs.items():
            rows.append(['完整所选原始采集',ds]);headers=sorted({k for v in values for k in v});rows.append(headers)
            rows.extend([v.get(k) for k in headers] for v in values)
        rows.append(['全局核对来源（包含筛选外重叠与版本依据）','数据集','编号','修订','批次','文件','工作表','行号','记录摘要','原件摘要'])
        rows.extend(['来源']+[s.get(k) for k in ('dataset','key','revision','batch_id','filename','sheet','row','record_hash','file_hash')] for s in d['sources'])
        out=io.StringIO();csv.writer(out).writerows([["'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v for v in row] for row in rows]);content='\ufeff'+out.getvalue()
    finish(d,request.user)
    AuditEvent.objects.create(action='curing.export',actor=request.user.username,object_type='CuringScope',object_id=curing.digest(r['scope'])[:24],
                              detail=dict(format=fmt,runs=r['summary']['runs'],source_hash=d['source_hash'],rule_hash=d['rule_hash'],file_sha256=hashlib.sha256(content.encode()).hexdigest(),business_facts_changed=False))
    return response(dict(filename='固化曲线_'+curing.digest(r['scope'])[:12]+'.'+fmt,format=fmt,text=content))
