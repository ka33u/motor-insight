"""Declare only the verified controlled-study increment; no formal capability."""
import copy
from collections import Counter
BASE_GAPS={'L-06':'现有系统尚未形成此项完整可验收页面和业务闭环；须先满足数据前提。',
           'L-13':'新增候选设计，尚未完成采集、计算、页面或业务验收。'}
STATUS='受控采样增量（2026-10-07）：第34份模拟Excel新增10个独立试验、730条观测和10条事件，关联原配置及SN而不补造旧终检顺序。固定基线I-MR候选试算、独立产品公差、基线/监控信号、缺号断点、逐点Excel来源及完整CSV已完成服务端与原生HTTP验证；六岗位读取和金额隐藏、凭据过期/变化、翻页不改基线、二值分类、小样本/零变异/重复/未知顺序暂停均有规则检查。测量系统、独立性和现场工况尚未工厂审定，20点门槛只是项目策略；不计算正式Cp/Cpk、不改变首检复测、放行或业务批准。浏览器渲染、手机交互及浏览器下载仍待验收，真实采集及MSA仍待建设。'
ROW=dict(name='受控采样与I-MR候选试算',question='观测字段、顺序和固定基线是否足够；控制信号与产品超限有何不同？',
         content='声明采样序号、固定基线、I/MR两图、产品限值、缺号/待核对、逐点Excel来源和全部观测CSV',
         action='核对采样与测量系统依据→调查信号/缺口→由质量和工艺审定实际适用性',href='#spc',status=STATUS)
CONTRACT=dict(revision='spc-trial-20261007',state='已验证合成候选试算；不证明真实工厂过程能力或稳定性',
              needs=['L-06','L-13'],raw_datasets=['spc_studies','spc_observations','spc_events'],studies=10,observations=730,events=10,
              source_workbook='34_过程稳定性采样_模拟.xlsx',actual_href='#spc',rule_version='SPC-I-MR-TRIAL.01',
              baseline='每个试验独立声明末序号；翻页或隐藏产品公差不重新估计',
              evidence='同一试验、源行及账号/规则版本绑定；600秒凭据，来源变化暂停下钻或导出',
              limits='产品限值与基线控制限分别显示；缺号或待核对点断开相邻移动极差',
              remaining='真实采样、MSA/独立性/工况、合理子组/其他控制图、正式能力评估、统计规则扩展、业务批准及浏览器/手机验收')

def counts(d):
    result=dict(Counter(n['implementation'] for dom in d['domains'] for n in dom['items']))
    d['planning_summary']['implementation_counts']=result
    d['planning_summary']['presentation_design']['coverage_counts']=result.copy()

def refine_spc(d):
    for dom in d['domains']:
        for n in dom['items']:
            if n['id'] in BASE_GAPS:
                n['implementation']='模拟部分覆盖';n['gap']=STATUS+' '+BASE_GAPS[n['id']]
                n['decision_spec']['implementation']=n['implementation'];n['verified_trial']=copy.deepcopy(CONTRACT)
    page=next(p for p in d['page_blueprints'] if p['id']=='P05')
    marker=' 受控采样增量说明：'
    base=page['status'].split(marker)[0]
    page['status']=base+marker+STATUS
    d['framework']['surfaces']=[s for s in d['framework']['surfaces'] if s['href']!='#spc']+[copy.deepcopy(ROW)]
    d['framework']['spc_trial']=copy.deepcopy(CONTRACT);counts(d);return d

def remove_exact_increment(d):
    assert d['framework']['spc_trial']==CONTRACT
    assert [s for s in d['framework']['surfaces'] if s['href']=='#spc']==[ROW]
    d['framework']['surfaces']=[s for s in d['framework']['surfaces'] if s['href']!='#spc'];d['framework'].pop('spc_trial')
    for dom in d['domains']:
        for n in dom['items']:
            if n['id'] in BASE_GAPS:
                assert n['gap']==STATUS+' '+BASE_GAPS[n['id']] and n['implementation']=='模拟部分覆盖' and n['verified_trial']==CONTRACT
                assert n['decision_spec']['implementation']=='模拟部分覆盖'
                n['implementation']=n['decision_spec']['implementation']='待建设';n['gap']=BASE_GAPS[n['id']];n.pop('verified_trial')
    page=next(p for p in d['page_blueprints'] if p['id']=='P05');suffix=' 受控采样增量说明：'+STATUS
    assert page['status'].endswith(suffix);page['status']=page['status'][:-len(suffix)];counts(d)
