import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=new URL('../',import.meta.url),input=JSON.parse(await fs.readFile(new URL('data/order_baseline_scenario.json',root),'utf8'));
const output=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root);await fs.mkdir(output,{recursive:true});
const workbook=Workbook.create(),intro=workbook.worksheets.add('导入说明');intro.showGridLines=false;
const notes=[['项目','说明'],['输入','10个独立案例、3张原始表，共609行；第2例是第1例的第二版，其余为独立核对场景。'],['订单','既有模拟订单6行共135台，未开工工单MO2609-000289至000294。试排只安排50台，另85台未覆盖。'],['交期','保留客户原承诺和基线现承诺，均在9月；10月试排的内部目标不能覆盖客户交期。'],['快照','保留配置、订单、工单、分配、BOM、工序和单位字段，摘要用于核对完整性与当前差异。'],['数量','BOM单耗、损耗及步长保留为数值，基线需求由平台重新计算；不同单位不合计。'],['版本','模拟基线时点2026-10-01 18:00；这不证明文件于当时已经生成或取得批准。'],['差异','第8例自编旧单耗，第9例自编单位差异，不能当成真实历史改版或自动换算。'],['暂停','第5至7及第10例保留摘要、明细、映射或版本链问题，完整输入可查，不显示健康零缺口。'],['范围','工单已有报工、跨订单分配或已发货数量超范围时，提示重新核对，不视为可再次投产。'],['边界','加工完成不是整单完成、质量放行、发运或签收；本文件不修改原订单、工单和客户承诺。'],['导入','先导入第39份物料人机试排及其前置数据，再经正常预览、校验、提交查看“订单与BOM基线”。']];
intro.getRange('A2').values=[['MotorInsight · 订单与BOM基线输入']];intro.getRange(`A4:B${notes.length+3}`).values=notes;
intro.getRange(`A2:B${notes.length+3}`).format={font:{name:'Arial',size:11,color:'#25394a'},verticalAlignment:'center'};
intro.getRange('A2').format.font={name:'Arial',size:16,bold:true};intro.getRange('A4:B4').format={fill:'#26394a',font:{name:'Arial',size:11,color:'#fff',bold:true}};
intro.getRange('A4:A15').format.columnWidth=18;intro.getRange('B4:B15').format.columnWidth=115;intro.getRange('B5:B15').format.wrapText=true;intro.getRange('A5:B15').format.rowHeight=44;
const letter=n=>{let t='';for(n++;n;n=Math.floor((n-1)/26))t=String.fromCharCode(65+(n-1)%26)+t;return t};
const serial=iso=>Date.parse((iso.length===10?iso+'T00:00:00':iso)+'Z')/86400000+25569;
for(const [key,rows] of Object.entries(input.tables)){
 const fields=input.schemas[key].fields,last=letter(fields.length-1),sheet=workbook.worksheets.add(input.schemas[key].label);
 const values=[fields.map(f=>f.label),...rows.map(r=>fields.map(f=>r[f.name]==null?null:['date','datetime'].includes(f.type)?serial(r[f.name]):r[f.name]))];
 sheet.getRange(`A1:${last}${values.length}`).values=values;sheet.getRange(`A1:${last}${values.length}`).format={font:{name:'Arial',size:11,color:'#25394a'},rowHeight:44,verticalAlignment:'center'};
 sheet.getRange(`A1:${last}1`).format={fill:'#26394a',font:{name:'Arial',size:11,color:'#fff',bold:true},wrapText:true,rowHeight:44,horizontalAlignment:'center'};
 for(let i=0;i<fields.length;i++){
  const f=fields[i],col=letter(i),cells=sheet.getRange(`${col}2:${col}${values.length}`),wide=['basis','note'].includes(f.name);
  cells.setNumberFormat(f.type==='datetime'?'yyyy-mm-dd hh:mm:ss':f.type==='date'?'yyyy-mm-dd':f.type==='float'?'0.000':f.type==='int'?'#,##0':f.type==='bool'?'General':'@');
  cells.format.horizontalAlignment=['date','datetime','float','int'].includes(f.type)?'right':'left';
  sheet.getRange(`${col}1:${col}${values.length}`).format.columnWidth=wide?105:f.name.endsWith('_hash')?76:f.type==='datetime'?29:f.name==='name'?42:f.name.endsWith('_id')||f.name==='id'?34:26;
  if(wide)cells.format.wrapText=true;
 }
 sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(2);sheet.showGridLines=false;sheet.tables.add(`A1:${last}${values.length}`,true,'OB_'+key);
}
workbook.recalculate();
for(const key of Object.keys(input.tables))console.log((await workbook.inspect({kind:'table',range:input.schemas[key].label+'!A1:F4',include:'values,formulas',tableMaxRows:4,tableMaxCols:6,maxChars:1000})).ndjson);
console.log((await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:10},maxChars:600})).ndjson);
const previews=[['导入说明','A2:B15','intro']];
for(const [key,schema] of Object.entries(input.schemas))for(let i=0;i<schema.fields.length;i+=4)previews.push([schema.label,letter(i)+'1:'+letter(Math.min(i+3,schema.fields.length-1))+'4',key+'-'+i]);
for(const [sheetName,range,label] of previews){const p=await workbook.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(new URL('order-baseline-'+label+'.png',output),new Uint8Array(await p.arrayBuffer()));}
await (await SpreadsheetFile.exportXlsx(workbook)).save(fileURLToPath(new URL('40_订单与BOM基线_模拟.xlsx',output)));
console.log('Saved 40_订单与BOM基线_模拟.xlsx');
