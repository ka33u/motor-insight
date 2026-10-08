import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=new URL('../',import.meta.url);
const input=JSON.parse(await fs.readFile(new URL('data/changeover_scenario.json',root),'utf8'));
const output=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root);
const preview=new URL('data/changeover-previews/',root);
await fs.mkdir(output,{recursive:true});await fs.mkdir(preview,{recursive:true});
const workbook=Workbook.create(),intro=workbook.worksheets.add('导入说明');
intro.showGridLines=false;
intro.getRange('A2:B2').merge();intro.getRange('A2').values=[['MotorInsight 三品种换型与交期取舍']];
const total=Object.values(input.tables).reduce((n,rows)=>n+rows.length,0);
const notes=[['项目','说明'],['性质','独立合成计划假设。供给不是账面库存，优先级不是正式派工或业务批准。'],
 ['输入',`16张原始表、${total}行。3个产品、3个批次、24台、96个任务。编号与引用保持文本。`],
 ['日期','2026-10-16 08:00 至 2026-10-19 18:00。原合成窗口顺延14天，包含原休息和不可用段。'],
 ['批次','B001：CP.00008.A，6台，FRAME-A，10月17日12:00，优先级1。\nB002：CP.00015.A，8台，FRAME-B，10月17日18:00，优先级3。\nB003：CP.00022.A，10台，FRAME-A，10月18日18:00，优先级2。'],
 ['策略','应完成时间优先：B001/B002/B003；批次优先级优先：B001/B003/B002。优先级为显式人工假设，不是自动同族寻优。'],
 ['设备','每任务从原候选中取编码最小资源位，仅保留一个候选。10个资源位由三批共用，不增加平行容量。'],
 ['人员','沿用原技能及候选工号。资格假设与日历顺延14天，一人陪同整个换型和加工，不按可选人数扩大产能。'],
 ['换型','各候选首次上机或跨换型族为12分钟，同族后续为0。资源初始族未知，首任务计入准备；不是具体型号转换矩阵。'],
 ['物料','按各自BOM及路线绑定需求，同物料同单位合池，供给恰好覆盖全部需求。kg向上取整至0.001，件向上取整至1。'],
 ['来源','沿用公开合成CR-261002-001前三批的产品、路线、BOM、工时与人机原编号；另建SP/CR/MP-261016-001假设版本。'],
 ['导入','先按demo清单导入43份有效工作簿。本文件经正常Excel预览、引用校验和提交；16张业务表第1行是标准表头。'],
 ['阅读','打开MP-261016-001的两策略对照，比较批次完成与晚交；在人机占用页看换型加工分段，点任务核对原假设及Excel行。'],
 ['边界','换型减少不保证全部批次更早完成；总完工时点和每批内部交期需分别核对。无模具约束、具体产品转换矩阵、抢占或自动优化。']];
intro.getRange(`A4:B${3+notes.length}`).values=notes;
intro.getRange('A2:B17').format={font:{name:'Arial',size:11,color:'#203A49'},verticalAlignment:'center'};
intro.getRange('A2:B2').format={font:{name:'Arial',size:18,bold:true,color:'#203A49'},rowHeight:42};
intro.getRange('A4:B4').format={fill:'#203A49',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},rowHeight:30};
intro.getRange('A4:A17').format.columnWidth=15;intro.getRange('B4:B17').format.columnWidth=110;
intro.getRange('A5:B17').format.rowHeight=52;intro.getRange('B5:B17').format.wrapText=true;
intro.getRange('A8:B8').format.rowHeight=75;
const letter=n=>{let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s};
const previews=[['导入说明','A2:B17','00-导入说明']];
for(const [index,[key,rows]] of Object.entries(input.tables).entries()){
 const fields=input.schemas[key].fields,last=letter(fields.length-1),sheet=workbook.worksheets.add(input.schemas[key].label);
 const values=[fields.map(f=>f.label),...rows.map(r=>fields.map(f=>f.type==='datetime'?Date.parse(r[f.name]+'Z')/86400000+25569:r[f.name]??null))];
 sheet.getRange(`A1:${last}${values.length}`).values=values;
 sheet.getRange(`A1:${last}${values.length}`).format={font:{name:'Arial',size:11,color:'#203A49'},rowHeight:46,verticalAlignment:'center'};
 sheet.getRange(`A1:${last}1`).format={fill:'#203A49',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},rowHeight:34,wrapText:true};
 for(let i=0;i<fields.length;i++){
  const field=fields[i],col=letter(i),range=sheet.getRange(`${col}2:${col}${values.length}`);
  const wide=['scope','assumptions','basis'].includes(field.name),numeric=['datetime','int','float'].includes(field.type);
  range.setNumberFormat(field.type==='datetime'?'yyyy-mm-dd hh:mm:ss':field.type==='float'?'0.000':field.type==='int'?'#,##0':'@');
  range.format.horizontalAlignment=numeric?'right':'left';range.format.wrapText=wide;
  sheet.getRange(`${col}1:${col}${values.length}`).format.columnWidth=wide?100:field.type==='datetime'?29:field.type==='str'?39:18;
 }
 sheet.showGridLines=false;sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(1);
 sheet.tables.add(`A1:${last}${values.length}`,true,'Mix_'+key);
 for(let at=0;at<fields.length;at+=4)previews.push([sheet.name,`${letter(at)}1:${letter(Math.min(at+3,fields.length-1))}${Math.min(4,values.length)}`,`${String(index+1).padStart(2,'0')}-${key}-${at}`]);
}
workbook.recalculate();
console.log((await workbook.inspect({kind:'table',range:'试排模拟批次!A1:F4',include:'values,formulas',tableMaxRows:4,tableMaxCols:6,maxChars:1800})).ndjson);
console.log((await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:1000})).ndjson);
for(const [sheetName,range,name] of previews){
 const png=await workbook.render({sheetName,range,scale:1,format:'png'});
 await fs.writeFile(new URL(name+'.png',preview),new Uint8Array(await png.arrayBuffer()));
}
const destination=fileURLToPath(new URL('45_三品种换型与交期_模拟.xlsx',output));
await(await SpreadsheetFile.exportXlsx(workbook)).save(destination);
console.log(JSON.stringify({output:destination,sourceRows:total,sheets:17,previews:previews.length}));
