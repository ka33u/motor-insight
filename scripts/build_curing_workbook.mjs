import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=new URL('../',import.meta.url),input=JSON.parse(await fs.readFile(new URL('data/curing_scenario.json',root),'utf8'));
const out=new URL('outputs/01a0f580-2480-7820-bc97-8ca293421c39/',root);await fs.mkdir(out,{recursive:true});
const workbook=Workbook.create(),letter=n=>String.fromCharCode(65+n),serial=s=>Date.parse(s+'Z')/86400000+25569;
for(const [ds,rows] of Object.entries(input.tables)){
 const schema=input.schemas[ds],fields=schema.fields,sheet=workbook.worksheets.add(schema.label),last=letter(fields.length-1);
 const data=[fields.map(f=>f.label),...rows.map(r=>fields.map(f=>r[f.name]==null?null:f.type==='datetime'?serial(r[f.name]):r[f.name]))];
 sheet.showGridLines=false;sheet.getRange(`A1:${last}${data.length}`).values=data;
 sheet.getRange(`A1:${last}${data.length}`).format={font:{name:'Arial',size:11,color:'#25394a'},rowHeight:36,verticalAlignment:'center'};
 sheet.getRange(`A1:${last}1`).format={fill:'#26394a',font:{name:'Arial',size:11,color:'#ffffff',bold:true},rowHeight:42,wrapText:true,horizontalAlignment:'center'};
 for(let i=0;i<fields.length;i++){
  const f=fields[i],col=letter(i),cells=sheet.getRange(`${col}2:${col}${data.length}`);
  cells.setNumberFormat(f.type==='datetime'?'yyyy-mm-dd hh:mm:ss"  "':f.type==='int'?'#,##0"  "':f.type==='float'?'0.000"  "':f.type==='bool'?'General':'@');
  cells.format.horizontalAlignment=['datetime','int','float'].includes(f.type)?'right':'left';
  sheet.getRange(`${col}1:${col}${data.length}`).format.columnWidth=['note','basis'].includes(f.name)?96:f.name==='reference'?72:f.type==='datetime'?29:f.name==='id'||f.reference?38:f.type==='float'?24:22;
  if(['note','basis','reference'].includes(f.name))cells.format.wrapText=true;
  if(f.name==='capture_state')cells.dataValidation={rule:{type:'list',values:['完整','部分','未采集']}};
  if(f.name==='quality')cells.dataValidation={rule:{type:'list',values:['有效','缺测','不可信']}};
 }
 sheet.tables.add(`A1:${last}${data.length}`,true,'Curing_'+ds);sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(2);
}
const guide=workbook.worksheets.add('导入说明');guide.showGridLines=false;
const notes=[['MotorInsight 固化温度曲线演练 · 详细合成输入与核对边界',null],['业务记录性质',input.notice],['工作簿规模',Object.entries(input.counts).map(([ds,n])=>input.schemas[ds].label+' '+n+'行').join('；')],
 ['前置来源','先经常规服务导入基础档案、路线、工单、批次、报工与独立资源位。所有编号取既有模拟Excel；不连接真实U8、MES或设备。'],
 ['模拟条件','炉温145至155℃（含边界），离散有效采样最多间隔5分钟；连续保温至少45分钟；全过程不超过170℃。均为自编条件，不是行业标准或批准工艺。'],
 ['时间解释','Excel时间为无时区的上海工厂墙钟，秒精度。业务截止固定为2026-10-01 18:00；筛选日期按曲线起点，登记时间与采样时间分开。'],
 ['区间计算','只有相邻有效℃点在保温范围内且间隔符合声明才支持该区间。缺测、无效值及过长间隔中断连续保温；不合并分离区段，不补零或外推。'],
 ['批次关系','每炉装载量为定子半成品件数。工单订单分配只提供订单线索，未采集装炉逐件订单对应、工件芯温或真实传感器校准证明。'],
 ['采集未闭合','旧报工已完成但曲线声明未闭合的案例仅表示资料未闭合，不表示现场此时仍在固化。未来案例无借用旧报工。'],
 ['异常演练','保留超温、短保温、断点、缺通道、错单位、重复时点/序号、配方过期/歧义、批次错配、数量越界、资源重叠和作废等原值。'],
 ['导入方式','数据表第一行是标准字段；说明页不是业务数据。使用预览、校验和正常提交，不从JSON写入业务库。'],
 ['核对场景','场景代码 / 预期状态（只供测试，不导入结论）'],...Object.entries(input.cases).map(([c,k])=>[c,k+' / '+input.expected[k]])];
guide.getRange(`A1:B${notes.length}`).values=notes;guide.getRange(`A1:B${notes.length}`).format={font:{name:'Arial',size:11,color:'#25394a'},verticalAlignment:'center',rowHeight:38};
guide.getRange('A1:B1').format={fill:'#26394a',font:{name:'Arial',size:14,color:'#ffffff',bold:true},rowHeight:48};
guide.getRange('A1:B1').merge();
guide.getRange(`A1:A${notes.length}`).format.columnWidth=29;guide.getRange(`B1:B${notes.length}`).format.columnWidth=120;guide.getRange('B2:B11').format.wrapText=true;guide.getRange('A2:B11').format.rowHeight=64;
guide.freezePanes.freezeRows(1);workbook.recalculate();
console.log((await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:10},maxChars:500})).ndjson);
for(const [ds,schema] of Object.entries(input.schemas)){
 const p=await workbook.render({sheetName:schema.label,range:'A1:D5',scale:1,format:'png'});await fs.writeFile(new URL('curing-'+ds+'.png',out),new Uint8Array(await p.arrayBuffer()));
 console.log((await workbook.inspect({kind:'table',range:schema.label+'!A1:D3',include:'values,formulas',tableMaxRows:3,tableMaxCols:4,maxChars:500})).ndjson);
}
for(const [range,label] of [['E1:J5','conditions'],['F1:J6','samples']]){
 const name=label==='conditions'?'固化规范通道':'固化温度采样',p=await workbook.render({sheetName:name,range,scale:1,format:'png'});await fs.writeFile(new URL('curing-'+label+'.png',out),new Uint8Array(await p.arrayBuffer()));
}
const p=await workbook.render({sheetName:'导入说明',range:'A1:B6',scale:1,format:'png'});await fs.writeFile(new URL('curing-guide.png',out),new Uint8Array(await p.arrayBuffer()));
await (await SpreadsheetFile.exportXlsx(workbook)).save(fileURLToPath(new URL('43_固化温度曲线_模拟.xlsx',out)));
console.log('Saved 43_固化温度曲线_模拟.xlsx');
