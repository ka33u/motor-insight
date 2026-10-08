import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=new URL('../',import.meta.url),input=JSON.parse(await fs.readFile(new URL('data/return_stock_scenario.json',root),'utf8'));
const output=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root),preview=new URL('data/return-stock-previews/',root);
await fs.mkdir(output,{recursive:true});await fs.mkdir(preview,{recursive:true});
const wb=Workbook.create(),intro=wb.worksheets.add('导入说明');
const notes=[['项目','说明'],['性质','独立合成输入，用于核对退料与库存状态；不代表真实质量结论、批准或库存承诺。'],
 ['范围','2个独立产品配置、16种物料、7张工单，保留完整BOM与工艺路线。8笔退料指向7个目标库位。'],
 ['来源','复制公开模拟CP.00008.A的规格、BOM与路线；另建CP.09101.A/CP.09102.A及独立物料、批次和库位。'],
 ['业务截止','2026-10-01 18:00。Q006工单目标库位的10月2日状态变更保留为未来输入，当前仍待检。'],
 ['状态案例','Q001待检；Q002转可用后再领1 kg；Q003转隔离；Q004原状态登记错链。'],
 ['时序与去重','Q005状态变更与退料同刻，不推断先后；Q007分两次退至同一库位，库存余额只计一次。'],
 ['登记边界','库存状态表中的批准工号是合成登记字段；未建立逐退料检验报告与授权有效性证明。'],
 ['导入与阅读','先按demo清单正常导入45份有效工作簿，再预览提交本文件。进入库存与物料保障→退料与库存状态，查找MO-260928-Q。'],
 ['数量口径','退料单据量与目标库位现存量分别阅读。目标库位还可能存在其他收发，不能把其余额分摊到某笔退料。']];
intro.getRange('A2').values=[['MotorInsight 退料库存状态模拟']];intro.getRange(`A4:B${notes.length+3}`).values=notes;
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
 sheet.showGridLines=false;sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(1);sheet.tables.add(`A1:${last}${values.length}`,true,'ReturnStock_'+key);
 for(let n=0;n<fields.length;n+=4)views.push([sheet.name,`${letter(n)}1:${letter(Math.min(n+3,fields.length-1))}${Math.min(values.length,['inventory_status_events','inventory_movements'].includes(key)?values.length:4)}`,`${String(index+1).padStart(2,'0')}-${key}-${n}`]);
}
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'库存流水!A1:I6',include:'values,formulas',tableMaxRows:6,tableMaxCols:9,maxChars:1600})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:500})).ndjson);
for(const [sheetName,range,name] of views){const png=await wb.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(new URL(name+'.png',preview),new Uint8Array(await png.arrayBuffer()));}
const destination=fileURLToPath(new URL('47_退料库存状态_模拟.xlsx',output));await(await SpreadsheetFile.exportXlsx(wb)).save(destination);
console.log(JSON.stringify({output:destination,sourceRows:Object.values(input.tables).reduce((n,r)=>n+r.length,0),sheets:Object.keys(input.tables).length+1,previews:views.length}));
