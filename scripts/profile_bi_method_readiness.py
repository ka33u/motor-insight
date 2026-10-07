"""Readonly, reproducible profile of the frozen synthetic BI workshop example."""
import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def profile():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    import django
    django.setup()
    from app import quality_board as quality
    from app.trace_cases import capture_sources
    data=quality.current()
    filters=quality.filters({'product_id':'CP.00008.A'})
    rows=quality.cohort(data.rows,filters)
    x=quality.distribution(data,rows,'CP.00008.A','JC-CP.00008.A-R-A','first_complete','SB-08-01')
    times=Counter(r['tested'] for r in x['observations'])
    ties=[dict(tested=t,count=n,measurement_ids=[r['id'] for r in x['observations'] if r['tested']==t])
          for t,n in sorted(times.items()) if n>1]
    refs={('test_specs',x['spec']['id']),('products',x['spec']['product_id'])}
    for r in x['observations']:
        refs.update({('measurements',r['id']),('test_sessions',r['session_id']),('units',r['unit_id'])})
    manifest=capture_sources({'sources':[dict(dataset=ds,key=key) for ds,key in sorted(refs)]})
    assert all(not r.get('missing') for r in manifest)
    result=dict(classification='合成Excel导入数据；描述性门槛预检，不是SPC计算或业务认证',
        business_cutoff='2026-10-01T18:00:00',
        database_sha256=hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest(),
        filters=filters,product_id=x['spec']['product_id'],spec_id=x['spec']['id'],
        version=x['spec']['version'],equipment_id=x['equipment_id'],sample=x['sample'],
        sample_note=x['sample_note'],spec=x['spec'],cohort_units=x['cohort_units'],
        stats=x['stats'],excluded=x['excluded'],time_ties=ties,
        tied_observations=sum(g['count'] for g in ties),observations=x['observations'],
        control_limits=None,cp=None,cpk=None,
        calculation_state='暂停：同刻观测没有可核验采样顺序；另需基线与测量系统、工况及过程适用性确认',
        source_manifest=manifest)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='data/bi_method_readiness_sample.json')
    args=parser.parse_args();path=(ROOT/args.output).resolve()
    assert path.is_relative_to(ROOT/'data'), 'Profile outputs belong in data/'
    result=profile()
    if path.exists():
        previous=json.loads(path.read_text())
        if 'source_manifest' not in previous:
            assert previous=={k:v for k,v in result.items() if k!='source_manifest'}
            path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        else:
            assert previous==result, 'Frozen example changed; choose a new output file for review'
    else:path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(success=True,observations=len(result['observations']),
                         excel_source_rows=len(result['source_manifest']),
                         tied_observations=result['tied_observations'],no_business_writes=True)))


if __name__=='__main__':main()
