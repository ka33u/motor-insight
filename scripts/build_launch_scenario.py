"""Prepare detailed synthetic XLSX inputs without writing business records."""
import json
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from app import launch, order_baseline_data
from app.launch_schema import DATASETS
from app.launch_contract import KINDS, COUNTS, bundle_hash, issues
from app.models import Record
from app.schema import SCHEMAS


def main():
    refs = {ds: {r.business_key: r.values for r in Record.objects.filter(dataset=ds)} for ds in ('tools', 'production_resources', 'employees')}
    parents = {(i,p): order_baseline_data.load(f'OB-261001-{i:03}',p) for i in (1,4,8) for p in ('due','priority')}
    base = parents[1,'due']
    raw = base['parent']['parent']['base']['tables']
    links = {r['job_id']:r for r in base['result']['links']}
    task_map = {r['id']:r for r in raw['schedule_tasks']}
    pairs = sorted({(r['job_id'],r['route_id']) for r in raw['schedule_tasks']})
    names = ['现有台账投产缺口','文件版本与要求不符','开工质量条件受限','工装借用占据试排时间','指定文件尚未登记','漏列工序质量条件','文件有效期未覆盖加工','BOM基线差异尚未重核','缺人导致任务时间未形成','输入摘要不符暂停']
    all_tables = {ds:[] for ds in DATASETS}
    for n,name in enumerate(names,1):
        key=f'LR-261001-{n:03}'; baseline_no={8:8,9:4}.get(n,1)
        study=dict(id=key,name=name,baseline_id=f'OB-261001-{baseline_no:03}',assessed_at='2026-10-01T18:00:00',owner_id='E00001',
                   basis='自编投产条件矩阵与登记资料。原工装台账保持不变；固定原试排时点进行核对，不证明真实现场条件或业务批准。')
        t={ds:[] for ds in DATASETS[1:]}
        common=dict(study_id=key,registered='2026-10-01T16:00:00',valid_from='2026-10-01T00:00:00',valid_until='2026-10-06T00:00:00',owner_id='E00067',reference='SIM-LAUNCH-'+str(n),note='自编模拟登记，文件号不是原件审阅或现场批准证据。')
        for i,(job_id,route_id) in enumerate(pairs,1):
            link=links[job_id];group=f'{key}-G{i:03}';doc=f'{key}-D{i:03}';qc=f'{key}-Q{i:03}'
            for j,(kind,subject) in enumerate(zip(KINDS,(group,doc,qc)),1):
                t['launch_requirements'].append(dict(id=f'{key}-R{i:03}-{j}',study_id=key,job_id=job_id,route_id=route_id,kind=kind,applicable=True,subject=subject,version='A.01',uses_per_unit=1 if kind=='工装' else 0,
                                                     reason='每个试排工序明确核对三类登记；每台一次为自编计次假设，须由现场验证。'))
            t['launch_documents'].append(dict(common,id=doc,document_no=f'WI-{link["product_id"]}-{i:03}',product_id=link['product_id'],route_id=route_id,version='A.01',status='已发布'))
            t['launch_clearances'].append(dict(common,id=qc,work_order_id=link['work_order_id'],route_id=route_id,version='A.01',status='具备登记条件',owner_id='E00185',note='合成开工质量条件登记；不代替首件实测、工序检验批准或整机放行。'))
            equipment={refs['production_resources'][o['resource_id']]['equipment_id'] for o in raw['schedule_options'] if (task_map[o['task_id']]['job_id'],task_map[o['task_id']]['route_id'])==(job_id,route_id)}
            tools=sorted([r for r in refs['tools'].values() if r['equipment_id'] in equipment],key=lambda r:r['id'])
            for j,tool in enumerate(tools,1):
                t['launch_tool_fits'].append(dict(common,id=f'{key}-F{i:03}-{j}',group=group,tool_id=tool['id'],product_id=link['product_id'],route_id=route_id,version='A.01',status='配套有效',owner_id='E00076',note='配套关系为自编假设；不能覆盖原工具状态、到期日或已超维护次数。'))
        target=pairs.index(('SP-261002-001-B002','GY-00015-01'))
        if n==2:t['launch_documents'][target]['version']='A.02'
        if n==3:t['launch_clearances'][target].update(status='限制开工',note='模拟首件条件尚待质量岗位复核；本行不是实际检验结论。')
        if n==4:t['launch_tool_blocks'].append(dict(id=key+'-B001',study_id=key,tool_id='GJ-0001',started='2026-10-02T00:00:00',ended='2026-10-06T00:00:00',registered='2026-10-01T15:00:00',owner_id='E00076',reason='模拟借用其他任务，全区间不可用'))
        if n==5:t['launch_requirements'][target*3+1]['subject']='WI-SIM-UNREGISTERED-001'
        if n==6:t['launch_requirements'].pop()
        if n==7:t['launch_documents'][target]['valid_until']='2026-10-02T08:01:00'
        study.update({f:len(t[ds]) for ds,f in COUNTS.items()})
        study['content_hash']='0'*64 if n==10 else bundle_hash(study,t)
        all_tables['launch_studies'].append(study)
        for ds,rows in t.items():all_tables[ds].extend(rows)
    profiles=[]
    for study in all_tables['launch_studies']:
        t={ds:[r for r in all_tables[ds] if r['study_id']==study['id']] for ds in DATASETS[1:]}
        for p in ('due','priority'):
            result=launch.analyze(study,t,parents[int(study['baseline_id'][-3:]),p],refs,'2026-10-01T18:00:00')
            profiles.append(dict(id=study['id'],policy=p,state=result['state'],summary=result['summary'],issues=result['issues']))
            (ROOT/f'data/launch_board_{study["id"][-3:]}_{p}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    for ds,rows in all_tables.items():
        for row in rows:assert not issues(ds,row),(ds,row['id'],issues(ds,row))
    output=dict(schemas={ds:SCHEMAS[ds] for ds in DATASETS},tables=all_tables,profiles=profiles)
    (ROOT/'data/launch_scenario.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(rows=sum(map(len,all_tables.values())),tables={ds:len(rows) for ds,rows in all_tables.items()},profiles=profiles),ensure_ascii=False))


if __name__=='__main__':main()
