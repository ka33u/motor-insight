"""Synthetic certificate correspondence, never calibration/quality approval."""
import csv,io,re,uuid,hashlib
from collections import Counter,defaultdict
from . import metrology as reg

TABLES=('metrology_certificates','metrology_certificate_links')
COMPARE=('certificate_no','instrument_id','parameter','unit','performed','valid_from','valid_until','result','laboratory')
HEADERS=list(COMPARE)+['issued','reference']
STATES={'consistent':'关联、声明与原件字段一致','missing_link':'缺当前原件关联','withdrawn':'当前原件关联已撤销',
        'record_attention':'关联或证明台账待核对','file_missing':'缺可核查原件','no_access':'当前账号需原件授权',
        'file_attention':'原件或声明摘要待核对','unparsed':'原件未结构化核对','content_attention':'原件字段不一致',
        'no_calibration':'未能选定当前校准登记','not_required':'模拟要求不需校准','unknown_rule':'适用要求待核对','archive':'仅原工具档案'}
DUE={'due':'登记有效且进入提醒窗口','later':'登记有效且在提醒窗口外','expired':'已到登记失效起点',
     'attention':'校准或身份待核对','failed':'最近登记不符合','withdrawn':'最近校准登记撤销','not_required':'模拟要求不需校准','archive':'仅原工具档案'}
NOTE='全部为合成校准证明与Excel台账。字段一致仅证明当前关联、声明和可读取原件的内容对应，不证明证书真实性、实验室能力、测量不确定度、量程或实际使用适合性，不改变原检测、校准登记、放行或失准处置。'
TIME_NOTE='校准按业务截止，关联完整版本按登记截止；原件字节、元数据和访问权限按本次读取检查。电子归档时间不等于模拟签发或登记时间，不证明历史时点已有此电子原件。提醒窗口为读者选择的自然天数，不是已批准校准周期或停机要求。'

def parse(raw,kind):
    if kind!='csv':return dict(mode='manual',row=None,errors=['此格式尚未结构化核对，请按原件人工核查'])
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:text=raw.decode('gb18030')
        except UnicodeDecodeError:return dict(mode='invalid',row=None,errors=['文本编码不能识别'])
    if '\x00' in text:return dict(mode='invalid',row=None,errors=['文本含二进制空字符'])
    try:
        reader=csv.reader(io.StringIO(text),strict=True);header=next(reader,None)
        if not header or len(set(header))!=len(header) or set(header)!=set(HEADERS):return dict(mode='invalid',row=None,errors=['模拟CSV表头须完整、唯一且无额外列'])
        rows=[]
        for values in reader:
            if values:rows.append(values)
            if len(rows)>1:break
        if len(rows)!=1 or len(rows[0])!=len(header):return dict(mode='invalid',row=None,errors=['一份模拟原件须有且仅有一条通道声明'])
        row={k:v.strip() for k,v in zip(header,rows[0])};errors=[]
        if any(not v or len(v)>240 for v in row.values()):errors.append('原件有空字段或过长字段')
        for k in ['performed','valid_from','valid_until','issued']:
            if not reg.clock(row[k]):errors.append(k+'时间格式无效')
        return dict(mode='invalid' if errors else 'structured',row=row,errors=errors)
    except csv.Error:return dict(mode='invalid',row=None,errors=['CSV结构损坏'])

def resolver(user):
    """Honor the existing private-original policy, including current grant state."""
    from . import file_sharing,device_files
    from .models import DeviceFile
    from .import_review import ReviewConflict
    from django.core.exceptions import PermissionDenied
    cache={}
    def resolve(file_id):
        if file_id in cache:return cache[file_id]
        try:key=uuid.UUID(str(file_id))
        except (ValueError,TypeError,AttributeError):return dict(state='file_attention',issues=['归档原件标识无效'],observation='bad-id')
        if not DeviceFile.objects.filter(pk=key).exists():out=dict(state='file_missing',issues=['此标识尚无归档原件'],observation='missing-record')
        else:
            try:
                f,permit=file_sharing.readable(user,key,check_file=False)
                try:raw=device_files.path(f).read_bytes()
                except OSError:raw=None
                observed=hashlib.sha256(raw).hexdigest() if raw is not None else 'missing-bytes'
                obs=reg.digest([observed,permit,device_files.file_meta(f),f.metadata_hash])
                meta={k:getattr(f,k) for k in ['filename','kind','size','file_hash']};meta['id']=str(f.pk)
                if raw is None:out=dict(state='file_missing',issues=['归档原件字节缺失'],observation=obs,file=meta)
                elif len(raw)!=f.size or observed!=f.file_hash:out=dict(state='file_attention',issues=['原件字节与归档大小或摘要不同'],observation=obs,file=meta)
                else:out=dict(state='verified',issues=[],observation=obs,file=meta,parsed=parse(raw,f.kind))
            except DeviceFile.DoesNotExist:out=dict(state='no_access',issues=['原件需归档账号明确只读授权，当前账号不能核查'],observation='private')
            except PermissionDenied:out=dict(state='no_access',issues=['当前账号已不具备原件核查权限'],observation='account-access-changed')
            except file_sharing.GrantConflict:out=dict(state='no_access',issues=['原件授权依据异常，协作核查暂停'],observation='grant-invalid')
            except ReviewConflict as e:out=dict(state='file_attention',issues=[str(e)],observation='metadata-invalid')
        cache[file_id]=out;return out
    return resolve

class Evidence:
    def __init__(self,registry,data=None,resolve=None,window=30):
        if type(window) is not int or not 1<=window<=365:raise ValueError('提醒窗口须为1至365个自然天')
        self.registry=registry;self.window=window;self.cutoff=registry.cutoff;self.known=registry.known_cutoff
        if data is None:
            from .models import Record
            data={k:[] for k in TABLES}
            for ds,v in Record.objects.filter(dataset__in=TABLES).values_list('dataset','values'):data[ds].append(v)
        self.data=data;self.certificates={r['id']:r for r in data.get(TABLES[0],[])}
        self.resolve=resolve or (lambda _:dict(state='no_access',issues=['没有当前账号读取器'],observation='unresolved'))
        self.groups=reg.resolve_versions(data.get(TABLES[1],[]),self.known,('calibration_id',));self.links=defaultdict(list)
        for g in self.groups:
            for cid in {r.get('calibration_id') for r in g['history']}:self.links[cid].append(g)
        self.inspections={c['id']:self.check(c) for c in registry.data.get('metrology_calibrations',[]) if reg.clock(c.get('registered')) and c['registered']<=self.known}
        self.measurements=defaultdict(list)
        for r in registry.rows:
            if r['instrument_id']:self.measurements[r['instrument_id']].append(r)
        self.rows=[]
        for i in registry.data.get('metrology_instruments',[]):self.rows.append(self.profile(i))
        self.index={r['id']:r for r in self.rows}
    def check(self,cal):
        groups=self.links[cal['id']];issues=[];sources=reg.refs('metrology_calibrations',[cal])+reg.refs('metrology_instruments',[self.registry.idx['metrology_instruments'].get(cal['instrument_id'])]);link=None;certificate=None
        for g in groups:
            issues+=g['issues'];sources+=reg.refs(TABLES[1],g['history'])
            for r in g['history']:sources+=reg.refs(TABLES[0],[self.certificates.get(r.get('certificate_id'))])
        if len(groups)>1:issues.append('同一校准版本存在多个关联系列')
        if len(groups)==1 and not issues:link=groups[0]['selected']
        certificate=self.certificates.get(link.get('certificate_id')) if link else None
        state='record_attention' if issues else 'missing_link' if not link else 'withdrawn' if link['status']=='撤销' else 'consistent'
        if state=='consistent':
            if not certificate:issues.append('选定关联缺证明台账')
            else:
                for k in COMPARE:
                    if certificate.get(k)!=cal.get(k):issues.append(k+'声明与所引校准版本不同')
                if not all(reg.clock(certificate.get(k)) for k in ['performed','valid_from','valid_until','issued']):issues.append('证明声明时间缺失或无效')
                elif not certificate['performed']<=certificate['valid_from']<certificate['valid_until'] or certificate['issued']<certificate['performed'] or certificate['issued']>link['registered'] or certificate['issued']>self.known:issues.append('证明有效区间、签发或关联登记顺序待核对')
                if link['registered']<cal['registered']:issues.append('关联登记早于所引校准版本登记')
                if not certificate.get('reference') or not link.get('reference'):issues.append('关联或声明依据缺失')
                if certificate.get('file_id') and not re.fullmatch('[0-9a-f]{64}',certificate.get('file_sha256') or ''):issues.append('台账声明文件摘要缺失或格式错误')
            if issues:state='record_attention'
        file=None;parsed=None;comparison=[];observation='not-observed';file_state='not_observed';record_problem=state=='record_attention'
        if state in ['consistent','record_attention'] and certificate:
            if not certificate.get('file_id'):state='file_missing';issues.append('证明台账未登记归档原件标识')
            else:
                seen=self.resolve(certificate['file_id']);file_state=seen['state'];observation=seen['observation'];file=seen.get('file');parsed=seen.get('parsed')
                if seen['state']!='verified':state=seen['state'];issues+=seen['issues']
                elif file['file_hash']!=certificate['file_sha256']:state='file_attention';issues.append('台账声明摘要与归档摘要不同')
                elif parsed['mode']=='manual':state='unparsed';issues+=parsed['errors']
                else:
                    issues+=parsed['errors'];original=parsed.get('row')
                    if original:
                        for k in HEADERS:
                            match=original.get(k)==certificate.get(k);comparison.append(dict(field=k,calibration=cal.get(k),declared=certificate.get(k),original=original.get(k),matched=match))
                            if not match:issues.append(k+'原件与证明台账不同')
                    if issues:state='content_attention'
        if record_problem:state='record_attention'
        return dict(calibration_id=cal['id'],link_id=link['id'] if link else None,certificate_id=certificate['id'] if certificate else None,state=state,state_label=STATES[state],
                    issues=list(dict.fromkeys(issues)),file=file,file_state=file_state,file_observation=observation,parsed=parsed,comparison=comparison,certificate=certificate,
                    history=groups,sources=reg.unique_sources(sources))
    def profile(self,i):
        required=None;cal=None;due='archive';hours=None;current=None
        if i['stage']=='档案':state='archive';issues=[];sources=reg.refs('metrology_instruments',[i]);cal_state='unknown_rule'
        else:
            rule=self.registry.rule(i['stage'],i['parameter'],i['unit'],self.cutoff);required=rule['required'];current=self.registry.calibration(i,self.cutoff,required);cal=current['selected'];cal_state=current['state'];issues=list(rule['issues']+current['issues'])
            state='not_required' if required is False else 'unknown_rule' if required is None else 'no_calibration' if not cal else self.inspections[cal['id']]['state']
            due='not_required' if required is False else {'expired':'expired','failed':'failed','withdrawn':'withdrawn'}.get(cal_state,'attention')
            if cal and reg.clock(cal.get('valid_until')):hours=round((reg.clock(cal['valid_until'])-reg.clock(self.cutoff)).total_seconds()/3600,3)
            if cal_state=='valid':due='due' if hours<=self.window*24 else 'later'
            sources=reg.refs('metrology_instruments',[i])+rule['sources']+current['sources']
            if cal:
                check=self.inspections[cal['id']];sources+=check['sources'];issues+=check['issues']
        return dict(id=i['id'],instrument=i,required=required,calibration=cal,calibration_state=cal_state,calibration_label=reg.CAL_STATES[cal_state],
                    evidence_state=state,evidence_label=STATES[state],due_state=due,due_label=DUE[due],hours_to_expiry=hours,
                    reading_summary=reg.summary(self.measurements.get(i['id'],[])),issues=list(dict.fromkeys(issues)),sources=reg.unique_sources(sources))
    def cohort(self,f):
        return [r for r in self.rows if (f.get('archives')=='1' or r['instrument']['stage']!='档案')
                and (not f.get('stage') or r['instrument']['stage']==f['stage']) and (not f.get('instrument_id') or r['id']==f['instrument_id'])
                and (not f.get('q') or f['q'].lower() in ' '.join(str(r['instrument'].get(k) or '') for k in ['id','asset_code','name','parameter','unit','source_alias']).lower())]
    def observations(self):return [(key,r['state'],r['file_observation'],r['file']) for key,r in sorted(self.inspections.items())]
def public(r):return {k:v for k,v in r.items() if k!='sources'}
def summary(rows):
    return dict(objects=len(rows),required=sum(r['required'] is True for r in rows),not_required=sum(r['required'] is False for r in rows),
                unknown_requirement=sum(r['required'] is None and r['instrument']['stage']!='档案' for r in rows),
                archives=sum(r['instrument']['stage']=='档案' for r in rows),evidence_counts=dict(Counter(r['evidence_state'] for r in rows)),due_counts=dict(Counter(r['due_state'] for r in rows)))
