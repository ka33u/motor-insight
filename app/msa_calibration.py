"""Existing complete-version calibration register, scoped to a study window."""
from .metrology import resolve_versions,clock
def context(instrument,rows,start,end,cutoff):
 issues=[];selected=None;candidates=[]
 if not instrument:return dict(state='missing',selected=None,issues=['仪器身份缺失'])
 if not clock(start) or not clock(end) or not start<end:return dict(state='invalid',selected=None,issues=['试验时间窗口无效'])
 if not clock(instrument.get('active_from')) or instrument['active_from']>start or instrument.get('retired') and (not clock(instrument['retired']) or instrument['retired']<=end):issues.append('仪器启停窗口不覆盖试验')
 for g in resolve_versions(rows,cutoff,['instrument_id']):
  if g['issues']:issues.extend(g['issues']);continue
  c=g['selected']
  if not c or not clock(c.get('performed')):issues.append('校准时间未核实');continue
  if start<c['performed']<=end:issues.append('试验窗口内有校准变更，请拆分并核对')
  if c['performed']<=start:candidates.append(c)
 if candidates:
  at=max(c['performed'] for c in candidates);latest=[c for c in candidates if c['performed']==at]
  if len(latest)!=1:issues.append('最近校准同刻登记冲突')
  else:selected=latest[0]
 else:issues.append('没有截止前且早于试验的校准登记')
 state='unknown'
 if selected:
  c=selected;state='registered'
  if c['status']!='已登记':issues.append('最近校准登记已撤销')
  if not clock(c.get('valid_from')) or not clock(c.get('valid_until')) or not c['performed']<=c['valid_from']<c['valid_until'] or not c['valid_from']<=start<end<c['valid_until']:issues.append('最近校准登记窗口未覆盖完整试验')
  if c.get('result')!='符合登记范围':issues.append('最近校准不符合登记范围')
  if (c.get('parameter'),c.get('unit'))!=(instrument.get('parameter'),instrument.get('unit')):issues.append('校准登记项目或单位与仪器不同')
  if not c.get('certificate_no') or not c.get('reference'):issues.append('校准登记依据不完整')
  if not clock(c.get('registered')) or c['registered']<c['performed']:issues.append('校准登记时间无效')
 if issues:state='unavailable'
 return dict(state=state,selected=selected,issues=list(dict.fromkeys(issues)),notice='仅核对既有合成校准登记，不证明真实证书或测量能力。')
