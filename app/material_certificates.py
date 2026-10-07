"""Receipt/certificate evidence. File consistency is never material approval."""
import csv,io,hashlib,uuid,re
from collections import Counter,defaultdict
from datetime import date,datetime
from decimal import Decimal,InvalidOperation
from math import isfinite
from pathlib import Path
from django.core.exceptions import ObjectDoesNotExist
from . import analytics,supply,device_files
from .import_review import ReviewConflict
from .topic_workspace import digest

TABLES=['material_certificates','material_certificate_properties','receipt_certificate_links']
HEADERS=['certificate_no','supplier_id','material_id','supplier_lot','issued','property_id','parameter','value','unit','method','reference']
STATES={'all':'全部到货','missing_link':'缺当前关联','withdrawn':'当前已撤销','record_attention':'关联或台账待核对','file_missing':'缺归档原件','no_access':'原件需授权核查','file_attention':'原件完整性异常','unparsed':'原件未结构化核对','content_attention':'原件内容不一致','consistent':'关联与原件内容一致'}
NOTE='全部合成模拟。到货日期选择业务队列，关联和签发日期按业务截止核查；原件可访问性与完整性按本次读取检查。关联台账、供方声明、原件内容一致和原来料批准分别保留。'
BOUNDARY='只支持本平台定义的模拟标准CSV逐字段核对；其他文件保留原件，须人工核查。原件一致不证明供应商签章真实、检测方法有效、整批合格或可批准入库。供方声明与本厂抽样不混算。最新错误或撤销不回退旧关联，同刻/同版本冲突不自动选择。'
def group(rows,key):
    d=defaultdict(list)
    for r in rows:d[r.get(key)].append(r)
    return d
def clock(v):
    try:
        t=datetime.fromisoformat(v);return t if not t.tzinfo and t.isoformat(timespec='seconds')==v else None
    except (TypeError,ValueError):return None
def day(v):
    try:return date.fromisoformat(v) if date.fromisoformat(v).isoformat()==v else None
    except (TypeError,ValueError):return None
def finite(v):return type(v) in [float,int] and isfinite(v)
def numeric(v):
    try:
        n=Decimal(str(v));return n if n.is_finite() else None
    except (InvalidOperation,ValueError,TypeError):return None
def unique(xs):return list(dict.fromkeys(xs))
def public(row):return {k:v for k,v in row.items() if k not in ['sources','history','certificate','properties','comparison','parsed','inspections']}

def parse(raw,kind):
    if kind!='csv':return dict(mode='manual',rows=[],errors=['此格式未进行结构化核对'])
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:text=raw.decode('gb18030')
        except UnicodeDecodeError:return dict(mode='invalid',rows=[],errors=['文本编码无法识别'])
    if '\x00' in text:return dict(mode='invalid',rows=[],errors=['文本含二进制空字符'])
    rows=[];errors=[]
    try:
        reader=csv.reader(io.StringIO(text),strict=True);header=next(reader,None)
        if not header or len(header)!=len(set(header)) or set(header)!=set(HEADERS):return dict(mode='invalid',rows=[],errors=['标准CSV表头须完整、唯一且无未知列'])
        for line,values in enumerate(reader,2):
            if not values:continue
            if line>1001:return dict(mode='invalid',rows=rows,errors=['单原件最多1000个特性行'])
            if len(values)!=len(header):errors.append(f'原件第{line}行列数不正确');continue
            row={k:v.strip() for k,v in zip(header,values)};row['line']=line;rows.append(row)
            if any(not row[k] or len(row[k])>200 for k in HEADERS):errors.append(f'原件第{line}行有空字段或过长字段')
            if numeric(row['value']) is None:errors.append(f'原件第{line}行实测值无效')
            if not day(row['issued']):errors.append(f'原件第{line}行签发日期无效')
        if not rows:errors.append('原件无特性数据行')
        if any(n>1 for n in Counter(r['property_id'] for r in rows).values()):errors.append('原件特性号重复')
        if any(n>1 for n in Counter(r['parameter'] for r in rows).values()):errors.append('原件同特性重复')
    except csv.Error:errors.append('CSV结构损坏')
    return dict(mode='invalid' if errors else 'structured',rows=rows,errors=unique(errors))

def resolver(user):
    """Owners and explicitly authorized recipients may inspect the original."""
    cache={}
    def resolve(file_id):
        if file_id in cache:return cache[file_id]
        try:key=uuid.UUID(str(file_id))
        except (ValueError,TypeError,AttributeError):return dict(status='file_attention',issues=['归档文件标识无效'],observation='invalid-id')
        # The sharing policy checks current account, grant chain and expiry first.
        from .models import DeviceFile
        from . import file_sharing
        f=DeviceFile.objects.filter(pk=key).first()
        if not f:out=dict(status='file_missing',issues=['此标识尚无归档原件'],observation='missing-record')
        else:
            try:
                try:f,permit=file_sharing.readable(user,key,check_file=False)
                except DeviceFile.DoesNotExist:
                    out=dict(status='no_access',issues=['原件归档在其他账号工作区，需该账号明确授权核查'],observation='private')
                    cache[file_id]=out;return out
                except file_sharing.GrantConflict:
                    out=dict(status='no_access',issues=['原件授权依据完整性异常，协作核查暂停'],observation='grant-integrity-error')
                    cache[file_id]=out;return out
                try:raw=device_files.path(f).read_bytes()
                except OSError:raw=None
                observed=hashlib.sha256(raw).hexdigest() if raw is not None else 'missing-bytes'
                meta={k:getattr(f,k) for k in ['filename','kind','size','file_hash']};meta['id']=str(f.pk)
                access_observation=digest([observed,permit])
                if raw is None:out=dict(status='file_missing',issues=['归档原件字节缺失'],observation=access_observation,file=meta)
                elif len(raw)!=f.size or observed!=f.file_hash:out=dict(status='file_attention',issues=['原件大小或摘要与归档记录不同'],observation=access_observation,file=meta)
                else:out=dict(status='verified',issues=[],observation=access_observation,file=meta,parsed=parse(raw,f.kind))
            except ReviewConflict as exc:out=dict(status='file_attention',issues=[str(exc)],observation='metadata-integrity-error')
        cache[file_id]=out;return out
    return resolve

class Certificates:
    def __init__(self,data=None,resolve=None,cutoff=None):
        self.data=data if data is not None else analytics.tables();self.cutoff=cutoff or analytics.AS_OF
        self.resolve=resolve or (lambda key:dict(status='file_missing',issues=['未提供当前账号原件读取器'],observation='unresolved'))
        self.idx={ds:supply.ix(self.data.get(ds,[])) for ds in TABLES+['receipts','purchase_lines','materials','suppliers','employees']}
        self.links=group(self.data.get('receipt_certificate_links',[]),'receipt_id');self.properties=group(self.data.get('material_certificate_properties',[]),'certificate_id')
        self.inspections=group(self.data.get('incoming_inspections',[]),'receipt_id')
        self.rows=[self.build(r) for r in self.data['receipts'] if r['received']<=self.cutoff];self.index=supply.ix(self.rows)
        self.global_issues=[]
        for ds,parent,key in [('receipt_certificate_links','receipts','receipt_id'),('receipt_certificate_links','material_certificates','certificate_id'),('material_certificate_properties','material_certificates','certificate_id')]:
            self.global_issues.extend(dict(dataset=ds,id=r['id'],message='缺少'+parent+'引用') for r in self.data.get(ds,[]) if r.get(key) not in self.idx[parent])
    def build(self,r):
        po=self.idx['purchase_lines'].get(r['purchase_line_id'],{});m=self.idx['materials'].get(r['material_id'],{});s=self.idx['suppliers'].get(po.get('supplier_id'),{})
        history=self.links[r['id']];eligible=[v for v in history if not clock(v.get('recorded')) or v['recorded']<=self.cutoff];issues=[];link=None
        if not all([po,m,s]) or po.get('material_id')!=r['material_id']:issues.append('采购、物料或供应商关系缺失或不一致')
        if any(not clock(v.get('recorded')) for v in eligible):issues.append('关联登记时间无法排序')
        if any(n>1 for n in Counter(v.get('recorded') for v in eligible).values()):issues.append('关联登记同刻并列，无法选定当前关联')
        if any(n>1 for n in Counter(v.get('version') for v in eligible).values()):issues.append('关联版本重复')
        if eligible and not issues:link=sorted(eligible,key=lambda v:(v['recorded'],v['id']))[-1]
        ordered=sorted(eligible,key=lambda v:(str(v.get('recorded') or ''),v['id']))
        for i,v in enumerate(ordered):
            if type(v.get('version')) is not int or v['version']!=i+1 or v.get('previous_id')!=(ordered[i-1]['id'] if i else None):issues.append(v['id']+'版本、前序或时间顺序不一致')
        sources=supply.refs('receipts',[r])+supply.refs('purchase_lines',[po] if po else [])+supply.refs('materials',[m] if m else [])+supply.refs('suppliers',[s] if s else [])+supply.refs('receipt_certificate_links',history)
        for v in history:
            c=self.idx['material_certificates'].get(v.get('certificate_id'))
            if c:sources+=supply.refs('material_certificates',[c])+supply.refs('material_certificate_properties',self.properties[c['id']])
            if v.get('owner_id') in self.idx['employees']:sources+=supply.refs('employees',[self.idx['employees'][v['owner_id']]])
        inspections=[q for q in self.inspections[r['id']] if q['inspected']<=self.cutoff]
        sources+=supply.refs('incoming_inspections',inspections)
        c=self.idx['material_certificates'].get(link.get('certificate_id')) if link else None;props=self.properties[c['id']] if c else [];file_status=None;file=None;parsed=None;comparison=[];observation='no-file-evaluation'
        if link:
            if link.get('status') not in ['登记关联','撤销关联'] or link.get('owner_id') not in self.idx['employees'] or not all(link.get(k) for k in ['reference','note']):issues.append(link['id']+'登记状态、责任或依据无效')
            if link['recorded']<r['received']:issues.append('关联登记早于到货，需核对')
            if link['lot']!=r['lot']:issues.append('关联厂内批次与到货批次不同')
            if not c:issues.append('关联证明台账缺失')
            else:
                if c['number']!=r['certificate']:issues.append('证明号与原到货登记不同')
                if c['material_id']!=r['material_id'] or c['supplier_id']!=po.get('supplier_id'):issues.append('证明物料或供应商与实物来源不同')
                if c['supplier_lot']!=link['supplier_lot']:issues.append('供方批次映射与证明不同')
                if not day(c.get('issued')) or c['issued']>r['received'][:10] or c['issued']>self.cutoff[:10]:issues.append('签发日期晚于到货或业务截止，需核对')
                if not all(c.get(k) for k in ['number','supplier_lot','document_type','basis']):issues.append('证明基本资料不完整')
                if type(c.get('property_count')) is not int or not 1<=c['property_count']<=1000 or c['property_count']!=len(props):issues.append('声明特性行数与台账明细不同')
                if any(n>1 for n in Counter(v.get('parameter') for v in props).values()):issues.append('声明特性编码重复')
                for v in props:
                    if not finite(v.get('value')) or not all(v.get(k) for k in ['parameter','name','unit','method','reference']):issues.append(v['id']+'特性资料缺失或数值无效')
                if c.get('file_id') and not re.fullmatch(r'[0-9a-f]{64}',c.get('file_sha256') or ''):issues.append('已声明文件标识但文件摘要无效或缺失')
        state='record_attention' if issues else 'missing_link' if not link else 'withdrawn' if link['status']=='撤销关联' else 'file_missing' if not c.get('file_id') else 'consistent'
        if state=='consistent':
            resolved=self.resolve(c['file_id']);file_status=resolved['status'];file=resolved.get('file');observation=resolved.get('observation','');parsed=resolved.get('parsed')
            if file_status!='verified':state=file_status;issues+=resolved['issues']
            elif file['file_hash']!=c['file_sha256']:state='file_attention';issues.append('台账声明摘要与归档摘要不同')
            elif parsed['mode']=='manual':state='unparsed';issues+=parsed['errors']
            else:
                problems=list(parsed['errors']);rows=parsed['rows'];pi={p['id']:p for p in props};meta={'certificate_no':c['number'],'supplier_id':c['supplier_id'],'material_id':c['material_id'],'supplier_lot':c['supplier_lot'],'issued':c['issued']}
                if len(rows)!=len(props) or {v['property_id'] for v in rows}!=set(pi):problems.append('原件特性行与声明明细不齐或有额外项')
                for row in rows:
                    pp=pi.get(row['property_id']);bad=[k+'与声明不同' for k,value in meta.items() if row.get(k)!=value]
                    if not pp:bad.append('原件特性号不在声明中')
                    else:
                        bad += [k+'与声明不同' for k in ['parameter','unit','method','reference'] if row.get(k)!=pp[k]]
                        if numeric(row.get('value'))!=numeric(pp['value']):bad.append('实测值与声明不同')
                    comparison.append(dict(line=row['line'],property_id=row['property_id'],declared=pp,original=row,issues=bad))
                    problems += ['原件第'+str(row['line'])+'行：'+x for x in bad]
                if problems:state='content_attention';issues+=problems
        return dict(id=r['id'],received=r['received'],lot=r['lot'],purchase_line_id=po.get('id'),material_id=m.get('id'),material=m.get('name','档案缺失'),category=m.get('category','未知'),supplier_id=s.get('id'),supplier=s.get('name','档案缺失'),qty=r['qty'],unit=m.get('unit'),raw_certificate_number=r['certificate'],raw_receipt_status=r['status'],link_id=link['id'] if link else None,certificate_id=c['id'] if c else None,certificate_number=c['number'] if c else None,supplier_lot=c['supplier_lot'] if c else None,issued=c['issued'] if c else None,state=state,state_label=STATES[state],issues=unique(issues),link_versions=len(eligible),future_links=len(history)-len(eligible),file_status=file_status,file=file,file_observation=observation,parsed=parsed,history=history,certificate=c,properties=props,comparison=comparison,inspections=inspections,sources=supply.unique_refs(sources))
    def cohort(self,f):return [r for r in self.rows if all(not f.get(k) or r[k]==f[k] for k in ['category','material_id','supplier_id']) and (not f.get('received_from') or r['received'][:10]>=f['received_from']) and (not f.get('received_to') or r['received'][:10]<=f['received_to']) and (not f.get('q') or f['q'].lower() in ' '.join(str(r.get(k) or '') for k in ['id','lot','purchase_line_id','material_id','material','supplier','raw_certificate_number','certificate_number','supplier_lot']).lower())]
def summary(rows):return dict(objects=len(rows),with_current_link=sum(bool(r['link_id']) for r in rows),consistent=sum(r['state']=='consistent' for r in rows),**{k:sum(r['state']==k for r in rows) for k in STATES if k not in ['all','consistent']})
