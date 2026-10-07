"""Read-only candidate preparation. Business changes require actual XLSX review."""
import os,sys,json,copy
from pathlib import Path
from datetime import date,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from app.models import Record
from app.schema import SCHEMAS
from app.import_review import snapshot
from app.manufacturing_rules import issues
from scripts.scenario_calendar import work_order_plan

expected={f'MO2609-{i:06}' for i in [208,224,240,256,272,288]}
records=list(Record.objects.filter(dataset='work_orders').select_related('source_row__batch').order_by('business_key'))
bad=[r for r in records if r.values['planned_start']>r.values['planned_end']]
assert {r.business_key for r in bad}==expected,'Expected six original synthetic date inversions; preserve earlier output after review.'
rows=[];changes=[]
for r in bad:
    before=snapshot(r);after=copy.deepcopy(r.values)
    start,end=work_order_plan(date(2026,9,26),date.fromisoformat(after['planned_end'])+timedelta(days=1))
    after['planned_start']=start.isoformat()
    assert end.isoformat()==after['planned_end'] and not issues('work_orders',after)
    assert {k for k in after if after[k]!=r.values[k]}=={'planned_start'}
    assert not Record.objects.filter(dataset='operations',values__work_order_id=r.business_key).exists()
    rows.append(after);changes.append({'before':before,'candidate':after})
schema=copy.deepcopy(SCHEMAS['work_orders']);schema['department']='17_计划日期更正'
payload={'notice':'合成模拟工单日期更正。仅6张未开工工单的计划开工由2026-09-23调整为2026-09-19，计划完工2026-09-22及其他字段保持原值。依据：原生成器在数量上限后复用装配日，造成计划倒置；异常时按计划完工前三天设置开工。三天为演练假设，不表示真实产能已核定。来源：04_计划生产_模拟.xlsx，生产工单第209、225、241、257、273、289行。需在导入界面逐行审核替换，保留原件和原值。','as_of':'2026-10-01T18:00:00','schema_version':'2 / 日期更正1','schemas':{'work_orders':schema},'tables':{'work_orders':rows}}
(ROOT/'data/plan_correction_scenario.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
(ROOT/'data/plan_correction_candidates.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2))
print(json.dumps({'candidates':len(rows),'changed_field':'planned_start','old':'2026-09-23','new':'2026-09-19','planned_end_preserved':'2026-09-22','business_facts_written':False},ensure_ascii=False))
