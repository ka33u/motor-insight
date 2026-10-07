"""Archive synthetic originals through normal service; generate Excel inputs only."""
import os,sys,json,sqlite3,csv,io,uuid,hashlib
from datetime import datetime,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from app import metrology as reg,metrology_evidence as eng,device_files,access
from app.models import Record
from app.schema import SCHEMAS
assert not Record.objects.filter(dataset__in=eng.TABLES).exists(),'已有证书来源，拒绝重新编排'
admin=User.objects.get(username='demo_admin');quality=next(u for u in User.objects.filter(is_active=True) if access.role(u)=='quality')
m=reg.Metrology();calibrations=sorted(m.data['metrology_calibrations'],key=lambda r:r['id']);new={k:[] for k in eng.TABLES};cases={};archives=[]
# Exercise cases on actual currently selected, required, valid instrument rows.
active=[]
for inst in sorted(m.data['metrology_instruments'],key=lambda r:r['id']):
    if inst['stage']=='档案':continue
    req=m.rule(inst['stage'],inst['parameter'],inst['unit'],m.cutoff)['required'];c=m.calibration(inst,m.cutoff,req)
    if c['state']=='valid':active.append(c['selected']['id'])
names=['missing_link','withdrawn','duplicate_latest','broken_chain','file_missing','file_attention','content_attention','record_attention','unparsed','no_access','duplicate_content','issued_attention','late_correction']
special=dict(zip(active[:len(names)],names));owner_id=m.data['metrology_instruments'][0]['owner_id']
for i,c in enumerate(calibrations,1):
    key=f'JL-ZM-{i:05d}';kind=special.get(c['id']);issued=(datetime.fromisoformat(c['performed'])+timedelta(minutes=15)).isoformat(timespec='seconds')
    doc={k:c[k] for k in eng.COMPARE};doc.update(issued=issued,reference='模拟证明依据-'+key)
    if kind=='record_attention':doc['instrument_id']=next(x['id'] for x in m.data['metrology_instruments'] if x['id']!=c['instrument_id'] and x['stage']!='档案')
    if kind=='issued_attention':doc['issued']=(datetime.fromisoformat(c['performed'])-timedelta(hours=1)).isoformat(timespec='seconds')
    original=dict(doc)
    if kind=='content_attention':original['certificate_no']='SIM-错误证书号-演练'
    out=io.StringIO();writer=csv.writer(out);writer.writerow(eng.HEADERS);writer.writerow([original[k] for k in eng.HEADERS])
    if kind=='duplicate_content':writer.writerow([original[k] for k in eng.HEADERS])
    raw=('\ufeff'+out.getvalue()).encode();suffix='csv'
    if kind=='unparsed':raw=('模拟人工原件，尚未结构化核对。\n'+json.dumps(original,ensure_ascii=False,indent=2)).encode();suffix='txt'
    file=None
    if kind!='file_missing':
        user=quality if kind=='no_access' else admin
        request_id=uuid.uuid5(uuid.NAMESPACE_URL,'motor-synthetic-metrology-original-v1/'+c['id'])
        file=device_files.upload(user,SimpleUploadedFile('模拟校准证明_'+key+'.'+suffix,raw),request_id,'合成校准证明演练；非真实证书或测量能力批准，仅用于字段对应和权限核查。')
        archives.append(dict(id=str(file.pk),owner=user.username,filename=file.filename,sha256=file.file_hash,calibration_id=c['id']))
    cert=dict(id=key,**doc,file_id=str(file.pk) if file else None,file_sha256=('f'*64 if kind=='file_attention' else file.file_hash) if file else None,
              owner_id=owner_id,note='全部为合成声明和模拟原件；原件内容一致不代表真实签章、认可资质、测量能力或产品批准。')
    new[eng.TABLES[0]].append(cert)
    at=max(datetime.fromisoformat(c['registered']),datetime.fromisoformat(doc['issued']))+timedelta(hours=1)
    link=dict(id=f'JL-GL-{i:05d}-V01',series=f'JL-GL-{i:05d}',version=1,previous_id=None,status='已登记',calibration_id=c['id'],certificate_id=key,
              registered=at.isoformat(timespec='seconds'),owner_id=owner_id,reference='模拟原件关联-'+key,note='对应确切校准版本；不是校准批准、自动放行或对其他账号的原件授权。')
    if kind!='missing_link':new[eng.TABLES[1]].append(link)
    if kind in ['withdrawn','duplicate_latest','broken_chain','late_correction']:
        v=dict(link,id=link['id'].replace('V01','V02'),version=2,previous_id=link['id'],registered='2026-09-29T09:00:00')
        if kind=='withdrawn':v['status']='撤销'
        if kind=='broken_chain':v['previous_id']=None
        if kind=='late_correction':v['note']='后来完整关联重新核对；不会覆盖校准或原检测结论。'
        new[eng.TABLES[1]].append(v)
        if kind=='duplicate_latest':new[eng.TABLES[1]].append(dict(v,id=v['id']+'-重复演练'))
    if kind:cases[kind]=dict(calibration_id=c['id'],instrument_id=c['instrument_id'],certificate_id=key,file_id=str(file.pk) if file else None)
e=eng.Evidence(m,new,eng.resolver(admin));assert len(e.rows)==150
for kind,case in cases.items():
    expected={'duplicate_latest':'record_attention','broken_chain':'record_attention','duplicate_content':'content_attention','issued_attention':'record_attention','late_correction':'consistent'}.get(kind,kind)
    assert e.inspections[case['calibration_id']]['state']==expected,(kind,e.inspections[case['calibration_id']])
scenario=dict(schema_version=1,as_of=m.cutoff,notice='合成校准证明、显式原件关联和模拟CSV/TXT；真实证书、签章、实验室能力及不确定度未核验。归档原件默认私有，内容一致不修改原校准、检测、失准或放行。',schemas={k:SCHEMAS[k] for k in eng.TABLES},tables=new)
(ROOT/'data/metrology_evidence_scenario.json').write_text(json.dumps(scenario,ensure_ascii=False,indent=2))
report=dict(tables={k:len(v) for k,v in new.items()},rows=sum(map(len,new.values())),archives=archives,cases=cases,current_summary=eng.summary([r for r in e.rows if r['instrument']['stage']!='档案']),all_summary=eng.summary(e.rows),simulation_only=True)
(ROOT/'data/metrology_evidence_scenario_build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ['cases','archives']},ensure_ascii=False))
