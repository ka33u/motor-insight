"""Create explicit synthetic device exports from existing Excel-imported facts; never changes facts."""
import os,sys,io,csv,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app.device_files import HEADERS
out=ROOT/'outputs/device_samples';out.mkdir(exist_ok=True)
retest=Record.objects.filter(dataset='test_sessions',values__attempt=2).order_by('business_key').first().values
sessions=list(Record.objects.filter(dataset='test_sessions',values__unit_id__in=[retest['unit_id'],'M260921000097']).order_by('business_key'))
rows=[]
for r in sessions:
    s=r.values;u=Record.objects.get(dataset='units',business_key=s['unit_id']).values
    for m in Record.objects.filter(dataset='measurements',values__session_id=s['id']).order_by('business_key').values_list('values',flat=True):
        rows.append({**{k:s[k] for k in ['unit_id','equipment_id','tested','spec_version']},**{k:u[k] for k in ['work_order_id','product_id']},'session_id':s['id'],'measurement_id':m['id'],**{k:m[k] for k in ['spec_id','raw_value','raw_unit','value','unit','result']}})
def write_csv(name,rr):
    stream=io.StringIO();w=csv.DictWriter(stream,HEADERS);w.writeheader();w.writerows(rr);p=out/name;p.write_bytes(stream.getvalue().encode('utf-8-sig'));return p
good=write_csv('01_模拟试验台_首测复测与漏项.csv',rows)
badrows=[dict(r) for r in rows if r['session_id']==retest['id']];badrows[0]['unit_id']='M260921999999';badrows[0]['raw_unit']='错误单位';bad=write_csv('02_模拟试验台_错配待核对.csv',badrows)
manual=out/'03_模拟现场检测补充记录.txt';manual.write_text(f"合成模拟补充记录，不是真实设备原件。\n会话：{retest['id']}\n电机SN：{retest['unit_id']}\n设备：{retest['equipment_id']}\n检测时间：{retest['tested']}\n用途：演练非结构化文件的人工关联、撤销与重新核对；不代替质量放行。\n",encoding='utf-8')
manifest={'synthetic':True,'derived_from':'当前已经由Excel导入的模拟Record；这是演练导出，不是真实检测设备采集证据','sessions':[r.values for r in sessions],'rows':len(rows),'files':[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size} for p in [good,bad,manual]]}
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');print(json.dumps(manifest,ensure_ascii=False))
