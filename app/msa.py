"""Balanced crossed random-effects trial, full interaction retained."""
import copy,hashlib,json,math
from collections import Counter,defaultdict
from decimal import Decimal,localcontext
from pathlib import Path
from .msa_source_contract import issues as row_issues
from .msa_calibration import context as calibration_context
from .metrology import clock

RULE_VERSION='MSA-CROSSED-FULL-TRIAL.01'
MAX_OBSERVATIONS=5000
NOTICE='合成测量系统候选试算。交叉、随机效应、恒定方差和可重复测量是当前分析假设；样件代表性、盲测、独立性及真实工况未审定。不作MSA合格判定、过程能力计算或产品批准。'
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def rule_hash():
 files=('msa.py','msa_schema.py','msa_source_contract.py','msa_calibration.py','msa_data.py','metrology.py')
 return hashlib.sha256(b''.join((Path(__file__).parent/name).read_bytes() for name in files)).hexdigest()
def finite(v):return type(v) in (int,float) and math.isfinite(v)

def decompose(cells,parts,operators,repeats,tolerance):
 """Decimal arithmetic avoids cancelling small variation around a large offset."""
 with localcontext() as ctx:
  ctx.prec=40;p=len(parts);o=len(operators);r=repeats;zero=Decimal(0)
  data={(a,b):[Decimal(str(v)) for v in cells[a,b]] for a in parts for b in operators}
  means={k:sum(v,zero)/r for k,v in data.items()};grand=sum(means.values(),zero)/(p*o)
  pm={a:sum((means[a,b] for b in operators),zero)/o for a in parts};om={b:sum((means[a,b] for a in parts),zero)/p for b in operators}
  ss={'part':o*r*sum(((v-grand)**2 for v in pm.values()),zero),
      'operator':p*r*sum(((v-grand)**2 for v in om.values()),zero),
      'interaction':r*sum(((means[a,b]-pm[a]-om[b]+grand)**2 for a in parts for b in operators),zero),
      'repeatability':sum(((v-means[k])**2 for k,values in data.items() for v in values),zero)}
  total=sum(((v-grand)**2 for values in data.values() for v in values),zero)
  dfs=dict(part=p-1,operator=o-1,interaction=(p-1)*(o-1),repeatability=p*o*(r-1));ms={k:v/dfs[k] for k,v in ss.items()}
  raw=dict(repeatability=ms['repeatability'],operator=(ms['operator']-ms['interaction'])/(p*r),interaction=(ms['interaction']-ms['repeatability'])/r,part=(ms['part']-ms['interaction'])/(o*r))
  variances={k:max(zero,v) for k,v in raw.items()};variances['reproducibility']=variances['operator']+variances['interaction'];variances['grr']=variances['repeatability']+variances['reproducibility'];variances['total']=variances['grr']+variances['part']
  band=Decimal(str(tolerance)) if tolerance is not None else None
  components=[]
  for k in ('repeatability','operator','interaction','reproducibility','grr','part','total'):
   v=variances[k];sd=v.sqrt();sv=6*sd
   components.append(dict(key=k,raw_variance=float(raw[k]) if k in raw else None,variance=float(v),clamped=k in raw and raw[k]<0,
    sd=float(sd),study_variation=float(sv),variance_percent=float(100*v/variances['total']) if variances['total'] else None,
    study_percent=float(100*sd/variances['total'].sqrt()) if variances['total'] else None,tolerance_percent=float(100*sv/band) if band and band>0 else None))
  result=dict(grand_mean=float(grand),anova=[dict(key=k,ss=float(ss[k]),df=dfs[k],ms=float(ms[k])) for k in ss]+[dict(key='total',ss=float(total),df=p*o*r-1,ms=None)],
   ss_reconciliation=float(total-sum(ss.values(),zero)),components=components,part_means={k:float(v) for k,v in pm.items()},operator_means={k:float(v) for k,v in om.items()},
   cell_means=[dict(part_id=a,operator_id=b,mean=float(means[a,b])) for a in parts for b in operators])
  def bounded(value):
   if type(value) is float:return math.isfinite(value)
   if isinstance(value,dict):return all(bounded(v) for v in value.values())
   if isinstance(value,list):return all(bounded(v) for v in value)
   return True
  if not bounded(result):raise ArithmeticError('数值尺度超过当前可呈现范围')
  return result

def analyze(study,members,observations,spec,instrument,units,employees,calibrations=(),cutoff='2026-10-01T18:00:00'):
 study=copy.deepcopy(study);issues=[];warnings=[];points=[];matrix=[];result=None
 if len(observations)>MAX_OBSERVATIONS:raise ValueError('测量系统试验超过5000观测，请拆分试验')
 if len(members)>100:raise ValueError('当前试验声明成员超过100个，请拆分试验')
 start=study.get('started') if clock(study.get('started')) else '';end=study.get('finished') if clock(study.get('finished')) else ''
 issues.extend(e['message'] for e in row_issues('msa_studies',study))
 dimensions=[study.get(k) for k in ('part_count','operator_count','repeat_count')]
 if any(type(n) is not int or not 2<=n<=50 for n in dimensions) or all(type(n) is int for n in dimensions) and math.prod(dimensions)>MAX_OBSERVATIONS:issues.append('当前模型须有2至50个样件、操作员和重复轮次，计划观测不超过5000')
 if study.get('model')!='CROSSED_RANDOM_FULL' or study.get('design')!='交叉可重复测量（模拟）':issues.append('当前只支持平衡交叉、可重复测量的全随机效应模型')
 if study.get('status')!='已结束':issues.append('试验采集未结束')
 if not start or not end or end>cutoff:issues.append('试验时间窗口不完整或超出业务截止')
 if not study.get('randomization') or study['randomization']=='未记录':issues.append('随机顺序或盲测依据未登记')
 if not spec or spec.get('product_id')!=study.get('product_id') or spec.get('unit')!=study.get('unit'):issues.append('规范配置或单位与试验不同')
 if not spec or not spec.get('effective') or spec['effective']>start[:10]:issues.append('规范生效日期未覆盖试验开始')
 if not instrument or not spec or (instrument.get('parameter'),instrument.get('unit'))!=(spec.get('test_code'),study.get('unit')):issues.append('仪器项目或单位与试验规范不同')
 if study.get('unit')=='bool':issues.append('二值项目不适用连续交叉Gage R&R，保留分类和原观测')
 cal=calibration_context(instrument,calibrations,study.get('started'),study.get('finished'),cutoff);issues.extend(cal['issues'])
 indexed={};parts=[];operators=[];labels=set();raw_members=[]
 for m in sorted(members,key=lambda m:str(m.get('id'))):
  reasons=[v['message'] for v in row_issues('msa_members',m)]
  if m.get('study_id')!=study.get('id') or not m.get('id') or m.get('id') in indexed:reasons.append('成员身份或所属试验不一致')
  if (m.get('kind'),m.get('blind_label')) in labels or not m.get('blind_label'):reasons.append('同类盲测标签缺失或重复')
  labels.add((m.get('kind'),m.get('blind_label')));indexed[m.get('id')]=m
  if m.get('kind')=='样件':
   unit=units.get(m.get('unit_id'))
   if not unit or unit.get('product_id')!=study.get('product_id'):reasons.append('样件SN缺失或配置不同')
   if unit and (not clock(unit.get('assembly_at')) or unit['assembly_at']>start):reasons.append('样件装配时间未覆盖试验')
   if m.get('unit_id') in {p.get('unit_id') for p in parts}:reasons.append('同一SN重复声明为不同样件')
   parts.append(m)
  elif m.get('kind')=='操作员':
   employee=employees.get(m.get('operator_id'))
   if not employee or employee.get('active') is not True:reasons.append('操作员未登记或当前人员台账未启用')
   if m.get('operator_id') in {o.get('operator_id') for o in operators}:reasons.append('同一人员重复声明为不同操作员')
   operators.append(m)
  if reasons:issues.append('成员 '+str(m.get('id'))+'：'+'；'.join(reasons))
  raw_members.append(dict(**m,reasons=reasons))
 if len(parts)!=study.get('part_count') or len(operators)!=study.get('operator_count'):issues.append('声明的样件或操作员数与计划不同')
 repeat_count=study.get('repeat_count');planned_repeats=list(range(1,repeat_count+1)) if type(repeat_count) is int and 1<=repeat_count<=50 else []
 cells=defaultdict(list);order_counts=Counter(p.get('run_order') for p in observations);ids=Counter(p.get('id') for p in observations)
 for p in sorted(observations,key=lambda p:(p.get('run_order') if type(p.get('run_order')) is int else 0,str(p.get('id')))):
  reasons=[v['message'] for v in row_issues('msa_observations',p)];part=indexed.get(p.get('part_member_id'));operator=indexed.get(p.get('operator_member_id'))
  if p.get('study_id')!=study.get('id') or ids[p.get('id')]!=1:reasons.append('观测身份或所属试验不一致')
  if not part or part.get('kind')!='样件' or part.get('study_id')!=study.get('id'):reasons.append('样件成员未核实')
  if not operator or operator.get('kind')!='操作员' or operator.get('study_id')!=study.get('id'):reasons.append('操作员成员未核实')
  if p.get('state')!='有效' or not finite(p.get('value')):reasons.append('观测缺测、作废或待核查')
  if p.get('unit')!=study.get('unit') or p.get('method_version')!=study.get('measurement_method'):reasons.append('观测单位或方法版本不同')
  if type(p.get('repeat')) is not int or p.get('repeat') not in planned_repeats:reasons.append('重复轮次不在计划范围')
  if type(p.get('run_order')) is not int or p['run_order']<1 or order_counts[p['run_order']]!=1:reasons.append('实际登记序号缺失或重复')
  if not clock(p.get('measured')) or not start<=p['measured']<=end or p['measured']>cutoff:reasons.append('实际测量时间未覆盖试验或截止')
  if not clock(p.get('registered')) or p['registered']>cutoff:reasons.append('登记时间未覆盖截止')
  q=dict(**copy.deepcopy(p),eligible=not reasons,reasons=list(dict.fromkeys(reasons)),part_label=part.get('blind_label') if part else None,operator_label=operator.get('blind_label') if operator else None,
   unit_id=part.get('unit_id') if part else None,operator_id=operator.get('operator_id') if operator else None)
  points.append(q);cells[p.get('part_member_id'),p.get('operator_member_id')].append(q)
 for part in parts:
  for operator in operators:
   cell=cells[part['id'],operator['id']];rounds=Counter(p['repeat'] for p in cell);available=[p for p in cell if p['eligible']]
   missing=[n for n in planned_repeats if not rounds[n]];duplicates=[n for n,count in rounds.items() if count>1]
   valid=len(cell)==len(planned_repeats) and len(available)==len(cell) and not missing and not duplicates
   matrix.append(dict(part_id=part['id'],operator_id=operator['id'],part_label=part['blind_label'],operator_label=operator['blind_label'],registered=len(cell),eligible=len(available),missing_repeats=missing,duplicate_repeats=duplicates,valid=valid,observation_ids=[p['id'] for p in cell]))
 if any(not c['valid'] for c in matrix) or not matrix:issues.append('交叉单元缺测、重复或有不适用观测，当前不以删行或补零恢复平衡')
 expected={(p['id'],o['id']) for p in parts for o in operators}
 if any(k not in expected for k in cells):issues.append('观测引用了计划交叉单元之外的成员')
 if any(not p['eligible'] for p in points):issues.append('存在需要核对的观测')
 lsl=spec.get('lsl') if spec else None;usl=spec.get('usl') if spec else None;band=usl-lsl if finite(lsl) and finite(usl) and usl>lsl and finite(usl-lsl) else None
 if band is None:warnings.append('双侧同单位产品公差未核实，%Tolerance不计算')
 if not issues:
  try:
   result=decompose({k:[p['value'] for p in values] for k,values in cells.items()},[p['id'] for p in parts],[o['id'] for o in operators],repeat_count,band)
   if next(c for c in result['components'] if c['key']=='total')['variance']==0:issues.append('总变异为零，变异百分比不适用，不能判定测量系统理想')
   if any(c['clamped'] for c in result['components']):warnings.append('矩估计出现负方差分量，原始估计保留、呈现值截为0；不自动合并交互或改变模型')
  except (ArithmeticError,ValueError,OverflowError):issues.append('数值尺度超出当前试算范围，未呈现失真结果');result=None
 category_counts={str(v):sum(p.get('value')==v for p in points if finite(p.get('value'))) for v in (0,1)} if study.get('unit')=='bool' else {}
 return dict(study=study,spec=spec,instrument=instrument,calibration=cal,as_of=cutoff,state='paused' if issues else 'trial',issues=list(dict.fromkeys(issues)),warnings=warnings,points=points,members=raw_members,matrix=matrix,result=result,
  coverage=dict(planned=math.prod(dimensions) if all(type(n) is int and n>0 for n in dimensions) else None,registered=len(points),eligible=sum(p['eligible'] for p in points),held=sum(not p['eligible'] for p in points),cells=len(matrix),invalid_cells=sum(not c['valid'] for c in matrix)),
  category_counts=category_counts,tolerance=band,rule_version=RULE_VERSION,formal_qualification=False,cp=None,cpk=None,notice=NOTICE,
  model_policy='保留样件×操作员交互的平衡交叉随机效应ANOVA；不做P值筛选、交互合并、置信区间或嵌套/破坏性分析。%方差为方差/总方差，%研究变异为SD/总SD，二者不能混用。')
