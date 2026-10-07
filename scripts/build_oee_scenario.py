"""Ten explicit synthetic capture cases, with hourly production classifications."""
import json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import oee
from app.schema import SCHEMAS
from app.models import Record
from app.oee_schema import DATASETS
def scenario(resource,products):
 tables={ds:[] for ds in DATASETS};profiles=[]
 names=['完整单配置采集','停止重叠与休息外片段','混配置分窗采集','完整采集但零产出','未登记理想节拍','产出分类未确认','班次采集未闭合','计划窗口重叠','晚于业务截止的采集','无计划生产窗口']
 for number,name in enumerate(names,1):
  key=f'OE-260925-{number:03}';date='2026-10-02' if number==9 else '2026-09-25';study=dict(id=key,name=name,resource_id=resource['id'],version='OEE-CAPTURE-SIM-V1',capture_state='未闭合' if number==7 else '完整',scope='终检独立资源位白班，两段计划生产；案例彼此独立，不能合成全厂产出。',assumptions='全部窗口、停止、节拍和报产为独立合成采集；理想90/120秒每台不来自真实技术标准。登记时刻不是单台加工时刻；首次经过只计一次，返工后通过不补入首次良品。',reference=f'SIM-OEE-260925-{number:03}');tables['oee_studies'].append(study)
  if number!=10:
   for wi,(start,end) in enumerate([('08:00:00','12:00:00'),('13:00:00','16:00:00')],1):
    product='CP.00002.A' if number==3 and wi==2 else 'CP.00001.A';wid=key+f'-W{wi:02}'
    tables['oee_windows'].append(dict(id=wid,study_id=key,product_id=product,started=date+'T'+start,finished=date+'T'+end,unit='台',basis='合成计划生产窗口；12至13点未计划生产，排除。'))
    if number!=4:
     for j in range(4 if wi==1 else 3):
      total=25 if wi==1 else 20;good=total-(1 if j<3 else 0)-(1 if j<2 else 0);rework=1 if j<3 else 0;scrap=1 if j<2 else 0;unknown=1 if number==6 and wi==1 and j==0 else 0
      tables['oee_outputs'].append(dict(id=key+f'-P{wi}{j+1:02}',study_id=key,window_id=wid,reported=date+f'T{(8 if wi==1 else 13)+j:02}:59:00',unit='台',total_qty=total,good_first_qty=good-unknown,rework_qty=rework,scrap_qty=scrap,unknown_qty=unknown,basis='按关联窗口登记一次首次经过与互斥分类；合成小时汇总，不代表实际单台加工时刻。'))
   if number==8:tables['oee_windows'].append({**tables['oee_windows'][-2],'id':key+'-W03','started':date+'T09:00:00','finished':date+'T11:00:00','basis':'刻意登记重叠，用于暂停核对。'})
   for ei,(a,b,kind) in enumerate([('08:00:00','08:15:00','换型'),('10:00:00','10:20:00','故障'),('14:00:00','14:25:00','待料')],1):tables['oee_events'].append(dict(id=key+f'-E{ei:02}',study_id=key,started=date+'T'+a,finished=date+'T'+b,kind=kind,reference=key+f'-REF{ei:02}',basis='独立合成停止记录；窗口内停止计损失，不从计划生产分母中扣除。'))
   if number==2:
    for ei,a,b,kind in [(4,'10:10:00','10:35:00','其他停止'),(5,'11:50:00','12:10:00','故障')]:tables['oee_events'].append(dict(id=key+f'-E{ei:02}',study_id=key,started=date+'T'+a,finished=date+'T'+b,kind=kind,reference=key+f'-REF{ei:02}',basis='合成重叠或休息外片段，原因时长不相加；停止合计按窗口交集并集。'))
   if number!=5:
    for ci,product in enumerate(sorted({w['product_id'] for w in tables['oee_windows'] if w['study_id']==key}),1):tables['oee_cycles'].append(dict(id=key+f'-C{ci:02}',study_id=key,product_id=product,seconds_per_unit=120.0 if product=='CP.00002.A' else 90.0,unit='台',method='独立合成理想条件假设',basis='模拟假设，不以历史平均工时替代理想节拍，实际节拍须技术与生产确认。'))
  local={ds:[r for r in tables[ds] if r.get('study_id')==key] for ds in DATASETS[1:]}
  for field,ds in [('window_count','oee_windows'),('event_count','oee_events'),('cycle_count','oee_cycles'),('output_count','oee_outputs')]:study[field]=len(local[ds])
  result=oee.analyze(study,local,resource,products,'2026-10-01T18:00:00');profiles.append(dict(id=key,name=name,state=result['state'],summary=result['summary'],issues=result['issues']))
 return dict(synthetic=True,tables=tables,schemas={k:SCHEMAS[k] for k in DATASETS},profiles=profiles)
def main():
 resource=Record.objects.get(dataset='production_resources',business_key='SB-08-01-W01').values;products={r.business_key:r.values for r in Record.objects.filter(dataset='products')};data=scenario(resource,products);(ROOT/'data/oee_scenario.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dict(counts={k:len(v) for k,v in data['tables'].items()},profiles=data['profiles']),ensure_ascii=False))
if __name__=='__main__':main()
