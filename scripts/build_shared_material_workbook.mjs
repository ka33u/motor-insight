import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=new URL('../',import.meta.url);
const input=JSON.parse(await fs.readFile(new URL('data/shared_material_scenario.json',root),'utf8'));
const output=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root);
const preview=new URL('data/shared-material-previews/',root);
await fs.mkdir(output,{recursive:true});await fs.mkdir(preview,{recursive:true});
const workbook=Workbook.create(),intro=workbook.worksheets.add('导入说明');
intro.showGridLines=false;intro.tabColor='#307E83';
intro.getRange('A2:B2').merge();intro.getRange('A2').values=[['MotorInsight · 跨批次共享物料试排']];
const total=Object.values(input.tables).reduce((n,rows)=>n+rows.length,0);
const notes=[['项目','说明'],['性质','全部为独立合成计划假设，不代表真实库存、生产实绩、采购承诺或正式派工。'],
 ['输入',`16张原始表、${total}行；两个同型号批次各6台，共12台，52个任务。原编号与引用保持文本。`],
 ['日期','2026-10-09 08:00 至 2026-10-12 18:00；沿用原合成工作窗口并顺延7天。'],
 ['批次','SP-261009-001-B001：内部交期10月10日18:00、优先级2；B002：10月11日18:00、优先级1（1优先）。'],
 ['对照','MP-261009-001：两批共需硅钢171.398 kg，共享供给85.699 kg；MP-261009-002：供给171.398 kg。其余物料足量。'],
 ['共享','物料01.01.0002按同编码、同单位跨批次共用；各方案独立，两个案例的供给不可相加。'],
 ['需求','每批6台；每条BOM按批量×单耗×(1+损耗)，kg向上取整至0.001，件向上取整至1。表中数值为显式导入假设。'],
 ['预留','绑定工序首个成功任务准备开始时整批预留；按派序先占，不抢占、不自动释放。定转子同料合并核对但整批需求不重复。'],
 ['阅读','交期优先与优先级优先分别读取→逐批次结果→逐物料构成→需求/预留→任务人机依据→Excel来源。'],
 ['来源','产品CP.00008.A、BOM、路线、物料、人机档案沿用既有公开合成Excel；任务与日历另建假设版本。无历史订单自动绑定。'],
 ['导入','先按demo清单导入42份有效工作簿；另1份映射演示原表保留备查。本文件经正常Excel预览、引用检查和提交，所有表保留第1行标准表头。'],
 ['边界','启发式输出不保证最优，不推断真实缺料因果；没有替代料、单位换算、模具约束、抢占或自动业务批准。']];
intro.getRange(`A4:B${3+notes.length}`).values=notes;
intro.getRange('A2:B16').format={font:{name:'Arial',size:11,color:'#203A49'},verticalAlignment:'center'};
intro.getRange('A2:B2').format={fill:'#203A49',font:{name:'Arial',size:17,bold:true,color:'#FFFFFF'},rowHeight:42};
intro.getRange('A4:B4').format={fill:'#307E83',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},rowHeight:30};
intro.getRange('A4:A16').format.columnWidth=15;intro.getRange('B4:B16').format.columnWidth=110;
intro.getRange('A5:B16').format.rowHeight=52;intro.getRange('B5:B16').format.wrapText=true;
const letter=n=>{let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s};
const previews=[['导入说明','A2:B16','00-导入说明']];
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
 sheet.tables.add(`A1:${last}${values.length}`,true,'Shared_'+key);
 for(let at=0;at<fields.length;at+=4)previews.push([sheet.name,`${letter(at)}1:${letter(Math.min(at+3,fields.length-1))}${Math.min(4,values.length)}`,`${String(index+1).padStart(2,'0')}-${key}-${at}`]);
}
workbook.recalculate();
const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:1000});
console.log(errors.ndjson);
for(const [sheetName,range,name] of previews){
 const png=await workbook.render({sheetName,range,scale:1,format:'png'});
 await fs.writeFile(new URL(name+'.png',preview),new Uint8Array(await png.arrayBuffer()));
}
const destination=fileURLToPath(new URL('44_跨批次共享物料试排_模拟.xlsx',output));
await(await SpreadsheetFile.exportXlsx(workbook)).save(destination);
console.log(JSON.stringify({output:destination,sourceRows:total,sheets:17,previews:previews.length}));
