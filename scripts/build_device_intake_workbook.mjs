import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=new URL('../',import.meta.url),input=JSON.parse(await fs.readFile(new URL('data/device_intake_scenario.json',root),'utf8'));
const output=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root);await fs.mkdir(output,{recursive:true});
const book=Workbook.create(),notes=book.worksheets.add('导入说明');
notes.getRange('A2:B2').merge();notes.getRange('A2').values=[['设备目录与文件发现演练']];
notes.getRange('A4:B10').values=[['项目','说明'],['数据性质','全部为合成模拟数据'],['目录来源','设备电脑别名与目录是声明，没有访问实际设备电脑'],['扫描结论','完成、部分完成、失败、未执行分别登记。无批次表示尚无扫描登记'],['发现与归档','清单指纹仅为声明，匹配本人归档后仍需核对实际内容'],['业务线索','会话与SN线索允许缺失或未知，不直接建立订单关联'],['导入方式','三个来源工作表按标准表头校验并导入，编号按文本']];
notes.getRange('A2:F10').format.font={name:'Arial',size:11};notes.getRange('A2').format.font={size:16,bold:true};notes.getRange('A4:B4').format={fill:'#26394a',font:{color:'#ffffff',bold:true}};notes.getRange('A4:A10').format.columnWidth=20;notes.getRange('B4:B10').format.columnWidth=80;notes.getRange('B4:B10').format.wrapText=true;notes.getRange('A5:B10').format.rowHeight=36;notes.showGridLines=false;
const letter=n=>{let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s};
for(const [key,records] of Object.entries(input.tables)){
 const schema=input.schemas[key],cols=schema.fields,last=letter(cols.length-1),sheet=book.worksheets.add(schema.label);
 const values=[cols.map(c=>c.label),...records.map(row=>cols.map(c=>c.type==='datetime'&&row[c.name]!=null?new Date(row[c.name]+'Z'):row[c.name]??null))];
 sheet.getRange(`A1:${last}${values.length}`).values=values;
 sheet.getRange(`A1:${last}${values.length}`).format={font:{name:'Arial',size:10,color:'#243442'},verticalAlignment:'center',rowHeight:25};
 sheet.getRange(`A1:${last}1`).format={fill:'#26394a',font:{color:'#ffffff',bold:true},wrapText:true,rowHeight:38};
 for(let i=0;i<cols.length;i++){
  const c=cols[i],col=letter(i),range=sheet.getRange(`${col}2:${col}${values.length}`);range.setNumberFormat(c.type==='datetime'?'yyyy-mm-dd hh:mm:ss':c.type==='int'?'#,##0':'@');
  sheet.getRange(`${col}1:${col}${values.length}`).format.columnWidth=['note','directory','relative_path'].includes(c.name)?50:c.name==='sha256'?69:c.type==='datetime'?24:['id','scan_id','session_hint','unit_hint','filename'].includes(c.name)?31:21;
  if(c.name==='note'){range.format.wrapText=true;sheet.getRange(`A2:${last}${values.length}`).format.rowHeight=48;}
 }
 sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(1);sheet.showGridLines=false;
 sheet.tables.add(`A1:${last}${values.length}`,true,'DeviceIntake_'+key);
 if(key==='device_scan_runs')sheet.getRange(`E2:E${values.length}`).dataValidation={rule:{type:'list',values:['完成','部分完成','失败','未执行']}};
 if(key==='device_file_observations')sheet.getRange(`I2:I${values.length}`).dataValidation={rule:{type:'list',values:['可读','正在写入','无权限','损坏','待核查']}};
}
book.recalculate();
const inspection=await book.inspect({kind:'table',range:'设备扫描登记!A1:H8',include:'values,formulas',tableMaxRows:8,tableMaxCols:8,maxChars:2000});console.log(inspection.ndjson);
const errors=await book.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:10},maxChars:600});console.log(errors.ndjson);
for(const [sheetName,range] of [['导入说明','A2:B10'],['设备文件来源','A1:D5'],['设备扫描登记','A1:H7'],['设备文件发现','A1:F7']]){
 const blob=await book.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(new URL(`device-intake-${sheetName}.png`,output),new Uint8Array(await blob.arrayBuffer()));
}
const xlsx=await SpreadsheetFile.exportXlsx(book);await xlsx.save(fileURLToPath(new URL('33_设备目录与待采集_模拟.xlsx',output)));console.log('Saved 33_设备目录与待采集_模拟.xlsx');
