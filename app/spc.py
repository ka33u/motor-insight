"""Fixed-plan I-MR trial analysis, distinct from acceptance and capability.

Consecutive means consecutive declared acquisition sequence. Missing/held
observations break MR pairs; a selected page never refits baseline limits.
"""
from collections import Counter,defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics

MIN_BASELINE=20  # Pilot policy, not a universal stability/sample-size standard.
MAX_POINTS=10000
D2=1.128
D4=3.267
RULE_VERSION='SPC-I-MR-TRIAL.01'
NOTICE='受控合成试验的候选控制图；测量系统、独立性、实际工况及稳定性尚未获工厂审定。规则信号只作调查线索，不计算正式Cp/Cpk，不改变首检/复测、放行或发货。'


def finite(value):return type(value) in (int,float) and math.isfinite(value)
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def rule_hash():
    h=hashlib.sha256()
    for name in ('spc.py','spc_schema.py','spc_source_contract.py','spc_data.py'):
        h.update((Path(__file__).parent/name).read_bytes())
    return h.hexdigest()


def time(value):
    try:
        parsed=datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is None and parsed.isoformat()==value else None
    except (ValueError,TypeError):return None


def analyze(study,observations,spec,units,events=(),cutoff='2026-10-01T18:00:00'):
    """All records retained; analytical exclusions have explicit point reasons."""
    cutoff_time=time(cutoff)
    if cutoff_time is None:raise ValueError('分析截止格式无效')
    study=dict(study);rows=[dict(r) for r in observations];issues=[]
    def issue(message):
        if message not in issues:issues.append(message)
    expected=study.get('expected_points');end=study.get('baseline_end')
    safe_expected=type(expected) is int and 1<=expected<=MAX_POINTS
    safe_end=type(end) is int and 1<=end<=(expected if safe_expected else 0)
    if not safe_expected:issue('计划点数无效或超过当前10000点试算上限')
    if not safe_end:issue('固定基线末序号无效')
    if not spec or spec.get('product_id')!=study.get('product_id') or spec.get('id')!=study.get('spec_id'):issue('规范项目与配置关系待核实')
    spec=spec or {}
    if study.get('unit')!=spec.get('unit'):issue('试验与规范单位不同')
    if spec.get('unit')=='bool':issue('二值项目不能使用当前I-MR单值模型')
    if study.get('method')!='I_MR':issue('当前试验尚未选定受支持的I-MR方法')
    if study.get('order_basis') not in {'设备计数（模拟）','人工顺序登记（模拟）'}:issue('没有可核验的实际采样顺序依据')
    pair_supported=study.get('method')=='I_MR' and spec.get('unit')!='bool' and study.get('order_basis') in {'设备计数（模拟）','人工顺序登记（模拟）'}
    started=time(study.get('started'));finished=time(study.get('finished'))
    if started is None or started>cutoff_time:issue('试验开始时间无效或晚于截止')
    if study.get('status')=='已结束' and (finished is None or started and finished<=started):issue('试验结束时间待核实')
    limits_valid=True
    for field in ('lsl','usl'):
        if spec.get(field) is not None and not finite(spec[field]):limits_valid=False
    if spec.get('lsl') is not None and spec.get('usl') is not None and limits_valid and spec['lsl']>spec['usl']:limits_valid=False
    if not limits_valid:issue('产品规范限值无效')
    seq_counts=Counter(r.get('sequence') for r in rows if type(r.get('sequence')) is int)
    id_counts=Counter(r.get('id') for r in rows)
    unit_counts=Counter(r.get('unit_id') for r in rows if r.get('state')!='作废')
    ordered=sorted(rows,key=lambda r:(r['sequence'] if type(r.get('sequence')) is int else MAX_POINTS+1,str(r.get('id',''))))
    points=[];by_sequence=defaultdict(list);previous_time=None
    for r in ordered:
        reasons=[];sequence=r.get('sequence');measured=time(r.get('measured'));registered=time(r.get('registered'))
        if type(sequence) is not int or sequence<=0 or safe_expected and sequence>expected:reasons.append('序号不在计划范围')
        elif seq_counts[sequence]!=1:reasons.append('同一试验序号重复')
        if id_counts[r.get('id')]!=1:reasons.append('观测身份重复')
        if r.get('study_id')!=study.get('id'):reasons.append('观测不属于本试验')
        if r.get('state')!='有效':reasons.append('观测状态为'+str(r.get('state') or '未知'))
        if not finite(r.get('value')):reasons.append('缺少有限标准数值')
        elif spec.get('unit')=='bool' and r['value'] not in (0,1):reasons.append('二值项目数值不在0/1范围')
        if r.get('unit')!=study.get('unit'):reasons.append('标准单位不同')
        if r.get('method_version')!=study.get('measurement_method'):reasons.append('试验方法版本不同')
        if r.get('replicate')!=1 or unit_counts.get(r.get('unit_id'),0)>1:reasons.append('重复样件，独立性待核实')
        u=units.get(r.get('unit_id'))
        if not u or u.get('product_id')!=study.get('product_id'):reasons.append('SN配置关系待核实')
        if measured is None:reasons.append('缺少有效实际测量时间')
        else:
            if measured>cutoff_time:reasons.append('测量晚于截止')
            if started and measured<started or finished and measured>finished:reasons.append('测量不在试验时间内')
            if time(spec.get('effective')+'T00:00:00' if isinstance(spec.get('effective'),str) else None) and measured.date().isoformat()<spec['effective']:reasons.append('规范尚未生效')
            if u and time(u.get('assembly_at')) and measured<time(u['assembly_at']):reasons.append('测量早于装配')
            if previous_time and measured<previous_time:reasons.append('按序号的实际测量时间倒序')
            previous_time=measured
        if registered is None or registered>cutoff_time or measured and registered<measured:reasons.append('登记时间无效或不在已知截止内')
        value=r.get('value');outside=None
        if finite(value) and r.get('unit')==spec.get('unit') and limits_valid and any(spec.get(k) is not None for k in ('lsl','usl')):
            outside=bool(spec.get('lsl') is not None and value<spec['lsl'] or spec.get('usl') is not None and value>spec['usl'])
        point={**r,'segment':'baseline' if safe_end and type(sequence) is int and sequence<=end else 'monitor',
               'eligible':not reasons,'reasons':list(dict.fromkeys(reasons)),'spec_outside':outside,
               'mr':None,'i_signal':None,'mr_signal':None}
        points.append(point)
        if type(sequence) is int:by_sequence[sequence].append(point)
    for p in points:
        before=by_sequence.get(p['sequence']-1,[]) if type(p.get('sequence')) is int else []
        if pair_supported and p['eligible'] and len(before)==1 and before[0]['eligible']:
            mr=abs(p['value']-before[0]['value'])
            if math.isfinite(mr):p['mr']=mr
            else:p['eligible']=False;p['reasons'].append('移动极差溢出')
    baseline=[p for p in points if p['segment']=='baseline'];baseline_valid=[p for p in baseline if p['eligible']]
    baseline_gaps=[i for i in range(1,end+1) if len(by_sequence.get(i,[]))!=1] if safe_end else []
    if baseline_gaps:issue('固定基线存在缺号或重复序号')
    if len(baseline_valid)!=len(baseline):issue('固定基线含待核对或不适用观测')
    if len(baseline_valid)<MIN_BASELINE:issue('固定基线不足本项目20点试算门槛；不说明过程稳定')
    mr_values=[p['mr'] for p in baseline_valid if p['mr'] is not None]
    if len(mr_values)!=max(0,len(baseline_valid)-1):issue('固定基线缺少完整相邻移动极差')
    model_limits=None
    if not issues:
        center=statistics.mean(p['value'] for p in baseline_valid);mrbar=statistics.mean(mr_values)
        sigma=mrbar/D2
        trial=dict(center=center,mr_mean=mrbar,sigma_estimate=sigma,i_lcl=center-3*sigma,
                   i_ucl=center+3*sigma,mr_lcl=0.0,mr_ucl=D4*mrbar)
        if not all(math.isfinite(v) for v in trial.values()):issue('派生控制限溢出')
        elif mrbar==0:issue('固定基线移动极差为零，当前变异估计退化')
        else:model_limits=trial
    if model_limits:
        for p in points:
            if not p['eligible']:continue
            p['i_signal']=p['value']<model_limits['i_lcl'] or p['value']>model_limits['i_ucl']
            p['mr_signal']=None if p['mr'] is None else p['mr']>model_limits['mr_ucl']
    signal_counts={seg:dict(i=sum(p['i_signal'] is True for p in points if p['segment']==seg),
                            mr=sum(p['mr_signal'] is True for p in points if p['segment']==seg))
                   for seg in ('baseline','monitor')}
    gaps=[i for i in range(1,expected+1) if not by_sequence.get(i)] if safe_expected else []
    safe_events=[]
    for e in events:
        if e.get('study_id')==study.get('id'):
            when=time(e.get('occurred'));known=time(e.get('registered'))
            safe_events.append({**e,'context_valid':bool(when and known and when<=known<=cutoff_time and
                                started and started<=when and (not finished or when<=finished)),
                                'causal_claim':False})
    return dict(study=study,spec=spec,points=points,events=safe_events,as_of=cutoff,
                state='trial' if model_limits else 'paused',issues=issues,limits=model_limits,
                baseline_policy=dict(minimum=MIN_BASELINE,baseline_end=end,baseline_points=len(baseline_valid),
                                     mr_pairs=len(mr_values),is_project_policy=True,refit_on_filter=False),
                coverage=dict(planned=expected,recorded=len(points),eligible=sum(p['eligible'] for p in points),
                              held=sum(not p['eligible'] for p in points),missing_sequences=gaps,
                              spec_outside=sum(p['spec_outside'] is True for p in points)),
                signal_counts=signal_counts,rule_version=RULE_VERSION,notice=NOTICE,
                category_counts={str(v):sum(p['eligible'] and p['value']==v for p in points) for v in (0,1)} if spec.get('unit')=='bool' else None,
                cp=None,cpk=None,formal_qualification=False)
