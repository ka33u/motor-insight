"""Generate synthetic batch date inputs; business facts are imported from XLSX only."""
import os,sys,json,copy
from pathlib import Path
from datetime import date,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import analytics,supply,inventory_age
from app.schema import SCHEMAS
data=analytics.tables();stock=supply.SupplyData(data);day=date.fromisoformat(analytics.AS_OF[:10]);materials=supply.ix(data['materials']);tables={ds:[] for ds in inventory_age.DATASETS}
for j,lot in enumerate(stock.lots,1):
 if j%41==0:continue
 chemical=materials[lot['material_id']]['category']=='漆料'
 first=day-timedelta(days=[45,75,125,200,410][j%5]) if lot['_opening'] else date.fromisoformat(min(m['occurred'][:10] for m in lot['_moves']))
 mode='待核实' if chemical and j%17==0 else '固定日期' if chemical else '不适用'
 expires=(day+timedelta(days=[-20,-1,0,7,30,100][j%6])).isoformat() if mode=='固定日期' else None
 r={'id':f'BZ260926{j:05d}-V01','material_id':lot['material_id'],'lot':lot['lot'],'version':1,'supersedes_id':None,'registered':'2026-09-26T09:00:00','manufactured':(first-timedelta(days=70 if chemical else 30)).isoformat(),'first_stock_date':None if j%29==0 else first.isoformat(),'expires':expires,'expiry_mode':mode,'document_no':('模拟补录凭据-'+lot['_opening'][0]['id']) if lot['_opening'] else lot['_moves'][0]['id'],'owner_id':'E00011','voided':False,'note':'全为合成日期资料；依据号仅为模拟登记，不证明原件核验；首次入库日期不等同期初日。'}
 tables['inventory_lot_dates'].append(r)
opening=[r for r in tables['inventory_lot_dates'] if any(l['_opening'] and l['material_id']==r['material_id'] and l['lot']==r['lot'] for l in stock.lots)]
for j,r in enumerate(opening[:10]):
 extra={'id':r['id'].replace('V01','V02'),'version':2,'supersedes_id':r['id'],'registered':'2026-09-28T10:00:00','note':'合成日期资料更正，保留首版；未修改期初或库存流水。'}
 if j<6 and r['first_stock_date']:extra['first_stock_date']=(date.fromisoformat(r['first_stock_date'])+timedelta(days=7)).isoformat()
 elif j<8:extra.update(registered='2026-10-02T10:00:00',note='合成截止后版本，当前快照不采用。')
 else:extra.update(voided=True,note='合成作废版本，不参与有效日期选择。')
 tables['inventory_lot_dates'].append(copy.deepcopy(r)|extra)
for j,m in enumerate(data['materials'],1):
 chemical=m['category']=='漆料'
 r={'id':f'KLGZ260925{j:03d}-V01','material_id':m['id'],'version':1,'supersedes_id':None,'effective_from':'2026-09-01','registered':'2026-09-25T09:00:00','age_limit_days':[60,90,120][j%3],'warning_days':14 if chemical else None,'expiry_required':chemical,'owner_id':'E00011','status':'模拟确认','reason':'合成关注阈值，非行业标准或正式制度；漆料有效期仅为本演练假设。'}
 tables['inventory_age_policies'].append(r)
base=tables['inventory_age_policies'][:]
for j,r in enumerate(base[:5]):
 extra={'id':r['id'].replace('V01','V02'),'version':2,'supersedes_id':r['id'],'effective_from':'2026-09-27','registered':'2026-09-27T10:00:00','age_limit_days':180,'reason':'合成规则更正，按截止日采用有效版本，不重写历史登记。'}
 if j==3:extra.update(effective_from='2026-10-02',registered='2026-10-02T09:00:00',reason='合成未来生效版本，当前不采用。')
 if j==4:extra.update(status='草稿',reason='合成草稿版本，当前不采用。')
 tables['inventory_age_policies'].append(copy.deepcopy(r)|extra)
notice='全部为合成批次日期和规则。首次入库日期单独登记，不用期初日推算；包含资料缺失、待核实、已更正、作废与截止后版本，漆料设模拟有效期及临期阈值。库龄高不等于呆滞；已导入流水未见出库不代表完整历史无领用。FIFO/FEFO仅为参考，不预留、不改库存、不自动冻结或批准领料。'
scenario={'schema_version':1,'as_of':analytics.AS_OF,'seed':'inventory-age-v1','notice':notice,'schemas':{ds:SCHEMAS[ds] for ds in inventory_age.DATASETS},'tables':tables}
(ROOT/'data/inventory_age_scenario.json').write_text(json.dumps(scenario,ensure_ascii=False,indent=2));print(json.dumps({ds:len(rows) for ds,rows in tables.items()},ensure_ascii=False))
