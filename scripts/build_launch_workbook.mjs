import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=new URL('../',import.meta.url),input=JSON.parse(await fs.readFile(new URL('data/launch_scenario.json',root),'utf8'));
const output=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root);await fs.mkdir(output,{recursive:true});
const workbook=Workbook.create(),intro=workbook.worksheets.add('导入说明');intro.showGridLines=false;
const notes=[['项目','说明'],['输入','10个独立案例、6张原始表，共4270行；通过正常Excel预览、校验及提交进入平台。'],['范围','6个既有试排批次、50台；198个任务对应66个批次工序，每个工序明确三类条件。订单仍有85台未覆盖。'],['工装','配套关系为自编假设；原台账超维护次数、到期或设备不匹配仍阻断，不改原工具记录。'],['文件','保留文件号、适用配置与工序、要求版本、登记和有效窗口；编号不证明原件已经审阅。'],['质量','模拟开工条件登记；不是首件实测、工序检验批准、整机放行或实际生产许可。'],['时段','完整换型与加工都须落入有效窗口，区间左闭右开；工装台账到期日按当日00:00失效核对。'],['计次','每台使用次数为输入假设，逐任务份号累计；共享工装跨任务不得重叠，不延时重排。'],['保守预算','其他条件受阻也保留已分配工装的占用与次数。未匹配工装的需求不视为零。'],['缺资料','工装尚无配套、指定文件未登记和未形成试排时间单列未知；漏列条件不能当成不需要。'],['案例','文件版本、质量限制、借用占用、缺文件、漏条件、过期、基线差异、缺人和摘要错误均保留。'],['边界','只做所列合成登记的核对与前序影响传播，不接真实U8/MES，不写回订单、工单或库存。'],['导入','先导入第40份订单BOM基线及其前置数据，再打开“投产条件”。没有原件及现场审核，不得作为开工批准。']];
intro.getRange('A2').values=[['MotorInsight · 投产条件核对输入']];intro.getRange(`A4:B${notes.length+3}`).values=notes;
intro.getRange(`A2:B${notes.length+3}`).format={font:{name:'Arial',size:11,color:'#25394a'},verticalAlignment:'center'};
intro.getRange('A2').format.font={name:'Arial',size:16,bold:true};intro.getRange('A4:B4').format={fill:'#26394a',font:{name:'Arial',size:11,color:'#fff',bold:true}};
intro.getRange('A4:A16').format.columnWidth=18;intro.getRange('B4:B16').format.columnWidth=115;intro.getRange('B5:B16').format.wrapText=true;intro.getRange('A5:B16').format.rowHeight=44;
const letter=n=>{let t='';for(n++;n;n=Math.floor((n-1)/26))t=String.fromCharCode(65+(n-1)%26)+t;return t};
const serial=iso=>Date.parse((iso.length===10?iso+'T00:00:00':iso)+'Z')/86400000+25569;
for(const [key,rows] of Object.entries(input.tables)){
 const fields=input.schemas[key].fields,last=letter(fields.length-1),sheet=workbook.worksheets.add(input.schemas[key].label);
 const values=[fields.map(f=>f.label),...rows.map(r=>fields.map(f=>r[f.name]==null?null:['date','datetime'].includes(f.type)?serial(r[f.name]):r[f.name]))];
 sheet.getRange(`A1:${last}${values.length}`).values=values;sheet.getRange(`A1:${last}${values.length}`).format={font:{name:'Arial',size:11,color:'#25394a'},rowHeight:44,verticalAlignment:'center'};
 sheet.getRange(`A1:${last}1`).format={fill:'#26394a',font:{name:'Arial',size:11,color:'#fff',bold:true},wrapText:true,rowHeight:44,horizontalAlignment:'center'};
 for(let i=0;i<fields.length;i++){
  const f=fields[i],col=letter(i),cells=sheet.getRange(`${col}2:${col}${values.length}`),wide=['basis','note','reason'].includes(f.name);
  cells.setNumberFormat(f.type==='datetime'?'yyyy-mm-dd hh:mm:ss':f.type==='date'?'yyyy-mm-dd':f.type==='float'?'0.000':f.type==='int'?'#,##0':f.type==='bool'?'General':'@');
  cells.format.horizontalAlignment=['date','datetime','float','int'].includes(f.type)?'right':'left';
  sheet.getRange(`${col}1:${col}${values.length}`).format.columnWidth=wide?105:f.name.endsWith('_hash')?76:f.type==='datetime'?29:f.name==='name'?42:f.name.endsWith('_id')||f.name==='id'?34:26;
  if(wide)cells.format.wrapText=true;
 }
 sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(2);sheet.showGridLines=false;sheet.tables.add(`A1:${last}${values.length}`,true,'LR_'+key);
}
workbook.recalculate();
for(const key of Object.keys(input.tables))console.log((await workbook.inspect({kind:'table',range:input.schemas[key].label+'!A1:F4',include:'values,formulas',tableMaxRows:4,tableMaxCols:6,maxChars:1000})).ndjson);
console.log((await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:10},maxChars:600})).ndjson);
const previews=[['导入说明','A2:B16','intro']];
for(const [key,schema] of Object.entries(input.schemas))for(let i=0;i<schema.fields.length;i+=4)previews.push([schema.label,letter(i)+'1:'+letter(Math.min(i+3,schema.fields.length-1))+'4',key+'-'+i]);
for(const [sheetName,range,label] of previews){const p=await workbook.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(new URL('launch-'+label+'.png',output),new Uint8Array(await p.arrayBuffer()));}
await (await SpreadsheetFile.exportXlsx(workbook)).save(fileURLToPath(new URL('41_投产条件核对_模拟.xlsx',output)));
console.log('Saved 41_投产条件核对_模拟.xlsx');
