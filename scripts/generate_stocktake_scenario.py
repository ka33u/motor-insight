"""Create synthetic Excel inputs from the existing imported stock ledger."""
import os,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app import analytics,supply,stocktake
from app.schema import SCHEMAS
stock=supply.SupplyData(analytics.tables());tables={ds:[] for ds in stocktake.DATASETS}
for run_no,date,prefix,kind in [(1,'2026-09-23','CK01-A','范围全盘'),(2,'2026-09-25','CK01-A01','指定抽盘')]:
    rid='PD'+date[2:].replace('-','')+f'{run_no:03d}';lots=[r for r in stock.lots if r['location'].startswith(prefix)]
    # Full-scope plan deliberately omits one known lot and includes an unbooked lot.
    if run_no==1:lots=lots[:-1]+[{**lots[-1],'lot':'RM260923待查001','balance_qty':None}]
    run={'id':rid,'kind':kind,'location_prefix':prefix,'book_at':date+'T07:00:00','freeze_start':date+'T07:00:00','freeze_end':date+'T12:00:00','line_count':len(lots),'owner_id':'E00011','status':'已登记' if run_no==1 else '进行中','freeze_evidence':'合成封库登记 '+rid+'；用于账实核对演练，实际流水完整性待核实'}
    tables['stocktake_runs'].append(run)
    for j,lot in enumerate(lots,1):
        lid=rid+f'-{j:04d}';book=lot['balance_qty'];unit=lot['unit'];qty=book if book is not None else 6
        if j%17==0:qty=None
        elif j%13==0:qty=0
        elif j%7==0:qty=max(0,round(qty-(3 if unit=='件' else 1.25),4))
        elif j%11==0:qty=round(qty+(2 if unit=='件' else .75),4)
        line={'id':lid,'run_id':rid,'material_id':lot['material_id'],'lot':lot['lot'],'location':lot['location'],'unit':unit,'initial_qty':qty,'counted':date+'T08:00:00' if qty is not None else None,'counter_id':'E00012' if qty is not None else None,'note':'模拟未盘对象；不能填零代替未盘' if qty is None else '合成实盘登记，按物料批次库位识别；非真实库存'}
        tables['stocktake_lines'].append(line);final_qty=qty;recount_id=None
        if qty is not None and book is not None and qty!=book and j%3!=0:
            rc={'id':lid+'-FP01','line_id':lid,'attempt':1,'qty':book if j%2==0 else qty,'counted':date+'T09:00:00','counter_id':'E00013','voided':False,'reason':'合成独立复盘：重新计数并核对包装标签'}
            tables['stocktake_recounts'].append(rc);final_qty=rc['qty'];recount_id=rc['id']
            if j%5==0:
                second={**rc,'id':lid+'-FP02','attempt':2,'qty':book,'counted':date+'T09:30:00','reason':'合成第二轮复盘，确认首轮漏数'};tables['stocktake_recounts'].append(second);final_qty=book;recount_id=second['id']
        if qty is not None and j%19==0:
            tables['stocktake_recounts'].append({'id':lid+'-FP作废','line_id':lid,'attempt':8,'qty':0,'counted':date+'T09:45:00','counter_id':'E00013','voided':True,'reason':'合成作废示例：错取相邻库位，不参与有效实盘'})
        if qty is not None and book is not None and (qty!=book or j%9==0):
            stale=j%5==0 and recount_id is not None
            tables['stocktake_dispositions'].append({'id':lid+'-CZ01','line_id':lid,'recount_id':lid+'-FP01' if stale else recount_id,'confirmed_qty':qty if stale else final_qty,'recorded':date+'T10:00:00','owner_id':'E00011','status':'复核无差异' if final_qty==book and not stale else '已确认' if j%4==0 else '待调查','method':'复盘核查' if final_qty==book else '调查领退料登记；尚未调整库存','evidence':'合成差异调查登记；旧复盘依据待重新确认' if stale else '合成盘点、包装与领料记录核查；未形成实际账务调整'})
notice='全部为合成盘点数据。范围全盘保留一条未列入计划的账面批次和一条缺账面基准的实物；包含未盘、零数量、盈亏、独立复盘、作废及旧处置依据。盘点截止后没有新增库存流水；模拟封库登记不证明真实现场封库。实盘及处置不调整账面库存。'
scenario={'schema_version':1,'as_of':analytics.AS_OF,'seed':'stocktake-v1','notice':notice,'schemas':{ds:SCHEMAS[ds] for ds in stocktake.DATASETS},'tables':tables}
(ROOT/'data/stocktake_scenario.json').write_text(json.dumps(scenario,ensure_ascii=False,indent=2));print(json.dumps({ds:len(rows) for ds,rows in tables.items()},ensure_ascii=False))
