import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=new URL('../',import.meta.url),input=JSON.parse(await fs.readFile(new URL('data/oee_scenario.json',root),'utf8'));
const output=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root);await fs.mkdir(output,{recursive:true});
const workbook=Workbook.create(),intro=workbook.worksheets.add('导入说明');intro.tabColor='#829389';intro.showGridLines=false;
intro.getRange('A2').values=[['班次设备效率模拟采集']];
intro.getRange('A4:B14').values=[['项目','说明'],['输入','10个独立案例，5张原始输入表，共123行。'],['范围','SB-08-01-W01独立资源位，容量1。不同案例独立，不合成全设备或全厂产出。'],['期间','白班08至12点、13至16点计划生产；12至13点未计划生产。第9例晚于固定业务截止。'],['数量','首次经过等于首次良品、需返工、报废与未确认之和。返工后合格不重复记入首次良品。'],['时间','停机与计划窗口取交集；重叠停止合并，原因时长不能直接相加。'],['节拍','90或120秒每台均为合成理想条件假设，不能视为真实工艺标准或历史平均周期。'],['混配置','每配置窗口分别计算OEE。合计显示理想良品时间占比，不能平均OEE或混合不同单位数量。'],['暂停','缺节拍、质量未确认、采集未闭合、窗口重叠、未来实绩与无窗口保留为待核查案例。'],['方法参考','https://www.oee.com/calculating-oee/'],['数据性质','全部业务输入由本平台自编，参考资料仅用于公式。报产登记时间不能证明单台加工时刻。']];
intro.getRange('A2:B14').format={font:{name:'Arial',size:11,color:'#25394a'},verticalAlignment:'center'};intro.getRange('A2').format.font={name:'Arial',size:16,bold:true};intro.getRange('A4:B4').format={fill:'#26394a',font:{name:'Arial',size:11,color:'#fff',bold:true}};intro.getRange('A4:A14').format.columnWidth=18;intro.getRange('B4:B14').format.columnWidth=110;intro.getRange('B5:B14').format.wrapText=true;intro.getRange('A5:B14').format.rowHeight=40;
const letter=n=>{let t='';for(n++;n;n=Math.floor((n-1)/26))t=String.fromCharCode(65+(n-1)%26)+t;return t};
const excelTime=iso=>Date.parse(iso+'Z')/86400000+25569;
for(const [key,rows] of Object.entries(input.tables)){
 const fields=input.schemas[key].fields,last=letter(fields.length-1),sheet=workbook.worksheets.add(input.schemas[key].label),values=[fields.map(f=>f.label),...rows.map(r=>fields.map(f=>f.type==='datetime'?excelTime(r[f.name]):r[f.name]??null))];
 sheet.getRange(`A1:${last}${values.length}`).values=values;sheet.getRange(`A1:${last}${values.length}`).format={font:{name:'Arial',size:11,color:'#25394a'},rowHeight:30,verticalAlignment:'center'};
 sheet.getRange(`A1:${last}1`).format={fill:'#26394a',font:{name:'Arial',size:11,color:'#fff',bold:true},wrapText:true,rowHeight:42,horizontalAlignment:'center'};
 for(let i=0;i<fields.length;i++){
  const f=fields[i],col=letter(i),data=sheet.getRange(`${col}2:${col}${values.length}`),wide=['basis','scope','assumptions'].includes(f.name);
  data.setNumberFormat(f.type==='datetime'?'yyyy-mm-dd hh:mm:ss':f.type==='float'?'0.0000':f.type==='int'?'#,##0':'@');data.format.horizontalAlignment=['datetime','float','int'].includes(f.type)?'right':'left';
  sheet.getRange(`${col}1:${col}${values.length}`).format.columnWidth=wide?88:f.type==='datetime'?29:['id','study_id','window_id','resource_id'].includes(f.name)?34:26;
  if(wide){data.format.wrapText=true;sheet.getRange(`A2:${last}${values.length}`).format.rowHeight=48}
 }
 sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(1);sheet.showGridLines=false;sheet.tables.add(`A1:${last}${values.length}`,true,'OEE_'+key);
}
workbook.recalculate();
for(const key of Object.keys(input.tables))console.log((await workbook.inspect({kind:'table',range:input.schemas[key].label+'!A1:F4',include:'values,formulas',tableMaxRows:4,tableMaxCols:6,maxChars:900})).ndjson);
console.log((await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:10},maxChars:600})).ndjson);
const previews=[['导入说明','A2:B14','说明']];
for(const key of Object.keys(input.tables)){
 const s=input.schemas[key],last=letter(s.fields.length-1);previews.push([s.label,'A1:D5',key+'-身份']);previews.push([s.label,'E1:'+letter(Math.min(9,s.fields.length-1))+'5',key+'-内容']);if(s.fields.length>10)previews.push([s.label,'K1:'+last+'5',key+'-依据']);
}
for(const [sheetName,range,label] of previews){const p=await workbook.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(new URL('oee-'+label+'.png',output),new Uint8Array(await p.arrayBuffer()));}
await (await SpreadsheetFile.exportXlsx(workbook)).save(fileURLToPath(new URL('38_班次设备效率_模拟.xlsx',output)));console.log('Saved 38_班次设备效率_模拟.xlsx');
