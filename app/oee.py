"""Loss-conserving OEE on declared independent resources and production windows."""
import hashlib,json
from collections import Counter,defaultdict
from decimal import Decimal
from pathlib import Path
from .finite_schedule_contract import time
from .oee_contract import issues as row_issues
from .oee_schema import DATASETS
NOTICE='独立合成班次采集，不能代表全设备或全厂实际OEE。计划生产窗口排除不打算生产的时段；窗口内换型和故障计停止。首次良品不含返工后合格。混配置合计仅显示理想良品时间占比，不能简单平均OEE。'
REFERENCES=['https://www.oee.com/calculating-oee/','https://www.oee.com/oee-factors/']
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def rule_hash():return digest({p:hashlib.sha256(Path(__file__).with_name(p).read_bytes()).hexdigest() for p in ('oee.py','oee_contract.py','oee_schema.py','oee_data.py')})
def seconds(a,b):return Decimal(str((b-a).total_seconds()))
def union(intervals):
 out=[]
 for a,b in sorted(intervals):
  if a>=b:continue
  if out and a<=out[-1][1]:out[-1]=(out[-1][0],max(out[-1][1],b))
  else:out.append((a,b))
 return out
def duration(intervals):return sum((seconds(a,b) for a,b in union(intervals)),Decimal(0))
def ratio(a,b):return float(a/b) if b else None
def analyze(study,tables,resource,products,as_of):
 from .schema import SCHEMAS
 issues=[];windows=[];events=[];output_rows=tables.get('oee_outputs',[])
 result=dict(study=study,state='paused',issues=issues,windows=windows,events=events,summary=None,synthetic=True,notice=NOTICE,as_of=as_of,references=REFERENCES)
 def fail(message):
  if message not in issues:issues.append(message)
 try:cutoff=time(as_of)
 except (TypeError,ValueError):fail('业务截止无效');return result
 for ds,rows in [('oee_studies',[study]),*[(d,tables.get(d,[])) for d in DATASETS[1:]]]:
  if len(rows)>10000:fail('独立方案每表最多10000行');return result
  if any(not isinstance(r,dict) for r in rows):fail('输入行结构无效');return result
  required={f['name'] for f in SCHEMAS[ds]['fields'] if f['required']}
  if any(not required<=set(r) or any(r[k] in (None,'') for k in required) for r in rows):fail(ds+'必填采集字段缺失');return result
  if len({r.get('id') for r in rows})!=len(rows):fail(ds+'身份重复')
  for row in rows:
   for i in row_issues(ds,row):fail(ds+'/'+str(row.get('id'))+'：'+i['message'])
   if ds!='oee_studies' and row.get('study_id')!=study.get('id'):fail('跨方案输入不能合并')
 if issues:return result
 for field,ds in [('window_count','oee_windows'),('event_count','oee_events'),('cycle_count','oee_cycles'),('output_count','oee_outputs')]:
  if study.get(field)!=len(tables.get(ds,[])):fail('采集声明与当前行数不一致：'+ds)
 if study.get('capture_state')!='完整':fail('班次采集尚未闭合')
 if not resource or resource.get('id')!=study.get('resource_id') or type(resource.get('capacity')) is not int or resource.get('capacity')!=1:fail('须有已识别、容量为1的独立资源位')
 if not tables.get('oee_windows'):fail('未登记计划生产窗口')
 cycles=defaultdict(list)
 for c in tables.get('oee_cycles',[]):cycles[(c.get('product_id'),c.get('unit'))].append(c)
 outputs=defaultdict(list);windowids={w['id'] for w in tables.get('oee_windows',[])}
 for o in output_rows:
  if o['window_id'] not in windowids:fail('报产关联窗口不属于当前方案')
  outputs[o['window_id']].append(o)
 intervals=[]
 for w in sorted(tables.get('oee_windows',[]),key=lambda w:(w['started'],w['id'])):
  a,b=time(w['started']),time(w['finished']);intervals.append((a,b))
  if b>cutoff:fail('实际采集窗口晚于业务截止，不能算历史实绩')
  if resource and (not resource.get('effective') or resource['effective']>a.date().isoformat()):fail('资源位尚未生效')
  if w['product_id'] not in products:fail('产品配置引用缺失')
  cs=cycles[w['product_id'],w['unit']];cycle=Decimal(str(cs[0]['seconds_per_unit'])) if len(cs)==1 else None
  if len(cs)!=1:fail('配置和单位须有且仅有一个理想节拍：'+w['id'])
  count={k:sum(o[k] for o in outputs[w['id']]) for k in ('total_qty','good_first_qty','rework_qty','scrap_qty','unknown_qty')}
  for o in outputs[w['id']]:
   if o['unit']!=w['unit']:fail('报产和窗口单位不一致：'+o['id'])
   if not a<=time(o['reported'])<=b or time(o['reported'])>cutoff:fail('报产登记时间不在关联窗口或晚于截止：'+o['id'])
  if count['unknown_qty']:fail('产出分类尚未确认：'+w['id'])
  stops=[];cause=defaultdict(list);event_ids=[]
  for e in tables.get('oee_events',[]):
   ea,eb=time(e['started']),time(e['finished'])
   if eb>cutoff:fail('停止事件晚于业务截止：'+e['id'])
   left,right=max(a,ea),min(b,eb)
   if left<right:stops.append((left,right));cause[e['kind']].append((left,right));event_ids.append(e['id'])
  planned=seconds(a,b);stop=duration(stops);run=planned-stop;ideal=cycle*count['total_qty'] if cycle is not None else None;good=cycle*count['good_first_qty'] if cycle is not None else None
  if ideal is not None and ideal>run:fail('理想加工时间超过运行时间，需核对节拍、数量和资源边界：'+w['id'])
  windows.append(dict(**w,counts=count,output_ids=[o['id'] for o in outputs[w['id']]],event_ids=event_ids,cycle_id=cs[0]['id'] if len(cs)==1 else None,ideal_seconds_per_unit=float(cycle) if cycle else None,planned_seconds=float(planned),stop_seconds=float(stop),run_seconds=float(run),ideal_seconds=float(ideal) if ideal is not None else None,good_ideal_seconds=float(good) if good is not None else None,availability=ratio(run,planned),performance=ratio(ideal,run) if ideal is not None else None,quality=ratio(Decimal(count['good_first_qty']),Decimal(count['total_qty'])),oee=ratio(good,planned) if good is not None else None,speed_loss_seconds=float(run-ideal) if ideal is not None else None,quality_loss_seconds=float(ideal-good) if ideal is not None else None,stop_segments=[dict(started=a.isoformat(),finished=b.isoformat()) for a,b in union(stops)],cause_seconds={k:float(duration(v)) for k,v in sorted(cause.items())}))
 if sum((seconds(a,b) for a,b in intervals),Decimal(0))!=duration(intervals):fail('计划生产窗口重叠，不能重复占用同一资源位')
 for e in tables.get('oee_events',[]):
  a,b=time(e['started']),time(e['finished']);inside=duration([(max(a,w_a),min(b,w_b)) for w_a,w_b in intervals]);events.append(dict(**e,inside_seconds=float(inside),outside_seconds=float(seconds(a,b)-inside)))
 if issues:
  for w in windows:
   for k in ('availability','performance','quality','oee','speed_loss_seconds','quality_loss_seconds','good_ideal_seconds'):w[k]=None
  return result
 planned=sum((Decimal(str(w['planned_seconds'])) for w in windows),Decimal(0));stop=sum((Decimal(str(w['stop_seconds'])) for w in windows),Decimal(0));run=planned-stop;ideal=sum((Decimal(str(w['ideal_seconds'])) for w in windows),Decimal(0));good=sum((Decimal(str(w['good_ideal_seconds'])) for w in windows),Decimal(0))
 distinct={(w['product_id'],w['unit'],w['ideal_seconds_per_unit']) for w in windows};mixed=len(distinct)>1;common_unit=len({w['unit'] for w in windows})==1
 counts={k:sum(w['counts'][k] for w in windows) if common_unit else None for k in ('total_qty','good_first_qty','rework_qty','scrap_qty','unknown_qty')}
 result['summary']=dict(planned_seconds=float(planned),stop_seconds=float(stop),run_seconds=float(run),ideal_seconds=float(ideal),good_ideal_seconds=float(good),speed_loss_seconds=float(run-ideal),quality_loss_seconds=float(ideal-good),availability=ratio(run,planned),performance=ratio(ideal,run) if not mixed else None,quality=ratio(Decimal(counts['good_first_qty']),Decimal(counts['total_qty'])) if not mixed else None,oee=ratio(good,planned) if not mixed else None,good_ideal_time_share=ratio(good,planned),mixed_configuration=mixed,counts=counts,unit=windows[0]['unit'] if common_unit else None,measure_label='混配置理想良品时间占比' if mixed else '独立资源位OEE',loss_conservation_seconds=float(planned-stop-(run-ideal)-(ideal-good)-good))
 result['state']='ready';return result
