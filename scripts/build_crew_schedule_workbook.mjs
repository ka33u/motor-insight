import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=new URL('../',import.meta.url),input=JSON.parse(await fs.readFile(new URL('data/crew_schedule_scenario.json',root),'utf8'));
const output=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root);await fs.mkdir(output,{recursive:true});
const workbook=Workbook.create(),intro=workbook.worksheets.add('导入说明');intro.tabColor='#829389';
intro.getRange('A2').values=[['设备与人员联立试排 · 独立模拟假设']];
intro.getRange('A4:B13').values=[['项目','说明'],['输入','6联立方案、118资格假设、2,358人员候选、921未来窗口、6不可用段，共3,409行。'],['前提','引用第36份Excel的SP-261002-001：6批次、198任务、50台；资源与工时仍为独立假设。'],['身份','CR-261002方案号；当前技能登记为资格依据，未来窗口是单独登记的合成假设。'],['期间','厂内时间2026-10-02至10-05；历史固定业务截止仍为2026-10-01 18:00。'],['资格','登记起止日期含到期日；本方案有效期是左闭右开。双方取交集，覆盖全部换型和加工。'],['容量','每任务一人全过程，设备与人员各容量1；同一工号跨设备和工序共享容量。'],['情形','完整人员、跨工序共享、资格假设过短、人员未来窗口缺失、重叠窗口、错误工序资格。'],['边界','假设登记不证明真实未来出勤或授权；未联立物料、工装、自动工序看护比例及费用。'],['来源','5张平面输入表经正常预览与提交；平台只读试算，不改历史工单，不实际派工。']];
intro.getRange('A2:B13').format={font:{name:'Arial',size:11,color:'#25394a'},verticalAlignment:'center'};intro.getRange('A2').format.font={name:'Arial',size:16,bold:true};intro.getRange('A4:B4').format={fill:'#26394a',font:{name:'Arial',size:11,color:'#fff',bold:true}};intro.getRange('A4:A13').format.columnWidth=18;intro.getRange('B4:B13').format.columnWidth=110;intro.getRange('B5:B13').format.wrapText=true;intro.getRange('A5:B13').format.rowHeight=36;intro.showGridLines=false;
const letter=n=>{let t='';for(n++;n;n=Math.floor((n-1)/26))t=String.fromCharCode(65+(n-1)%26)+t;return t};
const excelTime=iso=>Date.parse(iso+'Z')/86400000+25569;
for(const [key,rows] of Object.entries(input.tables)){
 const fields=input.schemas[key].fields,last=letter(fields.length-1),sheet=workbook.worksheets.add(input.schemas[key].label),values=[fields.map(f=>f.label),...rows.map(r=>fields.map(f=>f.type==='datetime'?excelTime(r[f.name]):r[f.name]??null))];
 sheet.getRange(`A1:${last}${values.length}`).values=values;sheet.getRange(`A1:${last}${values.length}`).format={font:{name:'Arial',size:11,color:'#25394a'},rowHeight:30,verticalAlignment:'center'};
 sheet.getRange(`A1:${last}1`).format={fill:'#26394a',font:{name:'Arial',size:11,color:'#fff',bold:true},wrapText:true,rowHeight:42,horizontalAlignment:'center'};
 for(let i=0;i<fields.length;i++){
  const f=fields[i],col=letter(i),data=sheet.getRange(`${col}2:${col}${values.length}`);
  data.setNumberFormat(f.type==='datetime'?'yyyy-mm-dd hh:mm:ss':f.type==='float'?'0.0000':f.type==='int'?'#,##0':'@');data.format.horizontalAlignment=['datetime','float','int'].includes(f.type)?'right':'left';
  const wide=['basis','scope','assumptions'].includes(f.name);sheet.getRange(`${col}1:${col}${values.length}`).format.columnWidth=wide?84:f.type==='datetime'?29:['id','job_id','task_id','from_task_id','to_task_id','dependency_id'].includes(f.name)?38:26;
  if(wide){data.format.wrapText=true;sheet.getRange(`A2:${last}${values.length}`).format.rowHeight=44}
 }
 sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(key==='schedule_edges'?2:1);sheet.showGridLines=false;sheet.tables.add(`A1:${last}${values.length}`,true,'Crew_'+key);
}
workbook.recalculate();
for(const [key] of Object.entries(input.tables))console.log((await workbook.inspect({kind:'table',range:input.schemas[key].label+'!A1:E4',include:'values,formulas',tableMaxRows:4,tableMaxCols:5,maxChars:1000})).ndjson);
console.log((await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:10},maxChars:500})).ndjson);
const previews=[['导入说明','A2:B13','说明']];
for(const [key] of Object.entries(input.tables)){
 const s=input.schemas[key],last=letter(s.fields.length-1);previews.push([s.label,'A1:'+letter(Math.min(3,s.fields.length-1))+'5',key+'-身份']);if(s.fields.length>4)previews.push([s.label,'E1:'+letter(Math.min(9,s.fields.length-1))+'5',key+'-内容']);if(s.fields.length>10)previews.push([s.label,'K1:'+last+'5',key+'-范围']);
}
for(const [sheetName,range,label] of previews){const p=await workbook.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(new URL('crew-'+label+'.png',output),new Uint8Array(await p.arrayBuffer()));}
await (await SpreadsheetFile.exportXlsx(workbook)).save(fileURLToPath(new URL('37_资源人员联立试排_模拟.xlsx',output)));console.log('Saved 37_资源人员联立试排_模拟.xlsx');
