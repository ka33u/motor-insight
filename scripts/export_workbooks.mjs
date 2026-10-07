import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
// Optional isolated scenario/output paths support importer acceptance fixtures.
const scenario=JSON.parse(await fs.readFile(process.argv[3]||path.join(root,'data/scenario.json'),'utf8'));
const output=process.argv[4]||path.join(root,'outputs/01a0f580-2480-7820-bc97-8ca293421c39');
const previewOutput=process.argv[4]?path.join(output,'previews'):path.join(root,'data/workbook-previews');
await fs.mkdir(output,{recursive:true}); await fs.mkdir(previewOutput,{recursive:true});
const department=process.argv[2];
const reviewSheets=process.env.MOTOR_REVIEW_SHEETS?new Set(process.env.MOTOR_REVIEW_SHEETS.split(',')):null;
if(!department) throw new Error('Pass the exact department from schema metadata');
const selected=Object.values(scenario.schemas).filter(s=>s.department===department);
if(!selected.length) throw new Error('Unknown department');
const book=Workbook.create();
const overview=book.worksheets.add('导入说明');overview.showGridLines=false;
overview.getRange('A2:D2').values=[[department.replace(/^\d+_/,''),'模拟数据','','']];
overview.getRange('A2:D2').format.font={name:'Arial',size:14,bold:true};
overview.getRange('A4:B7').values=[['数据性质',scenario.notice],['业务截止',scenario.as_of+' Asia/Shanghai'],['模板版本',scenario.schema_version],['使用方式','数据页第1行为字段名，每行一条事实。编码按文本，金额以分存储。请保留主键，修改后重新上传审核。']];
overview.getRange('A4:A7').format.font={bold:true,name:'Arial',size:10};
overview.getRange('B4:B7').format.wrapText=true;
overview.getRange('A4:A7').format.columnWidth=19;
overview.getRange('B4:B7').format.columnWidth=82;
overview.getRange('A4:B7').format.rowHeight=40;
overview.getRange('A4:B4').format.rowHeight=72;
if(department==='13_历史应收')overview.getRange('A4:B4').format.rowHeight=100;
if(department==='14_售后过程')overview.getRange('A4:B4').format.rowHeight=100;
if(['25_采购承诺','26_来料流程'].includes(department)){
 overview.getRange('A4:B4').format.rowHeight=118;
 overview.getRange('A4:B7').format.verticalAlignment='center';
 overview.getRange('B7').values=[['完整版本必须覆盖原采购行全部数量；分段行数、段次、前序版本须一致。仅模拟确认且截止前生效、登记的版本可计算；错误版本暂停当前承诺计算。']];
 overview.getRange('A7:B7').format.rowHeight=58;
 if(department==='26_来料流程')overview.getRange('B7').values=[['任务关联到货，完成窗口关联原检验或入库节点；派工≤开始≤结束≤登记。每版为完整登记，缺失、引用错误和版本冲突暂停分解，不修改原实物事实。']];
}
if(department==='27_来料特性'){
 overview.getRange('A4:B4').format.rowHeight=144;
 overview.getRange('A4:B7').format.verticalAlignment='center';
 overview.getRange('A7:B7').format.rowHeight=70;
 overview.getRange('B7').values=[['规范日期为左闭右开区间。计划关联原来料检验；登记区分测量与录入时间。每个样本特性一行，缺项留空，选检项可不测。全部限值仅为演示，样本判定不修改原批次批准。']];
}
if(department==='28_材质证明'){
 overview.getRange('A4:B4').format.rowHeight=128;
 overview.getRange('A4:B7').format.verticalAlignment='center';
 overview.getRange('A7:B7').format.rowHeight=70;
 overview.getRange('B7').values=[['证明台账、供方特性声明与到货关联分别保留。平台标识对应已归档原件，关联记录按版本追溯；缺失和错误是演练情形。原件内容一致不表示材料批准或供方签章真实。']];
}
if(department==='29_在制流转'){
 overview.getRange('A4:B4').format.rowHeight=144;
 overview.getRange('A4:B7').format.verticalAlignment='center';
 overview.getRange('A7:B7').format.rowHeight=74;
 overview.getRange('B7').values=[['基准按原批次件数登记。每次流转完整列出输入、输出及来源份额；拆合批保留父子关系，部分耗用明确保留剩余件数。SN耗用对应已有装配时点；错误最新版暂停位置判断，不回退。']];
}
if(department==='30_计量校准'){
 overview.getRange('A4:B4').format.rowHeight=144;
 overview.getRange('A4:B7').format.verticalAlignment='center';
 overview.getRange('A7:B7').format.rowHeight=74;
 overview.getRange('B7').values=[['一个通道对应明确环节、特性和单位。使用登记唯一对应原测量；完整版本不回退到旧结论。校准及影响区间左闭右开，起点未知明确留空。证书编号为模拟登记，核查不修改原检测或放行。']];
}
if(department==='31_计量原件'){
 overview.getRange('A4:B4').format.rowHeight=144;
 overview.getRange('A4:B7').format.verticalAlignment='center';
 overview.getRange('A7:B7').format.rowHeight=74;
 overview.getRange('B7').values=[['声明原件标识及摘要来自独立归档，不按文件名猜身份。关联对应确切校准版本，完整更正不回退。模拟CSV只核对一条通道声明；原件读取按当前权限，字段一致不构成校准或产品批准。']];
}
if(department==='15_研发工艺过程')overview.getRange('A4:B4').format.rowHeight=100;
if(department==='32_字段映射演练'){
 overview.getRange('A4:B4').format.rowHeight=120;
 overview.getRange('A7:B7').format.rowHeight=76;
 overview.getRange('B7').values=[['在导入中心逐页选择业务表，并将部门表头映射到字段；个人备注列和个人备注整页明确忽略。前3行样例正常不代表整表通过，末行另含冲突和非文本编号。原正式记录不得自动替换。']];
}
if(department==='16_销售报价过程')overview.getRange('A4:B4').format.rowHeight=116;
if(department==='17_计划日期更正'){
 overview.getRange('A4:B4').format.rowHeight=90;
 overview.getRange('A4:B7').format.verticalAlignment='center';
}
if(department==='18_工序检验'){overview.getRange('A4:B4').format.rowHeight=82;overview.getRange('A4:B7').format.verticalAlignment='center';}
if(department==='19_供应商应付'){overview.getRange('A4:B4').format.rowHeight=100;overview.getRange('A4:B7').format.verticalAlignment='center';}
if(department==='20_发运签收'){overview.getRange('A4:B4').format.rowHeight=100;overview.getRange('A4:B7').format.verticalAlignment='center';}
if(department==='21_经营目标'){
 overview.getRange('A4:B4').format.rowHeight=100;overview.getRange('A4:B7').format.verticalAlignment='center';
 overview.getRange('B7').values=[['数据页第1行为字段名；按文本保留目标系列和版本，金额目标按“目标单位”列读取，百分比按0至100填写。导入前核对模型版本和摘要。']];
}
if(department==='24_库存批次资料'){overview.getRange('A4:B4').format.rowHeight=118;overview.getRange('A4:B7').format.verticalAlignment='center';}
if(department==='23_库存盘点'){overview.getRange('A4:B4').format.rowHeight=118;overview.getRange('A4:B7').format.verticalAlignment='center';}
if(department==='22_装配计划'){
 overview.getRange('A4:B4').format.rowHeight=112;overview.getRange('A4:B7').format.verticalAlignment='center';
 overview.getRange('B7').values=[['每版为完整计划快照。保留系列、版本、冻结与发布时间；完整明细行数必须匹配。资料确认的摘要对应当日整机原始记录。']];
}
overview.getRange('A9:D9').values=[['数据页','记录数','主键','时间/单位说明']];
overview.getRange('A9:D9').format={fill:'#243649',font:{name:'Arial',bold:true,color:'#FFFFFF'}};
overview.getRange('C9:C40').format.columnWidth=22;overview.getRange('D9:D40').format.columnWidth=34;
overview.tabColor='#243649';
for (let i=0;i<selected.length;i++){
 const s=selected[i],rows=scenario.tables[s.key];
 overview.getRangeByIndexes(9+i,0,1,4).values=[[s.label,rows.length,s.fields[0].label,'日期时间为中国标准时间；全部模拟']];
 const sheet=book.worksheets.add(s.label);sheet.showGridLines=false;
 sheet.getRangeByIndexes(0,0,1,s.fields.length).values=[s.fields.map(f=>f.label)];
 const values=rows.map(r=>s.fields.map(f=>{
  const v=r[f.name]; if(v===null||v===undefined)return null;
  // Write Excel serials explicitly. Date objects can be interpreted through
  // the host timezone, notably UTC 16:00 becoming local midnight on export.
  if(f.type==='date')return Date.parse(v+'T00:00:00Z')/86400000+25569;
  if(f.type==='datetime')return Date.parse(v+'Z')/86400000+25569;
  return v;
 }));
 // Bounded block writes; this workbook is a source file, not a formula report.
 const size=5000;
 for(let start=0;start<values.length;start+=size){const part=values.slice(start,start+size);sheet.getRangeByIndexes(start+1,0,part.length,s.fields.length).values=part;}
 const area=sheet.getRangeByIndexes(0,0,Math.max(rows.length+1,2),s.fields.length);
 area.format.font={name:'Arial',size:10};area.format.rowHeight=21;
 const header=sheet.getRangeByIndexes(0,0,1,s.fields.length);
 header.format={fill:'#243649',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:30,verticalAlignment:'center',horizontalAlignment:'center'};
 for(let c=0;c<s.fields.length;c++){
   const f=s.fields[c];const col=sheet.getRangeByIndexes(0,c,Math.max(rows.length+1,2),1);
   col.format.columnWidth=f.type==='datetime'?24:f.type==='date'?16:f.name==='id'||f.reference?28:f.label.length>7?27:f.type==='str'?22:18;
   if(f.name==='id'||f.reference){const width=Math.max(28,...rows.map(r=>String(r[f.name]||'').replace(/[^\x00-\xff]/g,'xx').length+2));col.format.columnWidth=Math.min(80,width);}
   if(f.name==='station')col.format.columnWidth=56;
   if(department==='32_字段映射演练'&&f.name==='note'){col.format.columnWidth=66;col.format.wrapText=true;area.format.rowHeight=42;header.format.rowHeight=30;}
   if(f.name==='basis'){col.format.columnWidth=80;col.format.wrapText=true;area.format.rowHeight=32;header.format.rowHeight=30;}
   if(department==='13_历史应收'&&['note','reason'].includes(f.name)){col.format.columnWidth=80;col.format.wrapText=true;area.format.rowHeight=38;header.format.rowHeight=30;}
   if(department==='14_售后过程'&&['description','result'].includes(f.name)){col.format.columnWidth=72;col.format.wrapText=true;area.format.rowHeight=40;header.format.rowHeight=30;}
   if(department==='15_研发工艺过程'&&['description','result','outcome'].includes(f.name)){col.format.columnWidth=72;col.format.wrapText=true;area.format.rowHeight=40;header.format.rowHeight=30;}
   if(department==='16_销售报价过程'&&['description','result','requirement','reference','reason'].includes(f.name)){col.format.columnWidth=72;col.format.wrapText=true;area.format.rowHeight=40;header.format.rowHeight=30;}
   if(department==='18_工序检验'&&['basis','reason'].includes(f.name)){col.format.columnWidth=74;col.format.wrapText=true;area.format.rowHeight=36;header.format.rowHeight=30;}
   if(department==='18_工序检验'&&f.name==='instrument')col.format.columnWidth=48;
   if(department==='19_供应商应付'&&['reference','reason'].includes(f.name)){col.format.columnWidth=76;col.format.wrapText=true;area.format.rowHeight=42;header.format.rowHeight=30;}
   if(department==='20_发运签收'&&['note','reason','route'].includes(f.name)){col.format.columnWidth=60;col.format.wrapText=true;area.format.rowHeight=32;header.format.rowHeight=30;}
   if(department==='21_经营目标'&&['basis','reason','note','name'].includes(f.name)){col.format.columnWidth=f.name==='name'?42:76;col.format.wrapText=true;area.format.rowHeight=48;header.format.rowHeight=30;}
   if(department==='21_经营目标'&&['model_signature','calculation_hash','data_signature'].includes(f.name))col.format.columnWidth=78;
   if(department==='24_库存批次资料'&&['note','reason'].includes(f.name)){col.format.columnWidth=76;col.format.wrapText=true;area.format.rowHeight=48;header.format.rowHeight=30;}
   if(['25_采购承诺','26_来料流程'].includes(department)&&['reference','reason','note'].includes(f.name)){col.format.columnWidth=76;col.format.wrapText=true;area.format.rowHeight=48;header.format.rowHeight=30;}
   if(department==='27_来料特性'&&['basis','note','reason','reference','file_reference'].includes(f.name)){col.format.columnWidth=76;col.format.wrapText=true;area.format.rowHeight=48;header.format.rowHeight=30;}
   if(department==='28_材质证明'&&['basis','note','method','reference'].includes(f.name)){col.format.columnWidth=76;col.format.wrapText=true;area.format.rowHeight=48;header.format.rowHeight=30;}
   if(department==='28_材质证明'&&f.name==='file_id')col.format.columnWidth=44;
   if(department==='28_材质证明'&&f.name==='file_sha256')col.format.columnWidth=76;
   if(department==='29_在制流转'&&['note','reference','input_lots','output_lots'].includes(f.name)){col.format.columnWidth=76;col.format.wrapText=true;area.format.rowHeight=48;header.format.rowHeight=30;}
   if(department==='29_在制流转'&&f.type==='datetime'){col.format.columnWidth=28;col.format.horizontalAlignment='center';}
   if(department==='30_计量校准'&&['note','reference','name','source_alias'].includes(f.name)){col.format.columnWidth=f.name==='name'?48:76;col.format.wrapText=true;area.format.rowHeight=64;header.format.rowHeight=30;}
   if(department==='30_计量校准'&&f.type==='datetime'){col.format.columnWidth=28;col.format.horizontalAlignment='center';}
   if(department==='30_计量校准'&&f.name==='source_digest')col.format.columnWidth=76;
   if(department==='31_计量原件'&&['note','reference'].includes(f.name)){col.format.columnWidth=76;col.format.wrapText=true;area.format.rowHeight=64;header.format.rowHeight=30;}
   if(department==='31_计量原件'&&f.type==='datetime'){col.format.columnWidth=28;col.format.horizontalAlignment='center';}
   if(department==='31_计量原件'&&f.name==='file_sha256')col.format.columnWidth=76;
   if(department==='31_计量原件'&&f.name==='file_id')col.format.columnWidth=46;
   if(department==='23_库存盘点'&&['note','reason','evidence','freeze_evidence','method'].includes(f.name)){col.format.columnWidth=76;col.format.wrapText=true;area.format.rowHeight=48;header.format.rowHeight=30;}
   if(department==='22_装配计划'&&['basis','reason','note'].includes(f.name)){col.format.columnWidth=76;col.format.wrapText=true;area.format.rowHeight=48;header.format.rowHeight=30;}
   if(department==='22_装配计划'&&f.name==='data_signature')col.format.columnWidth=78;
   const data=sheet.getRangeByIndexes(1,c,Math.max(rows.length,1),1);
   if(f.type==='date')data.setNumberFormat('yyyy-mm-dd');
   else if(f.type==='datetime')data.setNumberFormat('yyyy-mm-dd hh:mm:ss');
   else if(f.type==='int')data.setNumberFormat('#,##0');
   else if(f.type==='float')data.setNumberFormat(['27_来料特性','28_材质证明'].includes(department)?'#,##0.000000':'#,##0.0000');
   else if(f.type==='str')data.setNumberFormat('@');
 }
 if(['18_工序检验','19_供应商应付','21_经营目标','22_装配计划','23_库存盘点','24_库存批次资料','25_采购承诺','26_来料流程','27_来料特性','28_材质证明','29_在制流转','30_计量校准','31_计量原件'].includes(department))area.format.verticalAlignment='center';
 sheet.freezePanes.freezeRows(1);
 let n=s.fields.length,last='';while(n){n--;last=String.fromCharCode(65+n%26)+last;n=Math.floor(n/26);}
 sheet.tables.add(`A1:${last}${rows.length+1}`,true,'T_'+s.key);
}
const dictionary=book.worksheets.add('字段字典');dictionary.showGridLines=false;
const definitions=[['数据页','内部字段','Excel字段','类型','必填','关联数据集'],...selected.flatMap(s=>s.fields.map(f=>[s.label,f.name,f.label,f.type,f.required?'是':'否',f.reference||'']))];
dictionary.getRangeByIndexes(0,0,definitions.length,6).values=definitions;
dictionary.getRangeByIndexes(0,0,definitions.length,6).format.font={name:'Arial',size:10};
dictionary.getRange('A1:F1').format={fill:'#243649',font:{bold:true,color:'#FFFFFF'},rowHeight:28};
dictionary.getRangeByIndexes(0,0,definitions.length,6).format.columnWidth=24;
if(department==='25_采购承诺')dictionary.getRangeByIndexes(0,5,definitions.length,1).format.columnWidth=44;
dictionary.freezePanes.freezeRows(1);
book.recalculate();
const check=await book.inspect({kind:'region',sheetId:selected[0].label,range:'A1:F4',maxChars:1200,tableMaxRows:4,tableMaxCols:6});
console.log(check.ndjson);
console.log((await book.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:10},summary:'formula error scan'})).ndjson);
// Review a bounded region of every sheet; retain images for human visual QA.
for(const name of ['导入说明',...selected.map(s=>s.label),'字段字典']){
 if(reviewSheets&&!reviewSheets.has(name))continue;
 const range=department==='17_计划日期更正'?(name==='导入说明'?'A1:D11':name==='字段字典'?'A1:F10':'A1:I8'):(name==='导入说明'?(department==='19_供应商应付'?'A1:D17':'A1:D15'):'A1:F8');
 const img=await book.render({sheetName:name,range,scale:1,format:'png'});
 await fs.writeFile(path.join(previewOutput,department+'_'+name+'.png'),new Uint8Array(await img.arrayBuffer()));
}
const letters=n=>{let text='';for(;n;n=Math.floor((n-1)/26))text=String.fromCharCode(65+(n-1)%26)+text;return text};
if(['18_工序检验','19_供应商应付','20_发运签收','21_经营目标','22_装配计划','23_库存盘点','24_库存批次资料','25_采购承诺','26_来料流程','27_来料特性','28_材质证明','29_在制流转','30_计量校准','31_计量原件','32_字段映射演练'].includes(department))for(const s of selected){
 if(reviewSheets&&!reviewSheets.has(s.label))continue;
 for(let first=7;first<=s.fields.length;first+=6){
  const last=Math.min(s.fields.length,first+5),range=`${letters(first)}1:${letters(last)}6`;
  const img=await book.render({sheetName:s.label,range,scale:1,format:'png'});
  await fs.writeFile(path.join(previewOutput,department+'_'+s.label+'_'+first+'.png'),new Uint8Array(await img.arrayBuffer()));
 }
}
for(const s of selected.filter(s=>['bom','routes','units','operations','attendance','production_resources','route_dependencies','resource_calendars','labor_entries','ar_opening','ar_events','service_events','service_tasks','service_conditions','project_milestones','change_actions','quotes','quote_details','quote_order_links','quote_tasks'].includes(s.key))){
 if(reviewSheets&&!reviewSheets.has(s.label))continue;
 const end=s.fields.length;const preview=await book.render({sheetName:s.label,range:`${letters(Math.max(1,end-5))}1:${letters(end)}8`,scale:1,format:'png'});
 await fs.writeFile(path.join(previewOutput,department+'_'+s.label+'_新增字段.png'),new Uint8Array(await preview.arrayBuffer()));
}
const filename=department+'_模拟.xlsx';const xlsx=await SpreadsheetFile.exportXlsx(book);await xlsx.save(path.join(output,filename));
console.log(JSON.stringify({department,file:filename,tables:selected.length,rows:selected.reduce((n,s)=>n+scenario.tables[s.key].length,0)}));
