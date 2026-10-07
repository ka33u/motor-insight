// The graph has categorical sample labels; it is never a production time chart.
const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const finite=v=>typeof v==='number'&&Number.isFinite(v);
export const componentNames={repeatability:'重复性',operator:'操作员',interaction:'样件×操作员',reproducibility:'再现性（人员＋交互）',grr:'测量系统（重复＋再现）',part:'样件间',total:'总变异'};
export function measure(v){return !finite(v)?'未计算':v!==0&&(Math.abs(v)<.00001||Math.abs(v)>=1e7)?v.toExponential(5):v.toLocaleString('zh-CN',{maximumFractionDigits:8});}
export function componentBars(result,field){
 if(!result)return '<div class="empty">当前前提未满足，不绘制百分比。</div>';
 const rows=result.components.filter(c=>['repeatability','operator','interaction','part'].includes(c.key));
 return `<div class="msa-bars">${rows.map(c=>`<div><span>${componentNames[c.key]}</span><div class="msa-bar-track"><i style="width:${finite(c[field])?Math.max(0,Math.min(100,c[field])):0}%"></i></div><b>${measure(c[field])}${finite(c[field])?'%':''}</b></div>`).join('')}</div>`;
}
export function interactionChart(d){
 if(!d.result)return `<div class="empty">${d.study.unit==='bool'?'二值项目保留分类计数，不绘制连续量交互图。':'交叉采样尚不适用；先核对完整性与试验条件。'}</div>`;
 const parts=d.members.filter(m=>m.kind==='样件'),ops=d.members.filter(m=>m.kind==='操作员');
 if(ops.length>8)return '<div class="empty">操作员超过8位，均值详表保留全部成员；请用表格核对，避免线条难以辨识。</div>';
 const points=d.chart_points.filter(p=>p.eligible&&finite(p.value)),values=points.map(p=>p.value);
 if(!values.length||!parts.length||!ops.length)return '<div class="empty">没有可呈现的连续量。</div>';
 const lo=Math.min(...values),hi=Math.max(...values),pad=(hi-lo)*.12||Math.max(Math.abs(lo)*.01,.0001),min=lo-pad,max=hi+pad;
 if(!finite(min)||!finite(max)||!finite(max-min)||max<=min)return '<div class="empty">数值尺度不适合当前图形；原读数和计算明细保留。</div>';
 const w=Math.max(820,parts.length*64+100),h=320,left=86,right=w-28,top=30,bottom=264;
 const x=id=>left+parts.findIndex(p=>p.id===id)*(right-left)/Math.max(1,parts.length-1),y=v=>bottom-(v-min)/(max-min)*(bottom-top);
 const colors=['#146b57','#2456ac','#a55c19','#8c4298','#a13447','#466981','#605c25','#36368a'];
 const ticks=Array.from({length:5},(_,i)=>min+(max-min)*i/4);
 let svg=`<svg class="msa-interaction" style="min-width:${w}px" viewBox="0 0 ${w} ${h}" role="img" aria-label="按样件类别排列的操作员均值与全部重复读数，单位${escape(d.study.unit)}"><text x="${left}" y="17">原始读数（${escape(d.study.unit)}）</text>`;
 svg+=ticks.map(v=>`<line x1="${left}" y1="${y(v)}" x2="${right}" y2="${y(v)}" class="msa-grid-line"/><text x="${left-10}" y="${y(v)+4}" text-anchor="end">${escape(measure(v))}</text>`).join('');
 svg+=parts.map(p=>`<text x="${x(p.id)}" y="${bottom+24}" text-anchor="middle">${escape(p.blind_label)}</text>`).join('');
 ops.forEach((op,j)=>{
  const means=d.result.cell_means.filter(c=>c.operator_id===op.id),path=parts.map(p=>means.find(c=>c.part_id===p.id)).filter(c=>c&&finite(c.mean)).map((c,i)=>`${i?'L':'M'}${x(c.part_id)},${y(c.mean)}`).join(' ');
  svg+=`<path d="${path}" fill="none" stroke="${colors[j]}" stroke-width="2"/>`;
  svg+=points.filter(p=>p.operator_member_id===op.id).map(p=>`<circle cx="${x(p.part_member_id)+(j-(ops.length-1)/2)*5}" cy="${y(p.value)}" r="3.4" fill="${colors[j]}" opacity=".65" tabindex="0" role="button" data-msa-point="${escape(p.id)}" aria-label="${escape(p.part_label+' '+p.operator_label+' 第'+p.repeat+'轮 '+measure(p.value)+' '+d.study.unit)}"><title>${escape(p.id+' · '+measure(p.value)+' '+p.unit)}</title></circle>`).join('');
 });
 svg+='<text x="'+((left+right)/2)+'" y="310" text-anchor="middle">样件盲测标签（类别顺序，不是生产时间）</text></svg>';
 return `<div class="msa-chart-scroll">${svg}</div><div class="msa-chart-legend">${ops.map((op,j)=>`<span><i style="background:${colors[j]}"></i>${escape(op.blind_label)} · ${escape(op.operator_id)}</span>`).join('')}</div><p class="source">线：每个样件与操作员单元的均值。点：全部重复读数。线条差异提供核对线索，不直接认定人员责任或因果。</p>`;
}
export function createMSAWorkspace(h){
 const {api,esc,header,panel,table,modal,toast,go,$,$$,on,isCurrent,getModalRevision}=h;let serial=0;
 const f=measure,attempt=fn=>async(...args)=>{try{await fn(...args)}catch(e){toast(e.message)}};
 async function render(params,token){
  const list=await api('msa');if(!isCurrent(token))return;
  if(!list.rows.length){$('#main').innerHTML=header('测量系统交叉采样','先定义样件、操作员和重复次数，再核对测量数据。')+'<div class="empty">尚未导入独立测量试验；普通终检读数不能替代重复测量采样。</div>';return}
  const selected=params.get('study')||list.rows[0].id,q=new URLSearchParams({page:params.get('page')||'1'});if(params.get('receipt'))q.set('receipt',params.get('receipt'));
  const d=await api('msa/'+encodeURIComponent(selected)+'?'+q);if(!isCurrent(token))return;++serial;
  const s=d.study,c=d.coverage,r=d.result,key=encodeURIComponent(s.id),url=suffix=>'msa/'+key+suffix+'?'+new URLSearchParams({receipt:d.receipt});
  const navigate=fields=>go('msa',{study:s.id,receipt:d.receipt,...fields});
  const sourceTable=(rows,download=false)=>table(['来源对象','归档Excel / 表 / 行','资料版本'],rows.map(v=>[`${esc(v.dataset)}<br>${esc(v.key)}`,`${esc(v.filename)}<br>${esc(v.sheet)} · 第${v.row}行${download?`<br><a href="/api/imports/${esc(v.batch_id)}/file">读取归档原件</a>`:''}`,`v${v.revision}<br><small>源行 ${v.source_row_id}</small>`]));
  const row=p=>[`<button class="row-link" data-msa-point="${esc(p.id)}">${esc(p.id)}</button><small class="block">登记序号 ${p.run_order}</small>`,`${esc(p.part_label)}<small class="block">${esc(p.unit_id)}</small>`,`${esc(p.operator_label)}<small class="block">${esc(p.operator_id)}</small>`,p.repeat,`${f(p.value)} ${esc(p.unit)}`,`${p.eligible?'字段可用':'待核对'}<small class="block">${esc(p.reasons.join('；'))}</small>`,esc(p.measured?.replace('T',' ')||'缺少时间')];
  const matrix=table(['样件 / SN',...d.members.filter(m=>m.kind==='操作员').map(m=>m.blind_label+' / '+m.operator_id)],d.members.filter(m=>m.kind==='样件').map(p=>[`${esc(p.blind_label)}<small class="block">${esc(p.unit_id)}</small>`,...d.members.filter(m=>m.kind==='操作员').map(o=>{const cell=d.matrix.find(v=>v.part_id===p.id&&v.operator_id===o.id);return cell?`<button class="msa-cell ${cell.valid?'':'msa-cell-warn'}" data-msa-part="${esc(p.id)}" data-msa-op="${esc(o.id)}">${cell.registered} / ${s.repeat_count}<small class="block">${cell.valid?'完整':'需核对'}</small></button>`:'未建立单元'})]));
  const components=r?table(['变异分量','原始矩估计（单位²）','呈现方差（单位²）','SD（单位）','6×SD（单位）','方差占比','研究变异占比','公差占用'],r.components.map(v=>[componentNames[v.key],f(v.raw_variance)+(v.clamped?'<small class="block">负估计保留；呈现值截为0</small>':''),f(v.variance),f(v.sd),f(v.study_variation),f(v.variance_percent)+(finite(v.variance_percent)?'%':''),f(v.study_percent)+(finite(v.study_percent)?'%':''),f(v.tolerance_percent)+(finite(v.tolerance_percent)?'%':'')])):'<div class="empty">前提未满足，方差分解未计算。</div>';
  const anova=r?table(['来源','平方和（单位²）','自由度','均方（单位²）'],r.anova.map(v=>[componentNames[v.key]||v.key,f(v.ss),v.df,f(v.ms)])):'<div class="empty">当前不生成ANOVA。</div>';
  $('#main').innerHTML=header('测量系统交叉采样','独立试验数据、完整性核对、变异分解与Excel来源。',`<a href="#metrology">计量登记 ↗</a>　<a href="#spc">过程稳定性试验 ↗</a>`)+
   `<div class="notice ${d.state==='trial'?'':'warn'}"><b>全部合成数据 · ${d.state==='trial'?'交叉模型候选试算':'试算暂停'}</b><span>截止 ${esc(d.as_of.replace('T',' '))}</span></div>`+
   `<form id="msa-study-form" class="toolbar"><label>固定采样试验<select name="study">${list.rows.map(v=>`<option value="${esc(v.id)}" ${v.id===s.id?'selected':''}>${esc(v.id+' · '+v.name)}</option>`).join('')}</select></label><button class="primary">读取完整试验</button><button id="msa-refresh" type="button">刷新来源</button></form>`+
   `<div class="msa-identity"><b>${esc(s.name)}</b><span>${esc(s.product_id)} · ${esc(s.spec_id)} · ${esc(s.instrument_id)}</span><span>方案 ${esc(s.protocol_version)} · 方法 ${esc(s.measurement_method)} · 单位 ${esc(s.unit)}</span><span>${esc(s.started)} 至 ${esc(s.finished||'未结束')}</span></div><p class="source">${esc(d.notice)}</p>`+
   (d.issues.length?`<div class="notice warn"><div><b>需要核对的条件</b><ul>${d.issues.map(v=>`<li>${esc(v)}</li>`).join('')}</ul></div></div>`:'')+(d.warnings.length?`<p class="source">${esc(d.warnings.join('；'))}</p>`:'')+
   `<div class="msa-kpis">${[['已登记 / 计划',`${c.registered} / ${c.planned??'未定义'}`],['样件 × 操作员 × 重复',`${s.part_count} × ${s.operator_count} × ${s.repeat_count}`],['字段可用 / 待核对',`${c.eligible} / ${c.held}`],['交叉单元待核对',`${c.invalid_cells} / ${c.cells}`]].map(([a,b])=>`<article><small>${a}</small><strong>${b}</strong></article>`).join('')}</div>`+
   panel('样件 × 操作员的完整性','每格显示登记数 / 计划重复数；点选核对全部轮次，缺测不补零、重复不择优删行',matrix)+
   `<div class="grid">${panel('试验计划与适用条件','固定方案，不通过页面筛选删除成员后重算',table(['计划项','当前声明'],[['随机与盲测',esc(s.randomization)],['工况',esc(s.conditions)],['目的',esc(s.purpose)],['负责人',esc(s.owner_id)],['校准登记范围',d.calibration.state==='registered'?'所引登记时间覆盖试验窗口':'登记依据待核对'],['所引校准',esc(d.calibration.selected?.id||'未选定')],['模拟双侧公差',`${f(d.spec?.lsl)}～${f(d.spec?.usl)} ${esc(s.unit)}`],['公差宽度',`${f(d.tolerance)} ${esc(s.unit)}`]]))}${panel('模型与计算定义','完整交互始终保留；没有P值筛选或自动合并',`<p>${esc(d.model_policy)}</p><p>研究变异采用 6×SD；公差占用 = 6×SD / 同单位双侧公差宽度。</p><p>原始四个方差分量可归一为100%。再现性、测量系统和总变异是合计项，不能再次累计。</p><p>当前不生成合格阈值、ndc、Cp/Cpk或产品放行结论。</p><code>${esc(d.rule_version)}</code>`)}</div>`+
   (s.unit==='bool'?panel('原始二值分类','分类计数保留，连续测量模型暂停',table(['原始值','已登记计数'],Object.entries(d.category_counts).map(([a,b])=>[a,b]))):'')+
   panel('样件与操作员的均值对照','保留全部重复读数，横轴为样件类别',interactionChart(d))+
   `<div class="grid">${panel('方差占比','分量方差 / 总方差；四个基本分量之和为100%（总方差非零时）',componentBars(r,'variance_percent'))}${panel('研究变异占比','分量SD / 总SD；各分量百分比不能相加作100%',componentBars(r,'study_percent'))}</div>`+
   panel('方差分解明细',`方差单位 ${esc(s.unit)}²，SD与6×SD单位 ${esc(s.unit)}；这些结果是合成模型试算`,components)+panel('ANOVA明细','平衡交叉全交互模型；平方和与自由度保留，合计均方不适用',anova)+
   (r?panel('成员均值详表','均值用于核对，不等于校准偏倚或真实值',table(['对象类别','成员','均值（'+s.unit+'）'],[...d.members.filter(m=>m.kind==='样件').map(m=>['样件',esc(m.blind_label+' / '+m.unit_id),f(r.part_means[m.id])]),...d.members.filter(m=>m.kind==='操作员').map(m=>['操作员',esc(m.blind_label+' / '+m.operator_id),f(r.operator_means[m.id])])])):'')+
   `<div class="toolbar"><b>观测与来源 · ${d.total}条</b><a href="/api/${esc(url('/export'))}">导出全部观测 CSV</a><button id="msa-sources">查看全部来源</button></div>${table(['观测 / 顺序','样件','操作员','轮次','原读数','字段检查','实测时间'],d.rows.map(row))}<div class="toolbar"><button id="msa-prev" ${d.page<=1?'disabled':''}>上一页</button><span>第 ${d.page} 页 / ${Math.max(1,Math.ceil(d.total/d.size))} 页</span><button id="msa-next" ${d.page*d.size>=d.total?'disabled':''}>下一页</button></div><p class="source">翻页只影响明细列表，完整性、图形和方差分解始终使用同一完整试验。来源凭据有效 ${d.receipt_seconds} 秒；资料或权限变化后需重新读取。</p>`;
  const point=attempt(async id=>{const rev=++serial,m=getModalRevision(),v=await api(url('/points/'+encodeURIComponent(id)));if(!isCurrent(token)||rev!==serial||m!==getModalRevision())return;const p=v.row;modal('测量观测 · '+id,table(['字段','资料'],[['样件 / SN',esc(p.part_label+' / '+p.unit_id)],['操作员 / 工号',esc(p.operator_label+' / '+p.operator_id)],['重复轮次 / 登记顺序',`${p.repeat} / ${p.run_order}`],['原读数 / 单位',`${f(p.value)} ${esc(p.unit)}`],['字段检查',p.eligible?'字段可用；整体门槛仍以试验状态为准':esc(p.reasons.join('；'))],['实测 / 登记时间',esc(p.measured+' / '+p.registered)],['原依据',esc(p.reference)]])+sourceTable(v.sources,v.can_download_original));});
  function bindPoints(root=$('#main')){$$('[data-msa-point]',root).forEach(b=>{b.addEventListener('click',()=>point(b.dataset.msaPoint));if(b.tagName.toLowerCase()==='circle')b.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();point(b.dataset.msaPoint)}})});}
  bindPoints();on('#msa-study-form','submit',e=>{e.preventDefault();go('msa',{study:new FormData(e.target).get('study')})});on('#msa-refresh','click',()=>go('msa',{study:s.id}));on('#msa-prev','click',()=>navigate({page:d.page-1}));on('#msa-next','click',()=>navigate({page:d.page+1}));
  $$('[data-msa-part]').forEach(b=>b.addEventListener('click',attempt(async()=>{const rev=++serial,m=getModalRevision(),v=await api(url('/cells/'+encodeURIComponent(b.dataset.msaPart)+'/'+encodeURIComponent(b.dataset.msaOp)));if(!isCurrent(token)||rev!==serial||m!==getModalRevision())return;modal('交叉采样单元',`<p>缺少轮次：${esc(v.cell.missing_repeats.join('、')||'无')}。重复轮次：${esc(v.cell.duplicate_repeats.join('、')||'无')}。</p><p>${esc(v.notice)}</p>`+table(['观测','样件','操作员','轮次','原数值','字段检查','实测时间'],v.rows.map(row)));bindPoints($('#dialog-content'));})));
  on('#msa-sources','click',attempt(async()=>{const rev=++serial,m=getModalRevision(),rows=[];let page=1,total=1;while(rows.length<total){const v=await api(url('/sources')+'&page='+page++);if(!isCurrent(token)||rev!==serial||m!==getModalRevision())return;total=v.total;if(!v.rows.length||page>150)throw Error('来源分页不完整，请重新读取');rows.push(...v.rows)}modal('完整试验来源',sourceTable(rows));}));
 }
 return render;
}
