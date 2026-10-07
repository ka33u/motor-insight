"""Permission-scoped discovery declarations. Never open a declared source path."""
import hashlib,json,re
from collections import Counter,defaultdict
from datetime import datetime,timedelta
from pathlib import PureWindowsPath
from django.core.exceptions import PermissionDenied,ValidationError
from django.contrib.auth.models import User
from . import access,device_files as originals
from .models import Record,DeviceFile

REVISION='device-intake-20261006-v1'
DATASETS=('device_sources','device_scan_runs','device_file_observations')
AS_OF='2026-10-01T18:00:00'
NOTICE='模拟 Excel 登记的目录和文件清单；没有访问设备电脑。归档状态仅核对本人私有原件，文件名与 SN 线索不构成订单关联或质量放行。'
PAGE_SIZE=25
STATES={'uncollected':'未见本人匹配归档','fingerprint_missing':'缺少有效指纹','read_blocked':'读取待处理','archived_structured':'已归档待逐项核对','archived_manual':'已归档待人工核对','archive_invalid':'已归档但解析或内容异常','declaration_invalid':'文件声明待核对'}
SCAN_STATES={'not_scanned':'尚无扫描登记','not_executed':'扫描登记未执行','invalid':'扫描声明待核对','failed':'扫描失败','partial':'扫描未完整','empty':'完整扫描未发现文件','complete':'完整扫描已有文件'}

def digest(obj):return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def require(user):
 current=User.objects.filter(pk=user.pk).first()
 if not current or access.role(current) not in ('admin','quality'):raise PermissionDenied('设备目录清单仅供管理员与质量工程师核对')
 return current
def stamp(value):
 try:
  d=datetime.fromisoformat(value)
  return d if d.tzinfo is None else None
 except (TypeError,ValueError):return None
def filters(p):
 allowed={'source','scan','mode','state','q','as_of','page','receipt'}
 if set(p)-allowed or hasattr(p,'getlist') and any(len(p.getlist(k))!=1 for k in p):raise ValidationError('采集清单参数不支持或重复')
 f={k:p.get(k,'') for k in ('source','scan','state','q')};f.update(mode=p.get('mode','current'),as_of=p.get('as_of',AS_OF))
 if any(not isinstance(v,str) or len(v)>200 for v in f.values()):raise ValidationError('筛选内容无效或过长')
 f={k:v.strip() for k,v in f.items()}
 if f['mode'] not in ('current','all') or f['state'] and f['state'] not in STATES:raise ValidationError('采集清单筛选选项无效')
 if not stamp(f['as_of']) or not '2000-01-01'<=f['as_of'][:10]<='2100-12-31':raise ValidationError('截止时间须为本地无时区日期时间')
 f['as_of']=stamp(f['as_of']).isoformat(timespec='seconds')
 if f['scan'] and not f['source']:raise ValidationError('指定扫描批次时须同时选择来源')
 return f
def page(p):
 value=p.get('page','1')
 if not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{0,5}',value):raise ValidationError('页码无效')
 return int(value)
def source(r):
 s=r.source_row
 return dict(dataset=r.dataset,key=r.business_key,revision=r.revision,record_hash=r.record_hash,batch_id=str(s.batch_id),filename=s.batch.filename,sheet=s.sheet,row=s.row_number,file_sha256=s.batch.file_hash)
def fingerprint(v):
 size=v.get('size_bytes');sha=v.get('sha256')
 return (sha.lower(),size) if isinstance(sha,str) and re.fullmatch(r'[0-9a-fA-F]{64}',sha) and type(size) is int and size>=0 else None

class Workspace:
 def __init__(self,user,conf=None):
  user=require(user);self.user=user;self.filters=filters(conf or {});self.at=stamp(self.filters['as_of'])
  self.records={(r.dataset,r.business_key):r for r in Record.objects.filter(dataset__in=DATASETS).select_related('source_row__batch').order_by('business_key')}
  sources={k:r.values for (d,k),r in self.records.items() if d=='device_sources'}
  scans={k:r.values for (d,k),r in self.records.items() if d=='device_scan_runs'}
  observations={k:r.values for (d,k),r in self.records.items() if d=='device_file_observations'}
  if self.filters['source'] and self.filters['source'] not in sources:raise ValidationError('来源编号不存在')
  if self.filters['scan'] and (self.filters['scan'] not in scans or scans[self.filters['scan']]['source_id']!=self.filters['source']):raise ValidationError('扫描批次与来源不对应')
  by_scan=defaultdict(list);by_source=defaultdict(list)
  for v in observations.values():by_scan[v['scan_id']].append(v)
  for v in scans.values():by_source[v['source_id']].append(v)
  self.scan_rows={};self.source_rows=[];selected_scans=set()
  for sid,s in sources.items():
   if not stamp(s.get('registered')) or stamp(s['registered'])>self.at:continue
   history=[]
   for run in by_source[sid]:
    started=stamp(run.get('started'))
    if not started or started>self.at:continue
    visible=[v for v in by_scan[run['id']] if stamp(v.get('discovered')) and stamp(v['discovered'])<=self.at]
    reasons=[];finish=stamp(run.get('finished'));state='complete'
    if run.get('status') not in ('完成','部分完成','失败','未执行'):reasons.append('扫描结论未定义')
    if run.get('reported_count') is not None and (type(run['reported_count']) is not int or run['reported_count']<0):reasons.append('声明发现数无效')
    if finish and finish<started:reasons.append('结束时间早于开始时间')
    if run.get('status')=='完成':
     if not finish or finish>self.at:state='partial'
     elif run.get('reported_count') is None or run['reported_count']!=len(visible):reasons.append('声明发现数与截止时点可见明细不一致')
     elif any(stamp(v['discovered'])<started or stamp(v['discovered'])>finish for v in visible):reasons.append('发现登记时间超出扫描窗口')
     elif not visible:state='empty'
    elif run.get('status')=='失败':state='failed'
    elif run.get('status')=='未执行':state='not_executed'
    else:state='partial'
    if reasons:state='invalid'
    row={**run,'state':state,'state_label':SCAN_STATES[state],'visible_count':len(visible),'issues':reasons,'provenance':source(self.records['device_scan_runs',run['id']])}
    history.append(row);self.scan_rows[run['id']]=row
   history.sort(key=lambda r:(r['started'],r['id']),reverse=True)
   latest=history[0] if history else None;ties=bool(latest and sum(r['started']==latest['started'] for r in history)>1)
   state='invalid' if ties else latest['state'] if latest else 'not_scanned'
   stale=None if not latest else (self.at-stamp(latest['started'])).total_seconds()/3600>s['scan_interval_hours'] if type(s.get('scan_interval_hours')) is int and s['scan_interval_hours']>0 else None
   item={**s,'latest_scan':latest['id'] if latest else None,'state':state,'state_label':SCAN_STATES[state],'stale':stale,'interval_valid':type(s.get('scan_interval_hours')) is int and s['scan_interval_hours']>0,'latest_tie':ties,'visible_count':latest['visible_count'] if latest else None,'history':history,'provenance':source(self.records['device_sources',sid])}
   self.source_rows.append(item)
   if self.filters['source'] and sid!=self.filters['source']:continue
   if self.filters['scan']:
    if self.filters['scan'] not in self.scan_rows:raise ValidationError('扫描批次尚未到所选截止时间')
    selected_scans.add(self.filters['scan'])
   elif self.filters['mode']=='all':selected_scans.update(r['id'] for r in history)
   elif latest:selected_scans.update(r['id'] for r in history if r['started']==latest['started'])
  # Never learn another account's file existence through discovery metadata.
  keys={fingerprint(v) for v in observations.values() if v['scan_id'] in selected_scans};keys.discard(None)
  matches=defaultdict(list);integrity=[]
  for f in DeviceFile.objects.filter(owner=user,file_hash__in=[k[0] for k in keys]).order_by('id'):
   if (f.file_hash,f.size) not in keys:continue
   ok=True;error=''
   try:originals.get(user,f.pk)
   except (ValidationError,ValueError,OSError):ok=False;error='私有原件内容或元数据核对失败'
   info=dict(id=str(f.pk),filename=f.filename,size=f.size,sha256=f.file_hash,mode=f.parsed.get('mode'),integrity_ok=ok,error=error,href='#device-files?id='+str(f.pk))
   matches[f.file_hash,f.size].append(info);integrity.append(info)
  self.rows=[]
  for key,v in observations.items():
   if v['scan_id'] not in selected_scans or not stamp(v.get('discovered')) or stamp(v['discovered'])>self.at:continue
   run=self.scan_rows[v['scan_id']];s=sources[run['source_id']];fp=fingerprint(v);issues=[]
   if run['state']=='invalid':issues.extend(run['issues'])
   path=PureWindowsPath(v.get('relative_path') or '')
   if not isinstance(v.get('relative_path'),str) or path.root or path.drive or '..' in path.parts:issues.append('相对路径须留在声明目录内')
   if PureWindowsPath(v.get('relative_path','')).name!=v.get('filename'):issues.append('相对路径与文件名不一致')
   if str(v.get('format','')).lower()!=PureWindowsPath(v.get('filename','')).suffix.lower().lstrip('.'):issues.append('声明格式与扩展名不一致')
   if stamp(v.get('modified')) and stamp(v['modified'])>stamp(v['discovered']):issues.append('声明修改时间晚于发现登记时间')
   if stamp(v['discovered'])<stamp(run['started']) or stamp(run.get('finished')) and stamp(v['discovered'])>stamp(run['finished']):issues.append('发现登记时间超出扫描窗口')
   if v.get('read_state') not in ('可读','正在写入','无权限','损坏','待核查'):issues.append('读取状态未定义')
   if any(s0['id']==s['id'] and s0['latest_tie'] for s0 in self.source_rows) and self.filters['mode']=='current' and not self.filters['scan']:issues.append('最新扫描时间相同，无法确定唯一当前批次')
   archives=matches.get(fp,[]);state='uncollected'
   if issues:state='declaration_invalid'
   elif v.get('read_state')!='可读':state='read_blocked'
   elif not fp:state='fingerprint_missing'
   elif archives:
    if any(not a['integrity_ok'] or a['mode']=='invalid' for a in archives):state='archive_invalid'
    elif any(a['mode']=='structured' for a in archives):state='archived_structured'
    else:state='archived_manual'
   self.rows.append({**v,'key':key,'source_id':s['id'],'equipment_id':s['equipment_id'],'host_label':s['host_label'],'scan_state':run['state'],'scan_state_label':run['state_label'],'state':state,'state_label':STATES[state],'issues':issues,'fingerprint_valid':bool(fp),'fingerprint_key':digest(fp) if fp else None,'archives':archives,'provenance':source(self.records['device_file_observations',key])})
  duplicates=Counter(r['fingerprint_key'] for r in self.rows if r['fingerprint_key'])
  for r in self.rows:r['same_content_observations']=duplicates[r['fingerprint_key']] if r['fingerprint_key'] else None
  self.source_rows.sort(key=lambda r:r['id']);self.rows.sort(key=lambda r:(r['source_id'],r['scan_id'],r['relative_path'],r['key']))
  self.receipt=digest([REVISION,user.pk,access.role(user),self.filters,[[source(r),r.values] for r in self.records.values()],integrity])
 def check(self,receipt):
  if receipt!=self.receipt:raise ValidationError('来源、私有归档或筛选已变化，请重新读取采集清单')
 def selected(self):
  q=self.filters['q'].casefold();state=self.filters['state']
  return [r for r in self.rows if (not state or r['state']==state) and (not q or q in ' '.join(str(r.get(k) or '') for k in ('key','source_id','equipment_id','filename','relative_path','session_hint','unit_hint')).casefold())]
 def summary(self,rows):
  c=Counter(r['state'] for r in rows);known={r['fingerprint_key']:r['size_bytes'] for r in rows if r['fingerprint_key']}
  selected_sources=[s for s in self.source_rows if not self.filters['source'] or s['id']==self.filters['source']]
  return dict(observations=len(rows),known_contents=len(known),unknown_fingerprints=sum(not r['fingerprint_valid'] for r in rows),duplicate_observations=sum(r['fingerprint_valid'] for r in rows)-len(known),known_content_bytes=sum(known.values()),sources=len(selected_sources),source_states=dict(Counter(r['state'] for r in selected_sources)),stale_sources=sum(s['stale'] is True for s in selected_sources),file_states=dict(c))
 def board(self,n=1):
  rows=self.selected();return dict(revision=REVISION,notice=NOTICE,filters=self.filters,receipt=self.receipt,as_of=self.filters['as_of'],business_quality_as_of=AS_OF,summary=self.summary(rows),rows=rows[(n-1)*PAGE_SIZE:n*PAGE_SIZE],page=n,page_size=PAGE_SIZE,total=len(rows),sources=[{k:v for k,v in s.items() if k!='history'} for s in self.source_rows],states=STATES,scan_states=SCAN_STATES,can_collect_live=False)
 def detail(self,key):
  row=next((r for r in self.selected() if r['key']==key),None)
  if row is None:raise ValidationError('发现记录不在当前筛选范围')
  s=next(s for s in self.source_rows if s['id']==row['source_id']);run=self.scan_rows[row['scan_id']];checks=[]
  if row['session_hint']:
   for a in row['archives']:
    if not a['integrity_ok']:continue
    try:
     p=originals.preview(self.user,a['id'],row['session_hint'])
     hint_ok=not p['target'] or not row['unit_hint'] or row['unit_hint']==p['target']['unit_id']
     equipment_ok=not p['target'] or s['equipment_id']==p['target']['equipment_id']
     checks.append(dict(file_id=a['id'],mode=p['mode'],target=p['target'],comparison=p['comparison'],errors=p['errors'],source_changed=p['source_changed'],session_can_confirm=p['can_confirm'],declaration_sn_matches=hint_ok,declaration_equipment_matches=equipment_ok,notice='会话核对由原件工作台执行；这里仅展示线索，声明不参与自动关联。'))
    except (ValidationError,ValueError,OSError):checks.append(dict(file_id=a['id'],errors=['会话线索无法核对，请到原件工作台检查']))
  return dict(row=row,source=s,scan=run,checks=checks,receipt=self.receipt,notice=NOTICE)
