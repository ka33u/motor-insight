import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=new URL('../',import.meta.url),input=JSON.parse(await fs.readFile(new URL('data/joint_schedule_scenario.json',root),'utf8'));
const output=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root);await fs.mkdir(output,{recursive:true});
const workbook=Workbook.create(),intro=workbook.worksheets.add('导入说明');intro.tabColor='#477b73';intro.showGridLines=false;
intro.getRange('A2').values=[['MotorInsight · 物料、人机联立试排输入']];
intro.getRange('A4:B15').values=[['项目','说明'],['输入','10个独立案例、4张原始表，共1569行；每案例引用既有6批次、50台的人机假设。'],['期间','2026-10-02 08:00至10-05 18:00，均为独立未来计划假设。'],['来源','BOM、路线、物料、人员及资源来自既有合成档案；本文件没有真实库存、采购承诺或生产实绩。'],['绑定','当前配置BOM行显式绑定到同产品、同分支的路线工序；不是历史订单冻结BOM。'],['需求','批量×BOM单耗×(1+损耗)，按步长向上取整。kg精确至0.001；件向上取整。'],['预留','绑定工序首个成功任务准备开始时，预留整批需求；同工序其他份号沿用。'],['供给','同物料同单位共享供给，按可用时间、供给号FIFO，可拆批；隔离和不可预留数量被排除。'],['先后','按派序先占未来物料，不抢占；整体重排设备与人员，不只平移既有时间。'],['异常','第7至9例故意设置绑定遗漏、单位和用量错误；导入保留，计算暂停，来源和完整输入仍可导出。'],['边界','已预留但未排完的批次不自动释放。未含保质期、替代料、换算、模具约束和正式派工。'],['导入','先导入36及37号资源与人员工作簿；本表经正常预览、引用检查与提交后查看“物料人机联立试排”。']];
intro.getRange('A2:B15').format={font:{name:'Arial',size:11,color:'#25394a'},verticalAlignment:'center'};
intro.getRange('A2').format.font={name:'Arial',size:16,bold:true};
intro.getRange('A4:B4').format={fill:'#26394a',font:{name:'Arial',size:11,color:'#fff',bold:true}};
intro.getRange('A4:A15').format.columnWidth=18;intro.getRange('B4:B15').format.columnWidth=115;
intro.getRange('B5:B15').format.wrapText=true;intro.getRange('A5:B15').format.rowHeight=44;
const letter=n=>{let t='';for(n++;n;n=Math.floor((n-1)/26))t=String.fromCharCode(65+(n-1)%26)+t;return t};
const excelTime=iso=>Date.parse(iso+'Z')/86400000+25569;
for(const [key,rows] of Object.entries(input.tables)){
 const fields=input.schemas[key].fields,last=letter(fields.length-1),sheet=workbook.worksheets.add(input.schemas[key].label);
 const values=[fields.map(f=>f.label),...rows.map(r=>fields.map(f=>f.type==='datetime'?excelTime(r[f.name]):r[f.name]??null))];
 sheet.getRange(`A1:${last}${values.length}`).values=values;
 sheet.getRange(`A1:${last}${values.length}`).format={font:{name:'Arial',size:11,color:'#25394a'},rowHeight:44,verticalAlignment:'center'};
 sheet.getRange(`A1:${last}1`).format={fill:'#26394a',font:{name:'Arial',size:11,color:'#fff',bold:true},wrapText:true,rowHeight:44,horizontalAlignment:'center'};
 for(let i=0;i<fields.length;i++){
  const f=fields[i],col=letter(i),range=sheet.getRange(`${col}2:${col}${values.length}`),wide=['basis','scope','assumptions'].includes(f.name);
  range.setNumberFormat(f.type==='datetime'?'yyyy-mm-dd hh:mm:ss':f.type==='float'?'0.000':f.type==='int'?'#,##0':'@');
  range.format.horizontalAlignment=['datetime','float','int'].includes(f.type)?'right':'left';
  sheet.getRange(`${col}1:${col}${values.length}`).format.columnWidth=wide?90:f.type==='datetime'?29:['id','study_id','job_id','crew_study_id','binding_id','reference','lot'].includes(f.name)?34:f.name==='name'?38:26;
  if(wide)range.format.wrapText=true;
 }
 sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(1);sheet.showGridLines=false;sheet.tables.add(`A1:${last}${values.length}`,true,'Joint_'+key);
}
workbook.recalculate();
for(const key of Object.keys(input.tables))console.log((await workbook.inspect({kind:'table',range:input.schemas[key].label+'!A1:F4',include:'values,formulas',tableMaxRows:4,tableMaxCols:6,maxChars:1000})).ndjson);
console.log((await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:10},maxChars:600})).ndjson);
const previews=[['导入说明','A2:B15','说明']];
for(const key of Object.keys(input.tables)){
 const s=input.schemas[key],last=letter(s.fields.length-1);
 previews.push([s.label,'A1:D5',key+'-身份'],[s.label,'E1:'+letter(Math.min(9,s.fields.length-1))+'5',key+'-内容']);
 if(s.fields.length>10)previews.push([s.label,'K1:'+last+'5',key+'-依据']);
}
for(const [sheetName,range,label] of previews){const p=await workbook.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(new URL('joint-'+label+'.png',output),new Uint8Array(await p.arrayBuffer()));}
await (await SpreadsheetFile.exportXlsx(workbook)).save(fileURLToPath(new URL('39_物料人机联立试排_模拟.xlsx',output)));
console.log('Saved 39_物料人机联立试排_模拟.xlsx');
