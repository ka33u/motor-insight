import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=new URL('../',import.meta.url),input=JSON.parse(await fs.readFile(new URL('data/first_review_scenario.json',root),'utf8'));
const output=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root);await fs.mkdir(output,{recursive:true});
const workbook=Workbook.create(),schema=input.schemas.first_piece_reviews,rows=input.tables.first_piece_reviews,sheet=workbook.worksheets.add(schema.label);
const letter=n=>String.fromCharCode(65+n),serial=iso=>Date.parse(iso+'Z')/86400000+25569,fields=schema.fields,last=letter(fields.length-1);
const values=[fields.map(f=>f.label),...rows.map(r=>fields.map(f=>r[f.name]==null?null:f.type==='datetime'?serial(r[f.name]):r[f.name]))];
sheet.showGridLines=false;sheet.getRange(`A1:${last}${values.length}`).values=values;
sheet.getRange(`A1:${last}${values.length}`).format={font:{name:'Arial',size:11,color:'#25394a'},rowHeight:44,verticalAlignment:'center'};
sheet.getRange(`A1:${last}1`).format={fill:'#26394a',font:{name:'Arial',size:11,color:'#ffffff',bold:true},wrapText:true,horizontalAlignment:'center'};
for(let i=0;i<fields.length;i++){
 const f=fields[i],col=letter(i),cells=sheet.getRange(`${col}2:${col}${values.length}`);
 cells.setNumberFormat(f.type==='datetime'?'yyyy-mm-dd hh:mm:ss"  "':f.type==='int'?'#,##0"  "':'@');
 cells.format.horizontalAlignment=['datetime','int'].includes(f.type)?'right':'left';
 sheet.getRange(`${col}1:${col}${values.length}`).format.columnWidth=f.name==='note'?108:f.name.endsWith('_hash')?82:f.type==='datetime'?29:f.name==='version'?14:f.name==='status'||f.name==='decision'?20:36;
 if(f.name==='note')cells.format.wrapText=true;
}
sheet.getRange(`E2:E${values.length}`).dataValidation={rule:{type:'list',values:['草稿','已登记','撤销']}};
sheet.getRange(`L2:L${values.length}`).dataValidation={rule:{type:'list',values:['复核通过','不予通过','待补充']}};
sheet.tables.add(`A1:${last}${values.length}`,true,'FirstPieceReviewRegister');sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(2);
const guide=workbook.worksheets.add('导入说明');guide.showGridLines=false;
guide.getRange('A2').values=[['MotorInsight 首件复核登记']];
const notes=[['项目','说明'],['数据性质','293条自编复核版本，覆盖288个既有首件计划。使用已有Excel中的工单、计划、检验和工号。'],['导入方式','先导入工序检验和计量等前置工作簿，再经平台预览、校验和正常提交导入本表。'],['版本规则','同一首件计划只有一条当前版本链。草稿和未来登记不替代当前登记。撤销、缺版或重复版本不回退旧通过。'],['依据截止','常规案例取2026-10-01 17:00。复核时点不早于依据截止，登记时点不早于复核。'],['依据摘要','内容摘要绑定所列检验及计量事实，规则摘要绑定计算解释。修改来源后需重新核对并登记完整新版本。'],['异常案例','包括撤销、最新待补、内容摘要不符、规则不符、引用别的检验、版本缺项、草稿、未来登记及重复首版。'],['结论矛盾','故意保留少量“登记通过但证据有超限或计量疑点”的案例，平台应显示冲突而不是自动放行。'],['复核边界','复核文件号和工号均为合成登记，不证明真实原件审阅、电子签名、测量能力或实际生产批准。'],['后续处理','新工单不能借用旧工单首件；首件触发、批次覆盖、现场复核和放量须由实际授权流程落实。']];
guide.getRange(`A4:B${notes.length+3}`).values=notes;guide.getRange('A2:B13').format={font:{name:'Arial',size:11,color:'#25394a'},verticalAlignment:'center'};guide.getRange('A2').format.font={name:'Arial',size:16,bold:true};
guide.getRange('A4:B4').format={fill:'#26394a',font:{name:'Arial',size:11,color:'#ffffff',bold:true},horizontalAlignment:'center'};
guide.getRange('A4:A13').format.columnWidth=18;guide.getRange('B4:B13').format.columnWidth=120;guide.getRange('B5:B13').format.wrapText=true;guide.getRange('A5:B13').format.rowHeight=44;
workbook.recalculate();
for(const range of ['A1:G4','H1:O4','A290:O294'])console.log((await workbook.inspect({kind:'table',range:schema.label+'!'+range,include:'values,formulas',tableMaxRows:5,tableMaxCols:8,maxChars:1200})).ndjson);
console.log((await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:10},maxChars:500})).ndjson);
const previews=[['导入说明','A2:B13','guide'],[schema.label,'A1:D5','identity'],[schema.label,'E1:G5','basis'],[schema.label,'H1:I4','hashes'],[schema.label,'J1:M5','decision'],[schema.label,'N1:O5','notes'],[schema.label,'A290:G294','versions']];
for(const [sheetName,range,label] of previews){const p=await workbook.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(new URL('first-review-'+label+'.png',output),new Uint8Array(await p.arrayBuffer()));}
await (await SpreadsheetFile.exportXlsx(workbook)).save(fileURLToPath(new URL('42_首件复核登记_模拟.xlsx',output)));
console.log('Saved 42_首件复核登记_模拟.xlsx');
