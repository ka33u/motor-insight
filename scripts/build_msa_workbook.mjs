import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=new URL('../',import.meta.url),input=JSON.parse(await fs.readFile(new URL('data/msa_scenario.json',root),'utf8'));
const output=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root);await fs.mkdir(output,{recursive:true});
const workbook=Workbook.create(),intro=workbook.worksheets.add('采样说明');
intro.getRange('A2').values=[['测量系统交叉采样模拟资料']];intro.getRange('A4:B12').values=[
 ['项目','说明'],['资料','11个独立试验、141个样件/人员成员、930条重复观测。'],
 ['设计','默认10个样件、3位操作员、每个交叉单元3次测量。'],
 ['随机性','固定种子260928加试验编号，随机登记顺序。数值为独立合成。'],
 ['身份','复用配置、SN和工号。盲测标签与正式身份分列。'],
 ['异常场景','缺测、重复、单位差异、二值、零变异、单操作员和校准过期各自保留。'],
 ['来源','三张平面表按标准Excel导入。旧终检、校准和SPC记录不改写。'],
 ['计算','平台采用保留交互的平衡交叉ANOVA。删行、补零和换单位不能恢复平衡。'],
 ['适用范围','用于数据和算法演练。实际样件代表性、盲测、独立性和工况尚待核实。']];
intro.getRange('A2:B12').format={font:{name:'Arial',size:11,color:'#25394a'},verticalAlignment:'center'};
intro.getRange('A2').format.font={name:'Arial',size:16,bold:true};
intro.getRange('A4:B4').format={fill:'#26394a',font:{name:'Arial',size:11,color:'#ffffff',bold:true}};
intro.getRange('A4:A12').format.columnWidth=18;intro.getRange('B4:B12').format.columnWidth=94;
intro.getRange('B5:B12').format.wrapText=true;intro.getRange('A5:B12').format.rowHeight=32;intro.showGridLines=false;
const letter=n=>{let t='';for(n++;n;n=Math.floor((n-1)/26))t=String.fromCharCode(65+(n-1)%26)+t;return t};
const excelTime=iso=>Date.parse(iso+'Z')/86400000+25569;
for(const [key,rows] of Object.entries(input.tables)){
 const fields=input.schemas[key].fields,last=letter(fields.length-1),sheet=workbook.worksheets.add(input.schemas[key].label);
 const values=[fields.map(f=>f.label),...rows.map(r=>fields.map(f=>f.type==='datetime'&&r[f.name]!=null?excelTime(r[f.name]):r[f.name]??null))];
 sheet.getRange(`A1:${last}${values.length}`).values=values;
 sheet.getRange(`A1:${last}${values.length}`).format={font:{name:'Arial',size:11,color:'#25394a'},rowHeight:28,verticalAlignment:'center'};
 sheet.getRange(`A1:${last}1`).format={fill:'#26394a',font:{name:'Arial',size:11,color:'#ffffff',bold:true},wrapText:true,rowHeight:40,horizontalAlignment:'center'};
 for(let i=0;i<fields.length;i++){
  const f=fields[i],col=letter(i),data=sheet.getRange(`${col}2:${col}${values.length}`);
  data.setNumberFormat(f.type==='datetime'?'yyyy-mm-dd hh:mm:ss':f.type==='float'?'0.000000':f.type==='int'?'#,##0':'@');
  data.format.horizontalAlignment=['datetime','float','int'].includes(f.type)?'right':'left';
  sheet.getRange(`${col}1:${col}${values.length}`).format.columnWidth=['note','conditions','randomization'].includes(f.name)?78:f.type==='datetime'?28:['id','study_id','part_member_id','operator_member_id','spec_id','protocol_version','reference'].includes(f.name)?32:24;
  if(['note','conditions','randomization','purpose'].includes(f.name)){data.format.wrapText=true;sheet.getRange(`A2:${last}${values.length}`).format.rowHeight=38}
  if(f.name==='state')data.dataValidation={rule:{type:'list',values:['有效','缺测','待核查','作废']}};
  if(f.name==='status')data.dataValidation={rule:{type:'list',values:['采集中','已结束']}};
  if(f.name==='kind')data.dataValidation={rule:{type:'list',values:['样件','操作员']}};
 }
 sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(key==='msa_observations'?4:1);sheet.showGridLines=false;
 sheet.tables.add(`A1:${last}${values.length}`,true,'Measurement_'+key);
}
workbook.recalculate();
console.log((await workbook.inspect({kind:'table',range:'测量重复观测!A1:J6',include:'values,formulas',tableMaxRows:6,tableMaxCols:10,maxChars:1800})).ndjson);
console.log((await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:10},maxChars:500})).ndjson);
for(const [sheetName,range,label] of [['采样说明','A2:B12','说明'],['测量系统试验','A1:H5','试验身份'],['测量系统试验','I1:P5','设计与时间'],['测量系统试验','Q1:U5','试验条件'],['测量试验样件与人员','A1:H7','样件与人员'],['测量重复观测','A1:H7','观测身份'],['测量重复观测','I1:O7','数值与工况']]){
 const preview=await workbook.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(new URL('msa-'+label+'.png',output),new Uint8Array(await preview.arrayBuffer()));
}
const file=await SpreadsheetFile.exportXlsx(workbook);await file.save(fileURLToPath(new URL('35_测量系统交叉采样_模拟.xlsx',output)));
console.log('Saved 35_测量系统交叉采样_模拟.xlsx');
