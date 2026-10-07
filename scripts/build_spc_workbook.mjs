import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';

const root=new URL('../',import.meta.url);
const input=JSON.parse(await fs.readFile(new URL('data/spc_scenario.json',root),'utf8'));
const output=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root);
await fs.mkdir(output,{recursive:true});
const workbook=Workbook.create(),notes=workbook.worksheets.add('导入说明');
notes.getRange('A2').values=[['受控采样试验模拟资料']];
notes.getRange('A4:B12').values=[
 ['项目','说明'],['数据性质','10个新增独立合成试验，730条观测及10条事件。'],
 ['用途','验证固定基线、顺序、断点与数据不足时的过程分析行为。'],
 ['生产记录','关联现有配置和SN，旧终检会话、首检、复测与放行记录保留。'],
 ['顺序来源','设备计数为模拟声明。未知顺序试验保留缺失实际时间。'],
 ['缺测与重复','缺号保留为空缺，重复样件保留原记录，不补零或择优。'],
 ['基线','每个试验的固定末序号见试验表，页面筛选不改变基线。'],
 ['测量系统','没有工厂MSA和实际测量条件审定，控制图为候选算法试算。'],
 ['导入','三个数据表使用标准表头。编号为文本，时间采用统一厂内业务时间。']];
notes.getRange('A2:B12').format={font:{name:'Arial',size:11,color:'#25394a'},verticalAlignment:'center'};
notes.getRange('A2').format.font={name:'Arial',size:16,bold:true};
notes.getRange('A4:B4').format={fill:'#26394a',font:{name:'Arial',color:'#ffffff',size:11,bold:true}};
notes.getRange('A4:A12').format.columnWidth=20;notes.getRange('B4:B12').format.columnWidth=86;
notes.getRange('B5:B12').format.wrapText=true;notes.getRange('A5:B12').format.rowHeight=34;
notes.showGridLines=false;
const letter=n=>{let text='';for(n++;n;n=Math.floor((n-1)/26))text=String.fromCharCode(65+(n-1)%26)+text;return text};
// Explicit Excel serials avoid Date local-midnight coercion during export.
// Values are naive plant-local timestamps, not UTC-to-local conversions.
const excelTime=iso=>Date.parse(iso+'Z')/86400000+25569;
for(const [key,rows] of Object.entries(input.tables)){
 const schema=input.schemas[key],fields=schema.fields,last=letter(fields.length-1);
 const sheet=workbook.worksheets.add(schema.label);
 const matrix=[fields.map(f=>f.label),...rows.map(r=>fields.map(f=>f.type==='datetime'&&r[f.name]!=null?excelTime(r[f.name]):r[f.name]??null))];
 sheet.getRange(`A1:${last}${matrix.length}`).values=matrix;
 sheet.getRange(`A1:${last}${matrix.length}`).format={font:{name:'Arial',size:11,color:'#25394a'},rowHeight:26,verticalAlignment:'center'};
 sheet.getRange(`A1:${last}1`).format={fill:'#26394a',font:{name:'Arial',size:11,color:'#ffffff',bold:true},wrapText:true,rowHeight:40,horizontalAlignment:'center'};
 for(let i=0;i<fields.length;i++){
  const f=fields[i],col=letter(i),range=sheet.getRange(`${col}2:${col}${matrix.length}`);
  range.setNumberFormat(f.type==='datetime'?'yyyy-mm-dd hh:mm:ss':f.type==='int'?'#,##0':f.type==='float'?'0.000000':'@');
  range.format.horizontalAlignment=['int','float','datetime'].includes(f.type)?'right':'left';
  sheet.getRange(`${col}1:${col}${matrix.length}`).format.columnWidth=['note','conditions','description'].includes(f.name)?68:f.type==='datetime'?28:['id','study_id','spec_id','protocol_version'].includes(f.name)?31:22;
  if(['note','conditions','description','purpose'].includes(f.name))range.format.wrapText=true;
  if(['note','description'].includes(f.name))sheet.getRange(`A2:${last}${matrix.length}`).format.rowHeight=38;
  if(f.name==='state')range.dataValidation={rule:{type:'list',values:['有效','缺测','待核查','作废']}};
  if(f.name==='status')range.dataValidation={rule:{type:'list',values:['采集中','已结束']}};
  if(f.name==='order_basis')range.dataValidation={rule:{type:'list',values:['设备计数（模拟）','人工顺序登记（模拟）','未知']}};
 }
 sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(key==='spc_observations'?3:1);
 sheet.showGridLines=false;sheet.tables.add(`A1:${last}${matrix.length}`,true,'Controlled_'+key);
}
workbook.recalculate();
console.log((await workbook.inspect({kind:'table',range:'受控采样观测!A1:H6',include:'values,formulas',tableMaxRows:6,tableMaxCols:8,maxChars:1500})).ndjson);
console.log((await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:10},maxChars:600})).ndjson);
for(const [sheetName,range,suffix] of [
 ['导入说明','A2:B12','说明'],['受控采样试验','A1:G5','试验身份'],
 ['受控采样试验','H1:Q5','试验基线'],['受控采样试验','R1:U5','试验条件'],
 ['受控采样观测','A1:H7','观测身份与数值'],['受控采样观测','I1:O7','观测条件'],
 ['采样过程事件','A1:I6','过程事件']]){
 const blob=await workbook.render({sheetName,range,scale:1,format:'png'});
 await fs.writeFile(new URL(`spc-${suffix}.png`,output),new Uint8Array(await blob.arrayBuffer()));
}
const file=await SpreadsheetFile.exportXlsx(workbook);
await file.save(fileURLToPath(new URL('34_过程稳定性采样_模拟.xlsx',output)));
console.log('Saved 34_过程稳定性采样_模拟.xlsx');
