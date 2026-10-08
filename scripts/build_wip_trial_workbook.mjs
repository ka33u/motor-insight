import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=new URL('../',import.meta.url),input=JSON.parse(await fs.readFile(new URL('data/wip_trial_scenario.json',root),'utf8'));
const output=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root),preview=new URL('data/wip-trial-previews/',root);
await fs.mkdir(output,{recursive:true});await fs.mkdir(preview,{recursive:true});
const wb=Workbook.create(),intro=wb.worksheets.add('导入说明');
const notes=[['项目','说明'],['性质','独立合成输入。正常预览、校验、提交后计算；不连接U8/MES，不代表现场盘点、授权或正式派工。'],
 ['范围','同配置2张完整工单，每单6台；52个工序任务、4笔原报工、4个分支在制基准。定子与转子不能相加为整机数。'],
 ['截至时点','2026-10-01 18:00；有2个已完成任务、1个加工中任务、1个中断待续任务，其余未开始。'],
 ['完成与续作','已完成任务不占未来产能；加工中锁定原设备和人员，续作12分钟。中断任务额外准备5分钟，另加常规换型。'],
 ['余料口径','按每项任务的剩余数量向上取整，再扣明确已投入量；独立尚未耗用池不能与原整批库存假设重复相加。'],
 ['方案001—003','完整池；排队任务缺料；专属线边余料仅工单1可用。应分别覆盖2、0、1张工单。'],
 ['方案004—005','加工中续作150分钟超过连续窗口；完成量与原报工不符。两者均暂停，不产生可用排程。'],
 ['方案006—008','006是001的v2，续作改为18分钟；007原始摘要失配；008已投入量超过剩余定额。后两者暂停。'],
 ['原件与版本','每行保留原任务、报工、BOM及工单编号；版本内行数、声明摘要与原始依据摘要同时核对。旧版本保留。'],
 ['导入顺序','依demo清单先正常导入46份有效工作簿，再导入本文件。进入在制剩余试排；同一时刻的不同方案各自独立计算。'],
 ['边界','单容量人机、单人全程陪同、连续窗口、保守尾部追加。未处理报废补产、返工路线、替代料、模具和多机看护。']];
intro.getRange('A2').values=[['MotorInsight 在制剩余试排模拟']];intro.getRange(`A4:B${notes.length+3}`).values=notes;
intro.getRange(`A2:B${notes.length+3}`).format={font:{name:'Arial',size:11,color:'#253C4B'},verticalAlignment:'center'};
intro.getRange('A2').format.font={name:'Arial',size:16,bold:true,color:'#253C4B'};
intro.getRange('A4:B4').format={fill:'#253C4B',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},rowHeight:30};
intro.getRange(`A4:A${notes.length+3}`).format.columnWidth=17;intro.getRange(`B4:B${notes.length+3}`).format.columnWidth=105;
intro.getRange(`A5:B${notes.length+3}`).format.rowHeight=48;intro.getRange(`B5:B${notes.length+3}`).format.wrapText=true;intro.showGridLines=false;
const letter=n=>{let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
const views=[['导入说明',`A2:B${notes.length+3}`,'00-intro']];
for(const [index,[key,rows]] of Object.entries(input.tables).entries()){
 const schema=input.schemas[key],fields=schema.fields,last=letter(fields.length-1),sheet=wb.worksheets.add(schema.label);
 const values=[fields.map(f=>f.label),...rows.map(row=>fields.map(f=>row[f.name]==null?null:f.type==='datetime'||f.type==='date'?Date.parse(row[f.name]+(f.type==='date'?'T00:00:00Z':'Z'))/86400000+25569:row[f.name]))];
 sheet.getRange(`A1:${last}${values.length}`).values=values;
 sheet.getRange(`A1:${last}${values.length}`).format={font:{name:'Arial',size:11,color:'#253C4B'},rowHeight:34,verticalAlignment:'center'};
 sheet.getRange(`A1:${last}1`).format={fill:'#253C4B',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},rowHeight:34,wrapText:true,horizontalAlignment:'center'};
 for(let n=0;n<fields.length;n++){
  const f=fields[n],col=letter(n),range=sheet.getRange(`${col}2:${col}${values.length}`),wide=['basis','reason'].includes(f.name);
  range.setNumberFormat(f.type==='datetime'?'yyyy-mm-dd hh:mm:ss':f.type==='date'?'yyyy-mm-dd':f.type==='float'?'0.000':f.type==='int'?'#,##0':'@');
  range.format.horizontalAlignment=['int','float','date','datetime'].includes(f.type)?'right':'left';
  sheet.getRange(`${col}1:${col}${values.length}`).format.columnWidth=wide?90:f.type==='datetime'?29:f.type==='str'?36:18;
  if(wide){range.format.wrapText=true;range.format.rowHeight=48;}
 }
 sheet.showGridLines=false;sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(1);sheet.tables.add(`A1:${last}${values.length}`,true,'WipTrial_'+key);
 for(let n=0;n<fields.length;n+=5)views.push([sheet.name,`${letter(n)}1:${letter(Math.min(n+4,fields.length-1))}${Math.min(values.length,key==='wip_trial_studies'?9:5)}`,`${String(index+1).padStart(2,'0')}-${key}-${n}`]);
}
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'在制任务进度声明!A1:H5',include:'values,formulas',tableMaxRows:6,tableMaxCols:9,maxChars:1600})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:500})).ndjson);
for(const [sheetName,range,name] of views){const png=await wb.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(new URL(name+'.png',preview),new Uint8Array(await png.arrayBuffer()));}
const destination=fileURLToPath(new URL('48_在制剩余试排_模拟.xlsx',output));await(await SpreadsheetFile.exportXlsx(wb)).save(destination);
console.log(JSON.stringify({output:destination,sourceRows:Object.values(input.tables).reduce((n,r)=>n+r.length,0),sheets:Object.keys(input.tables).length+1,previews:views.length}));
