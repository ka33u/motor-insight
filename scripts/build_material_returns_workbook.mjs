import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=new URL('../',import.meta.url),input=JSON.parse(await fs.readFile(new URL('data/material_returns_scenario.json',root),'utf8'));
const output=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root),preview=new URL('data/material-returns-previews/',root);
await fs.mkdir(output,{recursive:true});await fs.mkdir(preview,{recursive:true});
const wb=Workbook.create(),intro=wb.worksheets.add('导入说明');
const notes=[['项目','说明'],['性质','全部为独立合成输入，不代表真实领料、退料、质量批准或库存承诺。'],
 ['范围','2个模拟配置、16种物料、5张工单。保留完整BOM和工艺路线。库存流水中退料的来源单号指向原领料流水。'],
 ['来源','从公开模拟CP.00008.A复制规格、完整BOM及路线，另建CP.09001.A/CP.09002.A与独立物料号、批次和库位，未覆盖旧档案。'],
 ['业务截止','2026-10-01 18:00。R004工单的10月2日退料保留为未来登记，当前不抵扣。'],
 ['部分退料','MO-260928-R001：硅钢领10 kg，分两次退2 kg和1.5 kg；另有轴承领4件、退1件。'],
 ['全部退料','MO-260928-R002：硅钢领20 kg、退20 kg。净领料0不表示没有发生过领料。'],
 ['待检退回','MO-260928-R003：硅钢领30 kg、退5 kg到DJ-RT-01待检库位。净领料减少，可用库存不因此增加。'],
 ['待核对','MO-260928-R005：独立物料领10 kg，两次各退6 kg。保留原登记，累计超过原领料量，不能部分抵扣或截成10 kg。'],
 ['导入与阅读','先按demo清单正常导入44份有效工作簿，再预览并提交本文件。备料与共享库存试配中查找MO-260928-R，打开工单和领退料依据。'],
 ['数量含义','净领料是累计领料减可核对退料，不是实际消耗或在制实存。退料按仓储流水入账一次，库存可用性另核库位状态。']];
intro.getRange('A2').values=[['MotorInsight 生产领退料模拟']];intro.getRange(`A4:B${notes.length+3}`).values=notes;
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
  const f=fields[n],col=letter(n),range=sheet.getRange(`${col}2:${col}${values.length}`),wide=f.name==='basis';
  range.setNumberFormat(f.type==='datetime'?'yyyy-mm-dd hh:mm:ss':f.type==='date'?'yyyy-mm-dd':f.type==='float'?'0.000':f.type==='int'?'#,##0':'@');
  range.format.horizontalAlignment=['int','float','date','datetime'].includes(f.type)?'right':'left';
  sheet.getRange(`${col}1:${col}${values.length}`).format.columnWidth=wide?90:f.type==='datetime'?29:f.type==='str'?36:18;
  if(wide)range.format.wrapText=true;
 }
 sheet.showGridLines=false;sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(1);sheet.tables.add(`A1:${last}${values.length}`,true,'Return_'+key);
 for(let n=0;n<fields.length;n+=4)views.push([sheet.name,`${letter(n)}1:${letter(Math.min(n+3,fields.length-1))}${Math.min(values.length,4)}`,`${String(index+1).padStart(2,'0')}-${key}-${n}`]);
}
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'库存流水!A1:I6',include:'values,formulas',tableMaxRows:6,tableMaxCols:9,maxChars:1600})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:500})).ndjson);
for(const [sheetName,range,name] of views){const png=await wb.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(new URL(name+'.png',preview),new Uint8Array(await png.arrayBuffer()));}
const destination=fileURLToPath(new URL('46_生产领退料核对_模拟.xlsx',output));await(await SpreadsheetFile.exportXlsx(wb)).save(destination);
console.log(JSON.stringify({output:destination,sourceRows:Object.values(input.tables).reduce((n,r)=>n+r.length,0),sheets:Object.keys(input.tables).length+1,previews:views.length}));
