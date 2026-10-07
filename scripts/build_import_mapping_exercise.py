"""Prepare detailed heterogeneous source values; authoring stays in Artifact JS."""
import copy,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from app.models import Record
from app.schema import SCHEMAS

DEPT='32_字段映射演练'
SHEETS={
 'suppliers':('采购部_供方清单',['供方编号','供方全称','主要供货','所在地区','周期_自然日','供方资格登记']),
 'customers':('销售部_客户资料',['往来客户号','客户全称','市场区域','使用行业','合同账期_天','业务责任人工号']),
 'materials':('仓储部_物料卡片',['料号','材料名称','分类名称','材料规格','基本计量单位','参考单价_分','优先供方编码','安全缓冲数量']),
}
schemas={};tables={};mapping={};canonical={};reference_rows={}
for ds,(name,headers) in SHEETS.items():
 s=copy.deepcopy(SCHEMAS[ds]);s['department']=DEPT;s['label']=name
 rows=[copy.deepcopy(r.values) for r in Record.objects.filter(dataset=ds).order_by('business_key')[:5]]
 canonical[ds]=copy.deepcopy(rows)
 for f in s['fields']:
  if f['reference']:
   for row in rows:
    obj=Record.objects.get(dataset=f['reference'],business_key=row[f['name']]);reference_rows[(obj.dataset,obj.business_key)]=dict(dataset=obj.dataset,values=obj.values)
 for f,header in zip(s['fields'],headers):f['label']=header
 s['fields'].append(dict(name='note',label='个人采集备注',type='str',required=False,reference=None))
 for row in rows:row['note']='合成正式记录；本次用于异构表头及重复识别，备注列明确忽略'
 if ds=='suppliers':
  changed=copy.deepcopy(rows[0]);changed['lead_days']+=1;changed['note']='同供方编号更改周期：必须进入冲突审核，不自动覆盖';rows.append(changed)
 if ds=='customers':
  invalid=copy.deepcopy(rows[0]);invalid['id']=19;invalid['note']='故意使用数字编号：不能推测或补齐前导零';rows.append(invalid)
 schemas[ds]=s;tables[ds]=rows
 mapping[name]=dict(dataset=ds,fields={f['label']:f['name'] for f in s['fields'][:-1]},ignore=['个人采集备注'])
schemas['mapping_personal_notes']=dict(key='mapping_personal_notes',label='个人备注_不导入',department=DEPT,version=1,primary_key='id',fields=[dict(name='id',label='便签号',type='str',required=True,reference=None),dict(name='note',label='私人演练便签',type='str',required=False,reference=None)])
tables['mapping_personal_notes']=[dict(id='NOTE-SIM-001',note='这是模拟个人备注页；需明确选择忽略整页，不猜目标业务表。')]
mapping['个人备注_不导入']={'skip':True};mapping['导入说明']={'skip':True};mapping['字段字典']={'skip':True}
scenario=dict(schema_version=1,as_of='2026-10-01T18:00:00',notice='全部为合成演练，从当前正式模拟台账抽取采购、销售和仓储各5行，另加入1条同号变更、1条非文本编号及1条待忽略便签。不是实际U8/MES导出。只在隔离副本执行演练，不自动更改现有正式事实。编号、整数金额（分）、数值及布尔保留原生类型；非标准表头按显式映射导入。',schemas=schemas,tables=tables)
(ROOT/'data/import_mapping_exercise.json').write_text(json.dumps(scenario,ensure_ascii=False,indent=2))
expected=json.dumps(dict(mapping=mapping,canonical=canonical,references=list(reference_rows.values()),expected_status={'duplicate':15,'conflict':1,'invalid':1},selected_rows=17,ignored_data_rows=1,synthetic=True),ensure_ascii=False,indent=2)
(ROOT/'data/import_mapping_exercise_expected.json').write_text(expected)
(ROOT/'tests/fixtures').mkdir(exist_ok=True)
(ROOT/'tests/fixtures/import_mapping_exercise_expected.json').write_text(expected)
print(json.dumps(dict(data_sheets=4,workbook_rows=18,selected_rows=17,duplicate=15,conflict=1,invalid=1,ignored=1),ensure_ascii=False))
