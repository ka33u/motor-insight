"""Create actual synthetic CSV originals, archive them, then author Excel inputs.

The archived files are explicit simulation-builder uploads, never human reviews.
Business facts are subsequently imported only from the authored XLSX.
"""
import os,sys,json,csv,io,random,uuid,hashlib,zipfile
from pathlib import Path
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from app import analytics,device_files,material_certificates as eng
from app.schema import SCHEMAS
from app.models import Record,AuditEvent,DeviceFile
assert not Record.objects.filter(dataset__in=eng.TABLES).exists(),'已有证明业务事实，不重新编织'
raw=analytics.tables();rng=random.Random(20261006);tables={key:[] for key in eng.TABLES};cases={};files=[]
out=ROOT/'outputs/01a0f580-2480-7820-bc97-8ca293421c39/材质证明原件';out.mkdir(exist_ok=True)
po={p['id']:p for p in raw['purchase_lines']};owner=raw['incoming_inspections'][0]['inspector_id'];headers={};links={}
case_labels={1:'原到货有证明号但缺显式关联',2:'关联其他物料的证明',3:'供方批次映射错误',4:'只有台账，无平台归档原件',5:'台账摘要与归档原件不同',6:'原件证明号与声明不同',7:'原件重复特性',8:'原件表头含未知列',9:'最新关联厂内批次错误，不回退',10:'最新关联已撤销，不回退',11:'未来更正不覆盖当前',12:'有效关联同刻并列',13:'声明三特性但仅两行',14:'原件单位与声明不同',15:'原件数值不是有限数值',16:'原件实测值与声明不同',17:'原件归档在另一账号，当前管理员不越权读取',18:'签发日在业务截止及到货后',19:'原件少一条特性',20:'已声明原件标识但未登记摘要',21:'TXT原件保留，内容未结构化核对',22:'只有截止后的关联',23:'前序版本引用另一个到货关联',25:'台账证明号与原到货不同',26:'关联了别的归档文件',27:'关联登记时间早于到货'}
for i,r in enumerate(raw['receipts'],1):
    c=dict(id=f'MTC2609-{i:05d}',number=r['certificate'],supplier_id=po[r['purchase_line_id']]['supplier_id'],material_id=r['material_id'],supplier_lot=f'SB2609-{i:05d}',issued=(datetime.fromisoformat(r['received'])-timedelta(days=1)).date().isoformat(),file_id=None,file_sha256=None,property_count=2,document_type='模拟供方材质声明',basis='所有声明数值、方法及编号均为自编模拟，不含真实供方签章、资质或生产验收依据')
    if i==18:c['issued']='2026-10-02'
    if i==25:c['number']='CZ-DEMO-OTHER-00025'
    tables['material_certificates'].append(c);headers[i]=c
    wanted=[s for s in raw['incoming_specs'] if s['material_id']==r['material_id'] and s['mandatory'] and s['effective']<=r['received'][:10] and (not s['expires'] or r['received'][:10]<s['expires'])];assert len(wanted)==2
    for j,s in enumerate(wanted,1):
        value=round((s['lsl']+s['usl'])/2+(s['usl']-s['lsl'])*rng.uniform(-.1,.1),6)
        tables['material_certificate_properties'].append(dict(id=f'MTCP2609-{i:05d}-{j:02d}',certificate_id=c['id'],parameter=s['parameter'],name=s['name'],value=value,unit=s['unit'],method='模拟供方声明方法，与本厂抽样方法分开',reference='模拟供方项目-'+s['parameter']))
    link=dict(id=f'MTCL2609-{i:05d}-01',receipt_id=r['id'],certificate_id=c['id'],version=1,previous_id=None,lot=r['lot'],supplier_lot=c['supplier_lot'],recorded=(datetime.fromisoformat(r['received'])+timedelta(hours=1)).isoformat(timespec='seconds'),status='登记关联',owner_id=owner,reference=f'模拟到货文件核对-{i:05d}',note='显式映射厂内批次与供应批次，仅为模拟登记，不批准材料')
    links[i]=link
    if i!=1:tables['receipt_certificate_links'].append(link)
    if i in case_labels:cases[r['id']]=dict(case=case_labels[i],index=i)
links[2]['certificate_id']=next(c['id'] for c in headers.values() if c['material_id']!=headers[2]['material_id']);links[3]['supplier_lot']='SB-DEMO-WRONG'
for i in [9,10,11,12,23]:
    v=links[i]|dict(id=f'MTCL2609-{i:05d}-02',version=2,previous_id=links[i]['id'],recorded=(datetime.fromisoformat(links[i]['recorded'])+timedelta(minutes=10)).isoformat(timespec='seconds'),note='故意模拟更正或异常情形，保留首次登记')
    if i==9:v['lot']='RM-DEMO-OTHER'
    if i==10:v['status']='撤销关联'
    if i==11:v.update(recorded='2026-10-02T10:00:00',lot='RM-DEMO-FUTURE')
    if i==12:v['recorded']=links[i]['recorded']
    if i==23:v['previous_id']=links[2]['id']
    tables['receipt_certificate_links'].append(v)
links[22]['recorded']='2026-10-02T10:00:00';links[27]['recorded']=(datetime.fromisoformat(raw['receipts'][26]['received'])-timedelta(minutes=5)).isoformat(timespec='seconds')
headers[13]['property_count']=3
admin=User.objects.get(username='demo_admin');quality=User.objects.get(username='demo_quality');archived_before=DeviceFile.objects.count();uploaded=[]
for i,c in headers.items():
    props=[p for p in tables['material_certificate_properties'] if p['certificate_id']==c['id']]
    rr=[dict(certificate_no=c['number'],supplier_id=c['supplier_id'],material_id=c['material_id'],supplier_lot=c['supplier_lot'],issued=c['issued'],property_id=p['id'],**{k:str(p[k]) for k in ['parameter','value','unit','method','reference']}) for p in props]
    columns=list(eng.HEADERS)
    if i==6:
        for row in rr:row['certificate_no']='CZ-DEMO-BAD-CONTENT'
    if i==7:rr.append(dict(rr[0]))
    if i==8:
        columns+=['unknown_field']
        for row in rr:row['unknown_field']='模拟未知列'
    if i==14:rr[0]['unit']='模拟错误单位'
    if i==15:rr[0]['value']='NaN'
    if i==16:rr[0]['value']=str(float(rr[0]['value'])+.123456)
    if i==19:rr=rr[:1]
    text=io.StringIO();writer=csv.writer(text);writer.writerow(columns)
    for row in rr:writer.writerow([row[k] for k in columns])
    payload=('\ufeff'+text.getvalue()).encode();name=f'模拟材质证明_{i:05d}.csv'
    if i==21:name=f'模拟纸质转录_{i:05d}.txt';payload='模拟纸质材质证明转录。保留原件字节，当前未结构化解析或确认签章。'.encode()
    (out/name).write_bytes(payload);sha=hashlib.sha256(payload).hexdigest();files.append(dict(filename=name,sha256=sha,bytes=len(payload),archived=i!=4))
    if i==4:continue
    user=quality if i==17 else admin;request=uuid.uuid5(uuid.NAMESPACE_URL,'motor-certificate-builder-v1:'+name+':'+sha)
    f=device_files.upload(user,SimpleUploadedFile(name,payload),request,'本机模拟编织的材质证明原件，配合Excel核对，不是人工作出的批准或真实供方文件')
    c.update(file_id=str(f.pk),file_sha256=f.file_hash);uploaded.append(str(f.pk))
headers[5]['file_sha256']='deadbeef'*8;headers[20]['file_sha256']=None;headers[26]['file_id']=headers[27]['file_id']
notice='全部为合成模拟。证明、特性声明和到货关联分别一行一个对象；实际CSV/TXT原件已编织，多数由本机模拟生成器归档，故意保留缺原件、错误声明、撤销和未来关联。原件内容一致不代表签章真实或材料批准；原件私有权限按当前账号核查。'
scenario=dict(as_of=analytics.AS_OF,schema_version='MOTOR-DEMO-28-CERT-1',notice=notice,tables=tables,schemas={key:SCHEMAS[key] for key in eng.TABLES},cases=cases)
(ROOT/'data/material_certificate_scenario.json').write_text(json.dumps(scenario,ensure_ascii=False,indent=2))
proof=eng.Certificates(raw|tables,eng.resolver(admin));assert not proof.global_issues
expected={1:'missing_link',2:'record_attention',3:'record_attention',4:'file_missing',5:'file_attention',6:'content_attention',7:'content_attention',8:'content_attention',9:'record_attention',10:'withdrawn',11:'consistent',12:'record_attention',13:'record_attention',14:'content_attention',15:'content_attention',16:'content_attention',17:'no_access',18:'record_attention',19:'content_attention',20:'record_attention',21:'unparsed',22:'missing_link',23:'record_attention',25:'record_attention',26:'file_attention',27:'record_attention'}
for key,case in cases.items():assert proof.index[key]['state']==expected[case['index']],(key,proof.index[key]['state'],proof.index[key]['issues'])
added=DeviceFile.objects.count()-archived_before
if added:AuditEvent.objects.create(action='simulation.certificate_originals',actor='local-simulation-builder',object_type='DeviceFile',object_id='material-certificates',detail={'synthetic':True,'files_added':added,'via_existing_upload_service':True,'human_review':False,'business_facts_changed':False})
bundle=ROOT/'outputs/材质证明_模拟原件包.zip'
with zipfile.ZipFile(bundle,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for item in files:z.write(out/item['filename'],item['filename'])
    z.writestr('阅读说明.txt','全部自编模拟，不能用于生产验收或证明真实供应商签章。133个源文件，132个已通过平台文件归档服务归档，1个故意仅保留在模拟输出中。文件内容错误和关联资料错误为演练情形，逐项情况见配套Excel。')
with zipfile.ZipFile(bundle) as z:assert not z.testzip()
report=dict(tables={key:len(rows) for key,rows in tables.items()},summary=eng.summary(proof.rows),originals=len(files),archived=len(uploaded),new_archives=added,files=files,cases={key:case|dict(state=proof.index[key]['state']) for key,case in cases.items()},original_bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest())
(ROOT/'data/material_certificate_scenario_build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({key:value for key,value in report.items() if key not in ['files','cases']},ensure_ascii=False))
