"""Rebuild a new publication-only checkout from Excel, without the author's database."""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--target',type=Path,required=True);args=parser.parse_args();target=args.target.resolve()
    assert not target.exists(),'A fresh directory is required; never overwrite another rehearsal.'
    names=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=ROOT).split(b'\0')
    target.mkdir(parents=True)
    for value in names:
        if not value:continue
        relative=Path(value.decode());source=ROOT/relative
        assert source.is_file() and not source.is_symlink()
        destination=target/relative;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
    env=os.environ.copy()
    for key in ('PYTHONPATH','MOTOR_SQLITE_PATH','DJANGO_SETTINGS_MODULE'):env.pop(key,None)
    env['PYTHONNOUSERSITE']='1'
    subprocess.run([sys.executable,str(target/'scripts/bootstrap_demo.py')],cwd=target,env=env,check=True)
    os.environ['MOTOR_SQLITE_PATH']=str(target/'data/platform.sqlite3');os.environ['DJANGO_SETTINGS_MODULE']='config.settings';sys.path.insert(0,str(target))
    import django;django.setup()
    from app.models import Record,AnalysisModel,AnalysisModelChange,Topic,MetricVersion
    from app.finite_schedule import digest
    expected=json.loads((ROOT/'data/model-change-before/manifest.json').read_text())
    facts=list(Record.objects.order_by('dataset','business_key').values('dataset','business_key','record_hash'))
    assert len(facts)==expected['record_count']==230802 and digest(facts)==expected['record_digest']
    assert (AnalysisModel.objects.count(),Topic.objects.count(),MetricVersion.objects.count(),AnalysisModelChange.objects.count())==(52,21,11,0)
    proof=dict(success=True,fresh_checkout=True,fresh_xlsx_replay=True,workbooks=41,records=230802,all_business_facts_exact=True,
        analysis_models=52,topics=21,metric_versions=11,model_change_history=0,browser_acceptance=False,business_inputs='Normal Excel stage and commit only')
    (ROOT/'data/model_changes_bootstrap.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))

if __name__=='__main__':main()
