// Pure SVG geometry: fixed control limits come from the server study definition.
const finite=v=>typeof v==='number'&&Number.isFinite(v);
const text=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function spcChart(d,kind='i',showSpec=true){
 if(d.spec.unit==='bool')return kind==='mr'?'<div class="empty">二值项目不绘制移动极差图。</div>':`<div class="spc-binary">二值项目仅展示分类计数：0 值 ${d.category_counts?.['0']??0} 条，1 值 ${d.category_counts?.['1']??0} 条；不计算连续控制限。</div>`;
 if(d.study.method!=='I_MR'||!['设备计数（模拟）','人工顺序登记（模拟）'].includes(d.study.order_basis))return '<div class="empty">采样顺序或分析方法尚未核实，不按Excel行号绘制连续过程图。</div>';
 const points=d.chart_points||[],mr=kind==='mr',limits=d.limits||{},end=d.baseline_policy.baseline_end;
 const w=1000,h=290,l=76,r=22,t=30,b=50,iw=w-l-r,ih=h-t-b;
 const usable=points.filter(p=>p.eligible&&finite(mr?p.mr:p.value));
 const lines=mr?[[limits.mr_lcl,'MR LCL','control'],[limits.mr_mean,'MR均值','center'],[limits.mr_ucl,'MR UCL','control']]:
 [[limits.i_lcl,'I LCL','control'],[limits.center,'基线均值','center'],[limits.i_ucl,'I UCL','control'],...(showSpec?[[d.spec.lsl,'产品LSL','spec'],[d.spec.usl,'产品USL','spec']]:[])];
 const values=[...usable.map(p=>mr?p.mr:p.value),...lines.map(a=>a[0]).filter(finite)];
 if(!values.length)return '<div class="empty">没有适用的连续数值，保留观测清单和不适用原因。</div>';
 const lo=Math.min(...values),hi=Math.max(...values),pad=(hi-lo||Math.abs(hi)||1)*.12,min=lo-pad,max=hi+pad;
 const expected=Math.max(2,finite(d.coverage.planned)?d.coverage.planned:points.length),x=n=>l+(n-1)/(expected-1)*iw,y=v=>t+(max-v)/(max-min)*ih;
 const boundary=x(end+.5),grid=Array.from({length:5},(_,i)=>{const v=max-(max-min)*i/4;return `<line class="spc-grid" x1="${l}" x2="${w-r}" y1="${y(v)}" y2="${y(v)}"/><text x="${l-8}" y="${y(v)+4}" text-anchor="end">${v.toPrecision(4)}</text>`}).join('');
 let path='',previous=null;
 for(const p of points){const v=mr?p.mr:p.value;
  if(!p.eligible||!finite(v)){previous=null;continue}
  const connected=previous&&p.sequence===previous.sequence+1;
  path+=(connected?'L':'M')+x(p.sequence).toFixed(2)+','+y(v).toFixed(2)+' ';previous=p;
 }
 const controls=lines.filter(([v])=>finite(v)).map(([v,label,cls])=>`<line class="spc-limit spc-${cls}" x1="${l}" x2="${w-r}" y1="${y(v)}" y2="${y(v)}"/><text class="spc-limit-label spc-${cls}" x="${w-r-4}" y="${y(v)-5}" text-anchor="end">${label} ${v.toPrecision(5)}</text>`).join('');
 const markers=points.map(p=>{const v=mr?p.mr:p.value,valid=p.eligible&&finite(v);if(!finite(p.sequence)||p.sequence<1||p.sequence>expected)return '';
  const signal=mr?p.mr_signal:p.i_signal,label=`序号${p.sequence} · ${p.id} · ${valid?v:'不适用或缺测'}${signal?' · 规则信号':''}`;
  return `<g role="button" tabindex="0" data-spc-point="${text(p.id)}" aria-label="${text(label)}"><title>${text(label)}</title><circle cx="${x(p.sequence)}" cy="${valid?y(v):h-b+12}" r="${signal?5:3.5}" class="${valid?(signal?'spc-signal':'spc-observation'):'spc-held'}"/></g>`;
 }).join('');
 const ticks=[1,end,expected].filter((v,i,a)=>finite(v)&&v>=1&&v<=expected&&a.indexOf(v)===i).map(n=>`<text x="${x(n)}" y="${h-15}" text-anchor="middle">${n}</text>`).join('');
 return `<div class="spc-chart-scroll"><svg viewBox="0 0 ${w} ${h}" class="spc-chart" role="img" aria-label="${mr?'相邻移动极差':'单值'}候选控制图，固定基线末序号${end}"><title>${mr?'MR相邻移动极差':'I单值'} · ${text(d.study.id)}</title><desc>按声明采样序号排列；待核对、缺测和序号缺口断开连线。控制限始终来自固定基线，产品公差单独显示。</desc><rect x="${l}" y="${t}" width="${Math.max(0,Math.min(iw,boundary-l))}" height="${ih}" class="spc-baseline"/>${grid}<line x1="${boundary}" x2="${boundary}" y1="${t}" y2="${h-b}" class="spc-boundary"/><text x="${l+10}" y="18">固定基线 1～${end}</text><text x="${Math.min(w-160,boundary+10)}" y="18">监控段</text>${controls}<path d="${path}" class="spc-data-line"/>${markers}${ticks}<text x="${w/2}" y="${h-1}" text-anchor="middle">声明采样序号</text><text x="8" y="18">${mr?'移动极差':'标准数值'} ${text(d.study.unit)}</text></svg></div>`;
}

export function createSPCWorkspace(h){
 const {api,esc,num,header,panel,table,modal,toast,go,$,$$,on,isCurrent,localTime}=h;let detailSerial=0;
 return async function render(params,token){
  const snapshot=params.get('snapshot'),view=params.get('view'),mode=snapshot?'snapshot':view?'view':'study';
  const list=mode==='study'?await api('spc'):null;if(!isCurrent(token))return;
  if(list&&!list.rows.length){$('#main').innerHTML=header('过程稳定性试验','固定采样方案、基线与来源。')+'<div class="empty">尚未导入受控采样试验。历史终检记录没有可核验顺序时，不生成控制图。</div>';return}
  const selectedStudy=params.get('study')||list?.rows[0]?.id,page=params.get('page')||'1',q=new URLSearchParams({page});
  if(params.get('receipt'))q.set('receipt',params.get('receipt'));
  const endpoint=snapshot?'spc-result-snapshots/'+encodeURIComponent(snapshot):view?'spc-analysis-views/'+encodeURIComponent(view)+'/run':'spc/'+encodeURIComponent(selectedStudy);
  const d=await api(endpoint+'?'+q);if(!isCurrent(token))return;++detailSerial;
  const key=d.study.id,scope=snapshot?{snapshot}:view?{view}:{study:key},appearance=d.view?.definition?.display||{show_spec:true,decimals:6};
  const url=(suffix)=> (snapshot?'spc-result-snapshots/'+encodeURIComponent(snapshot):'spc/'+encodeURIComponent(key))+suffix+'?'+new URLSearchParams({receipt:d.receipt});
  const nav=fields=>go('spc',{...scope,receipt:d.receipt,...fields});
  const f=v=>v==null?'—':num(v,appearance.decimals),limits=d.limits,coverage=d.coverage,baseline=d.signal_counts.baseline,monitor=d.signal_counts.monitor;
  const cards=[['已登记 / 计划',`${coverage.recorded} / ${coverage.planned}`,`缺号 ${coverage.missing_sequences.length}，不会补零`],
   ['字段可用 / 待核对',`${coverage.eligible} / ${coverage.held}`,'字段通过检查仍不构成测量系统或独立性认定'],
   ['基线 I / MR 信号',`${baseline.i} / ${baseline.mr}`,`固定序号 1～${d.baseline_policy.baseline_end}`],
   ['监控 I / MR 信号',`${monitor.i} / ${monitor.mr}`,'同一点可命中两种信号，不相加作不合格数']];
  const row=p=>[`<button class="row-link" data-spc-point="${esc(p.id)}">${p.sequence} · ${esc(p.id)}</button><small class="block">${esc(p.unit_id)}</small>`,p.segment==='baseline'?'固定基线':'监控段',
   `${f(p.value)} ${esc(p.unit)}<small class="block">${esc(p.measured?.replace('T',' ')||'实际时间缺失')}</small>`,
   `${p.eligible?'字段检查通过':'待核对'}<small class="block">${esc(p.reasons.join('；'))}</small>`,
   `${f(p.mr)}<small class="block">I ${p.i_signal==null?'未计算':p.i_signal?'信号':'未命中'} · MR ${p.mr_signal==null?'未计算':p.mr_signal?'信号':'未命中'}</small>`,
   p.spec_outside==null?'未核对':p.spec_outside?'已测数值超模拟限值':'已测数值在模拟限内'];
  $('#main').innerHTML=header(snapshot?'受控试验 · 冻结结果':view?'受控试验 · 个人视角':'过程稳定性试验','以固定采样方案解释波动，逐点核对数值与来源。',`<a href="#spc-workspace">我的试验工作簿 ↗</a> <a href="#quality">质量与试验 ↗</a>`)+
   `<div class="notice ${limits?'':'warn'}"><b>全部合成数据 · ${limits?'候选算法试算':'控制限暂停'}</b><span>业务截止 ${esc(d.as_of.replace('T',' '))}</span></div>`+
   (mode==='study'?`<form id="spc-study-form" class="toolbar"><label>受控试验<select name="study" aria-label="受控试验">${list.rows.map(s=>`<option value="${esc(s.id)}" ${s.id===key?'selected':''}>${esc(s.id+' · '+s.name)}</option>`).join('')}</select></label><button class="primary">读取固定试验</button><button type="button" id="spc-refresh">刷新来源与凭据</button><button type="button" id="spc-save-view">保存个人视角</button></form>`:
    `<div class="spc-saved-context"><b>${esc(snapshot?d.snapshot.name:d.view.name)}</b><code>${esc(d.view.code)} · v${d.view.revision}</code><span>${snapshot?'冻结于 '+esc(localTime(d.snapshot.created_at))+' · '+d.snapshot.observations+'条观测':'保存定义，读取当前来源'}</span></div><div class="toolbar"><button id="spc-refresh">${snapshot?'刷新快照读取凭据':'刷新当前来源与凭据'}</button>${snapshot?'<button id="spc-compare-current">核对当前资料</button>':'<button id="spc-capture-view">冻结全部试验结果</button>'}</div>`)+
   `<div class="spc-identity"><b>${esc(d.study.name)}</b><span>${esc(d.study.product_id)} · ${esc(d.study.spec_id)} · ${esc(d.study.equipment_id)}</span><span>采样方案 ${esc(d.study.protocol_version)} · 方法 ${esc(d.study.measurement_method)} · ${esc(d.study.order_basis)}</span></div>`+
   `<p class="source">${esc(d.notice)}</p>${d.issues.length?`<div class="notice warn"><div><b>当前不适用原因</b><ul>${d.issues.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div></div>`:''}`+
   `${baseline.i||baseline.mr?'<div class="notice warn">固定基线已命中规则信号，需要调查采样或过程原因。当前保留原基线试算，不能据此认定过程稳定。</div>':''}`+
   `<div class="spc-kpis">${cards.map(([a,b,c])=>`<article><small>${a}</small><strong>${b}</strong><span>${c}</span></article>`).join('')}</div>`+
   `<div class="toolbar spc-legend"><span class="spc-legend-control">虚线：候选控制限</span><span class="spc-legend-spec">点线：模拟产品公差</span><span>红点：规则信号 · 灰点：待核对 / 不适用</span><label><input type="checkbox" id="spc-spec-visible" ${appearance.show_spec?'checked':''}>显示产品公差</label></div>`+
   panel('I 单值 · 固定基线与监控','单位、方法和配置由试验固定；点击或键盘选择数据点查看证据',`<div id="spc-i-chart">${spcChart(d,'i',appearance.show_spec)}</div>`)+
   panel('MR 相邻移动极差','仅计算实际相邻、适用的声明序号；不跨过缺测、重复或待核对记录',spcChart(d,'mr',false))+
   `<div class="grid">${panel('计算定义与界限','全部基线观测参与，页面翻页不重新估计',table(['定义','当前结果'],[
    ['固定基线',`1～${d.baseline_policy.baseline_end} · 可用${d.baseline_policy.baseline_points}条 · 相邻MR${d.baseline_policy.mr_pairs}对`],
    ['本项目试算门槛',`基线至少${d.baseline_policy.minimum}点；这是项目策略，不是稳定性证明`],['基线均值 / MR均值',`${f(limits?.center)} / ${f(limits?.mr_mean)}`],
    ['I LCL / UCL',`${f(limits?.i_lcl)} / ${f(limits?.i_ucl)}`],['MR LCL / UCL',`${f(limits?.mr_lcl)} / ${f(limits?.mr_ucl)}`],
    ['模拟产品 LSL / USL',`${f(d.spec.lsl)} / ${f(d.spec.usl)} · ${esc(d.study.unit)}`],['同单位已测数值超规范',`${coverage.spec_outside}条；不是正式质量处置结果`],
    ['固定计算式','I：均值 ± 3×MR均值/1.128；MR：0～3.267×MR均值'],['当前规则','单点严格越过控制限；未命中规则不表示过程稳定'],['Cp / Cpk','当前不计算']]))}
   ${panel('采样上下文与事件','事件提供调查线索，不能直接推断原因',`<p>${esc(d.study.conditions)}</p><p>测量系统依据：${esc(d.study.measurement_system_ref||'尚无工厂MSA与工况审定')}</p>${table(['序号 / 时间','事件','依据状态'],d.events.map(e=>[`${e.sequence} · ${esc(e.occurred)}`,`${esc(e.category)}<br>${esc(e.description)}`,e.context_valid?'模拟时间关系可核对':'事件关系待核对']))}<p class="panel-note">缺号：${coverage.missing_sequences.length?esc(coverage.missing_sequences.join('、')):'无'}。已登记资料仍可查看；不适用点不能解释为零。</p>`)}</div>`+
   `<div class="toolbar"><b>观测与来源 · ${d.total}条</b><a href="/api/${esc(url('/export'))}"><button>导出全部试验观测 CSV</button></a>${snapshot?`<a href="/api/${esc(url('/export')+'&format=json')}">导出完整快照 JSON ↓</a>`:''}<button id="spc-sources">查看全部来源</button></div>`+
   table(['序号 / 观测 / SN','分段','原始标准值 / 时间','适用性','相邻MR / 信号','模拟产品限值'],d.rows.map(row))+
   `<div class="pagination"><span>第${d.page}页 · 每页${d.size}条；图形始终包含整个试验</span><div><button id="spc-prev" ${d.page<=1?'disabled':''}>上一页</button><button id="spc-next" ${d.page*d.size>=d.total?'disabled':''}>下一页</button></div></div>`+
   `<details class="spc-definition"><summary>版本、来源与适用范围</summary><p>模型 ${esc(d.rule_version)} · 凭据有效${d.receipt_seconds}秒；${snapshot?'内容固定，读取仍按当前权限核对。':'来源或账号变更后须刷新。'}</p><p>资料摘要 <code>${esc(d.source_hash)}</code></p><p>模型摘要 <code>${esc(d.rule_hash)}</code></p><p><a href="https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc322.htm" target="_blank" rel="noreferrer">NIST 单值控制图方法</a> · 基线、独立性、测量系统和真实现场条件仍需工厂确认。</p></details>`;
  const point=async id=>{const serial=++detailSerial;const v=await api(url('/points/'+encodeURIComponent(id)));if(!isCurrent(token)||serial!==detailSerial)return;
   const original=s=>v.original_base?v.original_base+s.source_row_id+'?'+new URLSearchParams({receipt:v.receipt}):'/api/imports/'+s.batch_id+'/file';
   const p=v.row;modal('采样观测 · '+id,`<p class="source">${esc(v.notice)}</p>${table(['属性',snapshot?'冻结资料':'当前资料'],[['序号 / SN',`${p.sequence} / ${esc(p.unit_id)}`],['实测 / 单位',`${f(p.value)} ${esc(p.unit)}`],['字段检查',p.eligible?'字段检查通过；总体方法门槛仍以试验状态为准':esc(p.reasons.join('；'))],['相邻MR',f(p.mr)],['时间',esc(p.measured||'实际时间缺失')],['登记',esc(p.registered)],['来源依据',esc(p.reference)]])}${table(['来源对象','Excel文件 / 表 / 行','版本'],v.sources.map(s=>[`${esc(s.dataset)} / ${esc(s.key)}`,s.missing?'来源缺失':`${esc(s.filename)}<br>${esc(s.sheet)} · 第${s.row}行${v.can_download_original?`<br><a href="${esc(original(s))}">下载归档原件 ↧</a>`:''}`,s.missing?'—':`v${s.revision}`]))}`)};
  const bind=()=>$$('[data-spc-point]',$('#main')).forEach(el=>{el.addEventListener('click',()=>point(el.dataset.spcPoint).catch(e=>toast(e.message)));if(el.tagName.toLowerCase()==='g')el.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();point(el.dataset.spcPoint).catch(x=>toast(x.message))}})});
  bind();on('#spc-study-form','submit',e=>{e.preventDefault();go('spc',{study:new FormData(e.target).get('study')})});on('#spc-refresh','click',()=>go('spc',scope));
  on('#spc-save-view','click',()=>go('spc-workspace',{create:'1',study:key}));on('#spc-capture-view','click',()=>go('spc-workspace',{capture:view}));on('#spc-compare-current','click',()=>go('spc-workspace',{compare:snapshot}));
  on('#spc-prev','click',()=>nav({page:d.page-1}));on('#spc-next','click',()=>nav({page:d.page+1}));
  on('#spc-spec-visible','change',e=>{$('#spc-i-chart').innerHTML=spcChart(d,'i',e.target.checked);$$('[data-spc-point]',$('#spc-i-chart')).forEach(el=>{el.addEventListener('click',()=>point(el.dataset.spcPoint).catch(x=>toast(x.message)));el.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();point(el.dataset.spcPoint).catch(x=>toast(x.message))}})})});
  on('#spc-sources','click',async()=>{const serial=++detailSerial;const rows=[];let p=1,total=1;while(rows.length<total){const v=await api(url('/sources')+'&page='+p++);if(!isCurrent(token)||serial!==detailSerial)return;total=v.total;rows.push(...v.rows)}
   modal('完整试验来源 · '+rows.length+'条',table(['对象','Excel文件 / 表 / 行','版本与摘要'],rows.map(s=>[`${esc(s.dataset)} / ${esc(s.key)}`,s.missing?'缺失':`${esc(s.filename)}<br>${esc(s.sheet)} · ${s.row}`,s.missing?'—':`v${s.revision}<small class="block">${esc(s.record_hash)}</small>`])))});
 };
}
