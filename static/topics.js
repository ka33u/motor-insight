import {applyPage} from './topic_pages.js';
import {bindJourney,journeyRoute,loadJourney,sameConfig} from './topic_journey.js';
import {scopeSummaryMarkup} from './bi_card_summary.js';
import {linkMarkup,linkPicker,linkText,markRows,bindMarks} from './topic_linkage.js';
import {quantileExplanation} from './quantiles.js';
import {mountScatter} from './analysis_scatter.js';
import {mountPivotComparison,pivotCell} from './pivot_comparison.js';
import {derivedExplanation} from './derived.js';
import {groupingExplanation} from './groupings.js';
import {createTopicSnapshots} from './topic_snapshots.js';
export function createTopicWorkspace({pivotWorkspace,openAnalysisExplorer,api,esc,num,tag,header,panel,table,chart,modal,toast,go,$,$$,on,getState,isCurrent,editTopic,sourceLinks,localTime,getModalRevision}){
 const snapshots=createTopicSnapshots({pivotWorkspace,api,esc,num,header,panel,table,chart,modal,toast,go,$,$$,on,getState,isCurrent,localTime});
 const defaultConfig=()=>({scope:{},reference_scope:null,primary_label:'当前范围',reference_label:'对照范围'});
 const clean=s=>Object.fromEntries(Object.entries(s).filter(([,v])=>v!==''));
 const valueText=v=>typeof v==='number'?num(v,4):esc(v??'—');
 const signed=v=>v==null?'—':(v>0?'+':'')+num(v,4);
 const close=()=>$('#detail').close();
 return async function render(params,token){
  const journey=journeyRoute(params);
  const topics=await api('topics');if(!isCurrent(token))return;getState().topics=topics;
  const topic=topics.find(t=>t.id===Number(params.get('id')));
  if(journey&&!topic)throw Error('探索路径中的专题已不可访问，请从专题列表重新进入');
  if(!topic){$('#main').innerHTML=header('专题空间','按业务问题组织分析。保存个人范围、比较两组对象，并从分组追溯到来源。',getState().user.can_edit?'<button class="primary" id="new-topic">＋ 创建专题</button>':'')+`<div class="cards">${topics.map((t,i)=>`<article class="topic-card"><div class="number">SPACE ${String(i+1).padStart(2,'0')} <span class="tag gray" style="float:right">v${t.version}</span></div><h2>${esc(t.name)}</h2><p>${esc(t.description)}</p><footer><small>${t.layout.length} 张分析卡 · ${t.is_public?'共享专题':'个人专题'}</small><a href="#topics?id=${t.id}">进入专题 ↗</a></footer></article>`).join('')}</div>`;on('#new-topic','click',()=>editTopic());return}
  if(params.get('snapshot'))return snapshots.render(topic,params.get('snapshot'),token);
  const page=params.get('page')?await api('topic-pages/'+encodeURIComponent(params.get('page'))+(params.get('page_version')?'?version='+encodeURIComponent(params.get('page_version')):'')):null;if(!isCurrent(token))return;
  if(page&&(page.topic_id!==topic.id||!page.ready)){ $('#main').innerHTML=header('个人页面需要核对','页面已归档、原专题或模型绑定已变，请在定义页核对后保存新版本。')+`<a href="#topic-pages?id=${encodeURIComponent(page.id)}">查看定义与历史 ↗</a>`;return; }
  const topicGo=fields=>go('topics',{...(page?{page:page.id,page_version:page.version}:{}),...fields});
  const [ctx,options]=await Promise.all([api(`topics/${topic.id}/workspace`),api('scopes')]);if(!isCurrent(token))return;
  let arrival=null;
  if(journey){
   const receipt=loadJourney(sessionStorage,getState().user.username,journey.handle);
   arrival=await api(`topics/${topic.id}/journey/resolve`,{method:'POST',body:{receipt,direction:journey.direction}});if(!isCurrent(token))return;
   if(arrival.context_token!==ctx.context_token)throw Error('目标定义已变化，请从原专题重新预览');
  }
  if(params.get('page_context')&&params.get('page_context')!==ctx.context_token)throw Error('目标专题定义变化，请回到原工作页重新准备导航');
  if(page&&JSON.stringify(page.current_binding.topic)!==JSON.stringify(ctx.binding))throw Error('个人页面与当前专题定义不一致，请重新读取');
  getState().topic=topic;const requested=params.get('view');let selected=ctx.views.find(v=>String(v.id)===requested)||null;
  if(requested&&!selected){$('#main').innerHTML=header('个人视角不可用','视角可能已归档、属于其他账号或已不可访问。')+`<a href="#topics?id=${topic.id}">返回专题，管理自己的视角</a>`;return}
  const storageKey=`motor-topic-workspace:${getState().user.username}:${topic.id}`;let conf=defaultConfig(),last=null,serial=0,evidenceSerial=0;
  try{const saved=JSON.parse(sessionStorage.getItem(storageKey)||'null');if(saved?.scope&&Object.hasOwn(saved,'reference_scope'))conf=saved}catch{}
  if(selected)conf=structuredClone(selected.config);
  if(arrival)conf=structuredClone(arrival.config);
  const coverage=key=>ctx.cards.filter(c=>c.available&&c.contract[key]).length;
  const scopeName=s=>[s.family||'全部产品族',s.customer_id?(options.customers.find(c=>c.id===s.customer_id)?.name||s.customer_id):'全部客户',(s.from||'不限开始')+' 至 '+(s.to||'不限结束')].join(' · ');
  const familyOptions=s=>'<option value="">全部产品族</option>'+[...new Set([...options.families,...(s.family?[s.family]:[])])].map(f=>`<option value="${esc(f)}" ${s.family===f?'selected':''}>${esc(f)}${options.families.includes(f)?'':' · 当前来源未找到'}</option>`).join('');
  const customerOptions=s=>'<option value="">全部客户</option>'+[...options.customers,...(s.customer_id&&!options.customers.some(c=>c.id===s.customer_id)?[{id:s.customer_id,name:'当前来源未找到'}]:[])].map(c=>`<option value="${esc(c.id)}" ${s.customer_id===c.id?'selected':''}>${esc(c.id+' · '+c.name)}</option>`).join('');
  function scopeForm(prefix,s,label){return `<fieldset class="topic-range"><legend>${label}</legend><div class="scope-grid"><label>产品族 · ${coverage('family')}/${ctx.cards.length}卡支持<select id="${prefix}-family">${familyOptions(s)}</select></label><label>客户 · ${coverage('customer_id')}/${ctx.cards.length}卡支持<select id="${prefix}-customer">${customerOptions(s)}</select></label><label>业务开始日期<input id="${prefix}-from" type="date" value="${esc(s.from||'')}"></label><label>业务结束日期<input id="${prefix}-to" type="date" value="${esc(s.to||'')}"></label></div></fieldset>`}
  function formValue(prefix){return clean({family:$('#'+prefix+'-family').value,customer_id:$('#'+prefix+'-customer').value,from:$('#'+prefix+'-from').value,to:$('#'+prefix+'-to').value})}
  function readForm(){const next={scope:formValue('scope'),reference_scope:$('#topic-compare').checked?formValue('reference'):null,primary_label:$('#primary-label').value.trim(),reference_label:$('#reference-label').value.trim(),...(conf.links?{links:structuredClone(conf.links)}:{})};for(const s of [next.scope,next.reference_scope])if(s?.from&&s?.to&&s.from>s.to)throw Error('开始日期不能晚于结束日期');return next}
  function writeForm(){for(const [prefix,s] of [['scope',conf.scope],['reference',conf.reference_scope||{}]]){for(const [field,key] of [['family','family'],['customer','customer_id'],['from','from'],['to','to']])$('#'+prefix+'-'+field).value=s[key]||''}$('#topic-compare').checked=conf.reference_scope!==null;$('#reference-range').hidden=conf.reference_scope===null;$('#primary-label').value=conf.primary_label;$('#reference-label').value=conf.reference_label}
  $('#main').innerHTML=header(topic.name,topic.description,`<a href="#topics">← 所有专题</a>${ctx.topic.can_edit?'<button id="edit-topic">编辑布局</button>':''}`)+`<section class="panel topic-view-bar"><div class="toolbar"><label>个人分析视角<select id="topic-view-select"><option value="">临时分析 · 未保存</option>${ctx.views.map(v=>`<option value="${v.id}" ${selected?.id===v.id?'selected':''}>${esc(v.name)}${v.stale?' · 定义待核对':''}</option>`).join('')}</select></label><button id="topic-view-save">另存个人视角</button><button id="topic-view-update" ${!selected||selected.stale?'disabled':''}>更新此视角</button><button id="topic-view-manage">管理视角</button></div><p class="panel-note" id="topic-view-status">${selected?'已载入个人视角 v'+selected.version:'当前为临时分析'} · ${esc(ctx.notice)}</p>${selected?.stale?`<div class="notice warn"><span>专题或模型定义已变，已保存视角暂停运行。请核对差异后更新，或选择临时分析。</span><button id="topic-view-rebind">核对新定义</button></div>`:''}</section><details id="topic-scope-editor" class="panel topic-scope" ${selected?'':'open'}><summary>调整范围和对照条件</summary><form id="topic-scope-form" class="editor"><div class="topic-compare-controls"><label>当前范围名称<input id="primary-label" maxlength="30" value="${esc(conf.primary_label)}" required></label><label class="topic-check"><input id="topic-compare" type="checkbox" ${conf.reference_scope!==null?'checked':''}>启用范围对照</label><label>对照范围名称<input id="reference-label" maxlength="30" value="${esc(conf.reference_label)}" required></label></div>${scopeForm('scope',conf.scope,'当前范围')}<div id="reference-range" ${conf.reference_scope===null?'hidden':''}>${scopeForm('reference',conf.reference_scope||{},'对照范围')}</div><div class="toolbar"><button class="primary" type="submit">应用到专题</button><button type="button" id="scope-reset">重置范围</button></div></form><p class="panel-note">${esc(options.note)} 不支持条件的卡片暂停计算。更改条件后点击应用；保存视角仅保存已应用条件。</p><div id="scope-error" class="inline-error" role="alert"></div></details><div id="scope-summary"></div><div class="grid topic-result-grid" id="topic-results"></div>`;
  const root=$('#topic-results');
  root.insertAdjacentHTML('beforebegin','<div class="toolbar"><button id="topic-journey-open">跨专题探索 ↗</button><span class="panel-note">逐卡核对范围，选择条件继承方式。</span></div>');
  if(arrival){root.insertAdjacentHTML('beforebegin',`<div class="notice"><span>${arrival.direction==='return'?'已返回原专题的临时分析':esc(arrival.source.name)+' → '+esc(arrival.target.name)+' · '+esc(arrival.mode_label)}<br>${esc(arrival.return_notice)} 结果读取当前数据。刷新会恢复此路径的起始范围；后续调整可另存个人视角。</span>${arrival.direction==='forward'?'<button id="topic-journey-return">返回原专题与范围</button>':''}</div>`);on('#topic-journey-return','click',()=>go('topics',{id:arrival.source.id,journey_back:journey.handle}));}
  bindJourney({api,esc,table,modal,toast,go,$,on,getModalRevision,isCurrent,token,topic,topics,ctx,username:getState().user.username,getApplied:()=>{
   if(!last||!last.cards.some(c=>c.primary)||!sameConfig(conf,last.config)||!sameConfig(readForm(),conf))throw Error('请先应用当前条件并完成计算，再跨专题探索');
   return structuredClone(last.config);
  }});
  if(page){
   root.insertAdjacentHTML('beforebegin',`<section class="topic-page-heading"><small>${esc(page.code)} · 页面 v${page.version}${page.version!==page.current_version?' · 历史编排，结果仍按当前数据计算':''}</small><h2>${esc(page.definition.title)}</h2><p>${esc(page.definition.question)}</p><p>使用节奏：${esc(page.definition.cadence)}</p><a href="#topic-pages?id=${encodeURIComponent(page.id)}&version=${page.version}">定义与历史 ↗</a><div class="toolbar">${page.definition.navigation.map((n,i)=>`<button data-page-navigation="${i}">${esc(n.label)} · ${n.mode==='inherit'?'继承完整条件':'开始新范围'}</button>`).join('')}</div><p>页面版本保存阅读布局；结果快照固定当次数值。未保存的范围修改请先点击应用，再导航。</p></section>`);
   $$('[data-page-navigation]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{
    const prepared=await api('topic-pages/'+encodeURIComponent(page.id)+'/navigate',{method:'POST',body:{version:page.version,receipt:page.receipt,index:Number(button.dataset.pageNavigation),config:structuredClone(conf)}});if(!isCurrent(token))return;
    sessionStorage.setItem(`motor-topic-workspace:${getState().user.username}:${prepared.topic_id}`,JSON.stringify(prepared.config));toast(prepared.notice);go('topics',{id:prepared.topic_id,page_context:prepared.context_token});
   }catch(e){if(isCurrent(token))toast(e.message)}finally{if(isCurrent(token))button.disabled=false}}));
  }else root.insertAdjacentHTML('beforebegin',`<div class="toolbar"><a href="#topic-pages?topic=${topic.id}">定义此专题的个人工作页 ↗</a></div>`);
  root.insertAdjacentHTML('beforebegin','<div id="topic-link-controls"></div>');
  function drawLinks(){const area=$('#topic-link-controls');area.innerHTML=linkMarkup(ctx,conf,esc);area.querySelectorAll('[data-link-remove],[data-link-clear]').forEach(b=>b.addEventListener('click',async()=>{const values=b.hasAttribute('data-link-clear')?[]:conf.links.selections.filter(s=>s.kind!==b.dataset.linkRemove);if(values.length)conf.links={...conf.links,selections:values};else delete conf.links;if(selected?.linkage_stale&&!conf.links){selected.linkage_stale=false;selected.stale=selected.changes.some(c=>c.kind!=='linkage');if(!selected.stale){$('#topic-view-update').disabled=false;$('#topic-view-rebind')?.closest('.notice')?.remove();}}storeConfig();await draw()}));}
  function storeConfig(){try{sessionStorage.setItem(storageKey,JSON.stringify(conf))}catch{}}
  $('.topic-view-bar').insertAdjacentHTML('afterend','<div class="toolbar snapshot-toolbar"><button id="topic-snapshot-save">保存本次结果快照</button><button id="topic-snapshot-list">查看结果快照</button><span class="panel-note">固定当次数值与来源，供后续复盘。</span></div>');
  on('#topic-snapshot-save','click',()=>snapshots.save(topic,last,token));on('#topic-snapshot-list','click',()=>snapshots.list(topic,token));
  on('#edit-topic','click',async()=>{getState().models=await api('models');editTopic(topic)});
  on('#topic-compare','change',()=>{$('#reference-range').hidden=!$('#topic-compare').checked});
  on('#topic-view-select','change',e=>{if(!e.target.value){try{sessionStorage.setItem(storageKey,JSON.stringify(conf))}catch{}}topicGo({id:topic.id,...(e.target.value?{view:e.target.value}:{})})});
  function updateStatus(){if(!$('#topic-view-status'))return;const dirty=selected&&JSON.stringify(conf)!==JSON.stringify(selected.config);$('#topic-view-status').textContent=(selected?`个人视角 v${selected.version}${dirty?' · 有未保存的条件修改':''}`:'临时分析 · 未保存')+' · '+ctx.notice}
  function viewForm(rebind=false,update=false){
    if(selected?.stale&&!rebind)throw Error('请先核对定义变化，或切换到临时分析');
    const changes=selected?.changes||[];
    modal(rebind?'核对专题与模型改版':update?'更新个人分析视角':'保存个人分析视角',`<form id="personal-view-form" class="editor"><label>视角名称<input name="name" maxlength="120" value="${esc(selected?.name||topic.name+' · 我的范围')}" required></label><div class="source">${esc(conf.primary_label)}：${esc(scopeName(conf.scope))}<br>${conf.reference_scope!==null?esc(conf.reference_label)+'：'+esc(scopeName(conf.reference_scope)):'未启用对照'}${conf.links?'<br>两侧联动：'+esc(linkText(ctx,conf)):''}<br>仅保存已应用条件；不保存结果数值，不修改专题或模型。</div>${rebind?table(['变化对象','原版本','当前版本'],changes.map(c=>[c.kind==='topic'?'专题布局':c.kind==='linkage'?'联动规则':'第'+(c.slot+1)+'张卡',esc(c.before??c.before_version??'无'),esc(c.after??c.after_version??'不可用')]))+`<label>重新核对依据<textarea name="reason" minlength="5" maxlength="1000" required placeholder="确认新布局、模型含义与两侧范围仍适用"></textarea></label><p class="source">保存后明确改用当前定义；旧绑定留在审计中。请检查每张卡的口径与范围。</p>`:''}<button class="primary" type="submit">${rebind?'确认当前定义并更新视角':update?'保存视角修改':'保存为个人视角'}</button></form>`);
    on('#personal-view-form','submit',async e=>{e.preventDefault();const f=new FormData(e.target),b=$('button[type="submit"]',e.target);b.disabled=true;try{const body={name:f.get('name'),config:conf,context_token:ctx.context_token,...(update||rebind?{version:selected.version,rebind,reason:rebind?f.get('reason'):''}:{})};const v=await api(`topics/${topic.id}/views${update||rebind?'/'+selected.id:''}`,{method:'POST',body});close();toast('个人视角已保存');topicGo({id:topic.id,view:v.id})}finally{b.disabled=false}});
  }
  on('#topic-view-save','click',()=>viewForm());on('#topic-view-update','click',()=>viewForm(false,true));on('#topic-view-rebind','click',()=>viewForm(true,true));
  async function manage(archived=false){
    const data=await api(`topics/${topic.id}/workspace${archived?'?archived=true':''}`);if(!isCurrent(token))return;
    modal('我的分析视角',`<div class="toolbar"><button id="view-active">使用中</button><button id="view-archived">已归档</button></div><p class="source">归档后可恢复。仅显示当前账号保存的视角。</p>${table(['名称 / 版本','定义状态','操作'],data.views.map(v=>[`${esc(v.name)}<br><small>v${v.version} · ${localTime(v.updated_at)}</small>`,v.stale?'需要重新核对':'与当前定义一致',`${!archived?`<button data-view-open="${v.id}">打开</button> `:''}<button data-view-archive="${v.id}">${archived?'恢复':'归档'}</button>`]))}`);
    on('#view-active','click',()=>manage(false));on('#view-archived','click',()=>manage(true));
    $$('[data-view-open]').forEach(b=>b.addEventListener('click',()=>{close();topicGo({id:topic.id,view:b.dataset.viewOpen})}));
    $$('[data-view-archive]').forEach(b=>b.addEventListener('click',async()=>{b.disabled=true;try{const v=data.views.find(v=>v.id===+b.dataset.viewArchive);await api(`topics/${topic.id}/views/${v.id}/archive`,{method:'POST',body:{version:v.version,archived:!archived}});close();toast(archived?'个人视角已恢复':'个人视角已归档');topicGo({id:topic.id})}catch(e){b.disabled=false;toast(e.message)}}));
  }
  on('#topic-view-manage','click',()=>manage());
  async function draw(){
    const request=++serial,current=structuredClone(conf);last=null;updateStatus();drawLinks();
    if(selected?.stale){root.innerHTML='<div class="empty span2">该视角的定义需要重新核对，未计算数据。</div>';return}
    $('#scope-summary').innerHTML=`<div class="notice"><span><b>${esc(current.primary_label)}</b>：${esc(scopeName(current.scope))}${current.reference_scope!==null?'<br><b>'+esc(current.reference_label)+'</b>：'+esc(scopeName(current.reference_scope)):''}</span><span>状态截至 ${esc(options.as_of.replace('T',' '))}</span></div>${current.reference_scope!==null?'<p class="source">'+esc(ctx.compare_note)+'</p>':''}`;
    root.innerHTML='<div class="empty span2">正在按同一模型核对范围与计算结果…</div>';
    try{
      const result=await api(`topics/${topic.id}/run`,{method:'POST',body:{context_token:ctx.context_token,config:current}});if(!isCurrent(token)||request!==serial||!root.isConnected)return;last=result;
      root.innerHTML=result.cards.map(c=>`<section class="panel ${c.span===2?'span2':''}" id="topic-card-${c.slot}"></section>`).join('')||'<div class="empty span2">此专题尚无分析卡，请先添加模型。</div>';
      for(const c of result.cards)drawCard(c,result);
      if(page)applyPage(root,page.definition,esc);
      $('#scope-summary').insertAdjacentHTML('beforeend',`<div class="toolbar"><a href="/api/topics/${topic.id}/summary/export?${esc(new URLSearchParams({context_token:result.context_token,facts_token:result.facts_token,summary_token:result.summary_token,config:JSON.stringify(result.config)}).toString())}" download>导出全专题整范围摘要 ↓</a></div>`);
      if(result.same_scope)$('#scope-summary').insertAdjacentHTML('beforeend','<p class="source">当前与对照条件完全相同；两边读取同一范围，不代表两个时期的变化。</p>');
    }catch(e){if(!isCurrent(token)||request!==serial||!root.isConnected)return;root.innerHTML=`<div class="empty span2">${esc(e.message)}</div>`;$('#scope-error').textContent=e.message}
  }
  const canLink=(group,model)=>model.definition.grouping_ref?false:model.definition.dimension==='family'?options.families.includes(group):model.definition.dimension==='customer_id'?options.customers.some(c=>c.id===group):false;
  async function linked(group,model){
    const field=model.definition.dimension;if(!canLink(group,model))return;
    conf.scope={...conf.scope,[field]:group};writeForm();try{sessionStorage.setItem(storageKey,JSON.stringify(conf))}catch{}await draw();
    toast('所选分组已应用到当前范围；对照范围保持原条件');
  }
  function comparisonTable(card,result){
    const r=card.primary,key=r.display_metric,rows=card.comparison.rows;
    return table([r.dimension_label,result.config.primary_label,result.config.reference_label,'差值','相对变化','证据'],rows.map((row,i)=>{const v=row.values.find(v=>v.key===key);return [esc(row.dimension),valueText(v.primary),valueText(v.reference),`${signed(v.delta)}${v.delta!=null&&v.delta_unit==='百分点'?' 百分点':''}`,v.relative_pct==null?`<span title="${esc(v.reason)}">—</span>`:signed(v.relative_pct)+'%',`<button data-compare-row="${i}">查看两侧</button>`]}));
  }
  function comparabilityNote(c){
    const q=c.comparability;if(!q)return '';
    const warning=q.configuration_available&&(!q.same_configuration_mix||q.primary_unknown_configuration||q.reference_unknown_configuration);
    return `<div class="source ${warning?'topic-mix-warning':''}"><b>可比性检查</b> · 两侧重叠 ${num(q.overlap_objects)} 个来源对象${q.configuration_available?` · 共同产品配置 ${num(q.shared_configuration_count)} 种<br>${warning?'两侧配置分布不同或有未知配置；差异不能直接解释为效率或成本改善。':'按来源行计数的配置构成相同，仍需核对其他比较条件。'}`:'<br>此模型无直接配置字段，未做同配置核对。'}<details><summary>查看配置与对象范围</summary><p>当前 ${num(q.primary_objects)} 个对象 / 对照 ${num(q.reference_objects)} 个对象；重叠对象分别出现在两侧。</p>${q.configuration_available?table(['配置编码','当前来源行数','对照来源行数'],[...new Set([...Object.keys(q.primary_configurations),...Object.keys(q.reference_configurations)])].sort().map(k=>[esc(k),num(q.primary_configurations[k]||0),num(q.reference_configurations[k]||0)]))+`<p>配置未知：当前 ${num(q.primary_unknown_configuration)} 行 / 对照 ${num(q.reference_unknown_configuration)} 行。</p>`:''}<p>${esc(q.note)}</p></details></div>`;
  }
  function drawCard(c,result){
    const linkedChart=(rows,...args)=>chart(markRows(rows,c.link_choices||[]),...args,true);
    const el=$('#topic-card-'+c.slot);if(c.error){el.innerHTML=`<h2>${esc(c.model?.name||'受限分析卡')}</h2><div class="empty"><span class="tag orange">本卡未计算</span><p class="inline-error">${esc(c.error)}</p></div>`;return}
    const r=c.primary,key=r.display_metric,ref=c.reference,comp=c.comparison;let graphic;
    if(r.scatter)graphic='<div class="topic-scatter"></div>';
    else if(r.pivot)graphic=`<div class="toolbar"><label>透视范围<select class="pivot-side">${ref?'<option value="comparison">逐格对照 · 差值与变化</option>':''}<option value="primary">${esc(result.config.primary_label)}</option>${ref?`<option value="reference">${esc(result.config.reference_label)}</option>`:''}</select></label></div>${comp?`<p class="source">${esc(comp.note)}</p>`:''}<div class="topic-pivot"></div>`;
    else if(comp?.blocked)graphic=`<div class="notice warn"><span>${esc(comp.note)}</span></div>`;
    else if(comp){const rows=comp.rows.map(row=>{const v=row.values.find(v=>v.key===key);return {dimension:row.dimension,current:v.reason.includes('计量单位不同')||typeof v.primary!=='number'?null:v.primary,reference:v.reason.includes('计量单位不同')||typeof v.reference!=='number'?null:v.reference}});graphic=linkedChart(rows,'dimension','current','bar','reference')+`<div class="legend"><span><i></i>${esc(result.config.primary_label)}</span><span><i class="pale"></i>${esc(result.config.reference_label)}</span></div>`+`<details class="topic-comparison-table"><summary>查看全部对照分组与差值</summary>${comparisonTable(c,result)}</details>`}
    else graphic=c.model.definition.chart==='table'?table([r.dimension_label,...r.labels],r.rows.map(row=>[esc(row.dimension),...r.measures.map(m=>typeof row[m.key]==='number'?num(row[m.key],4):esc(row[m.key]??'—'))])):linkedChart(r.rows,'dimension',key,c.model.definition.chart,null);
    el.innerHTML=`<div class="panel-head"><div><h2>${esc(c.model.name)}</h2><p>${esc(result.config.primary_label)} ${num(r.matched)} 条来源${ref?' / '+esc(result.config.reference_label)+' '+num(ref.matched)+' 条来源':''} · 日期：${esc(r.scope.date_label)}</p></div><button class="ghost scope-definition">口径与范围</button></div>${scopeSummaryMarkup(c.scope_summary,esc,num,{primary:result.config.primary_label,reference:result.config.reference_label})}${graphic}${comparabilityNote(c)}<div class="card-foot"><span>${esc(r.display_label)} · 模型v${c.model.version}${r.metric_receipt?' · 指标 '+esc(r.metric_receipt.key)+' v'+r.metric_receipt.version:''}</span><button class="ghost scope-evidence">下钻来源 ↗</button></div>${groupingExplanation(r,esc)}${derivedExplanation(r,esc,true)}${!r.pivot&&!r.scatter?quantileExplanation(r,esc,result.config.primary_label)+quantileExplanation(ref,esc,result.config.reference_label):''}<div class="toolbar">${comp?.blocked?'<button disabled>对照未就绪，暂不可导出</button>':`<a class="scope-export" href="/api/topics/${topic.id}/export?${esc(new URLSearchParams({context_token:result.context_token,facts_token:result.facts_token,config:JSON.stringify(result.config),slot:String(c.slot)}).toString())}" download>导出已返回结果 ↓</a>`}${!c.model.definition.grouping_ref&&['family','customer_id'].includes(c.model.definition.dimension)?'<span class="panel-note">在来源窗口可把分组应用到其他卡。</span>':''}</div>${r.scope.unknown_customer_rows||ref?.scope.unknown_customer_rows?`<p class="inline-error">客户归属未明确，当前侧排除 ${num(r.scope.unknown_customer_rows)} 条，对照侧排除 ${num(ref?.scope.unknown_customer_rows||0)} 条。</p>`:''}${r.truncated?'<p class="panel-note">当前最多返回1000组；导出也仅包含已返回分组，请缩小范围。</p>':''}`;
    el.insertAdjacentHTML('beforeend',linkPicker(c,esc));
    bindMarks(el,(i,side)=>selectLink(c,result,{...c.link_choices[i],side:side||c.link_choices[i].side}));
    const choice=el.querySelector('.topic-link-choice'),apply=el.querySelector('.topic-link-apply');
    if(choice){choice.onchange=()=>apply.disabled=choice.value==='';apply.onclick=()=>selectLink(c,result,c.link_choices[Number(choice.value)]);}
    on('.scope-definition','click',()=>modal(c.model.name+' · 口径与范围',`<dl class="definition-grid"><dt>对象粒度</dt><dd>${esc(r.grain)}</dd><dt>当前范围</dt><dd>${esc(scopeName(result.config.scope))}</dd><dt>对照范围</dt><dd>${result.config.reference_scope===null?'未启用':esc(scopeName(result.config.reference_scope))}</dd><dt>日期与状态</dt><dd>${esc(r.scope.date_label)}选择对象；状态截至${esc(result.as_of)}</dd><dt>业务边界</dt><dd>${esc(r.note)}</dd></dl><p class="source">${esc(ctx.compare_note)}</p>${groupingExplanation(r,esc)}${derivedExplanation(r,esc)}${quantileExplanation(r,esc,result.config.primary_label)}${quantileExplanation(ref,esc,result.config.reference_label)}<details><summary>全部度量、局部筛选与比率分子分母</summary><pre class="code-block">${esc(JSON.stringify({definition:c.model.definition,primary_components:r.components,reference_components:ref?.components,primary_missing:r.derived_notes,reference_missing:ref?.derived_notes,metric:r.metric_receipt,grouping:r.grouping_receipt},null,2))}</pre></details>`),el);
    if(r.scatter){mountScatter({root:el.querySelector('.topic-scatter'),primary:r,reference:ref,primaryLabel:result.config.primary_label,referenceLabel:result.config.reference_label,esc,num,table,onSelect:(side,point)=>evidence(c,result,side,point.dimension,1)});el.querySelector('.scope-evidence').hidden=true;}
    if(r.pivot){
     const show=side=>side==='comparison'?mountPivotComparison({root:el.querySelector('.topic-pivot'),comparison:comp,esc,num,primaryLabel:result.config.primary_label,referenceLabel:result.config.reference_label,onSelect:(which,selection)=>{const cell=pivotCell(c[which],selection);if(cell)pivotWorkspace.evidence(c.model,c[which],result.config[which==='primary'?'scope':'reference_scope'],cell,1,result.config[which==='primary'?'primary_label':'reference_label'])}}):pivotWorkspace.mount(el.querySelector('.topic-pivot'),c.model,c[side],result.config[side==='primary'?'scope':'reference_scope'],result.config[side==='primary'?'primary_label':'reference_label']);
     show(ref?'comparison':'primary');el.querySelector('.pivot-side').onchange=e=>show(e.target.value);el.querySelector('.scope-evidence').hidden=true;
    }
    if(!r.pivot&&c.model.definition.drilldown?.length){el.insertAdjacentHTML('beforeend',`<div class="toolbar"><button class="scope-drill-primary">逐层分析 · ${esc(result.config.primary_label)}</button>${ref&&!comp?.blocked?`<button class="scope-drill-reference">逐层分析 · ${esc(result.config.reference_label)}</button>`:''}</div>`);on('.scope-drill-primary','click',()=>openAnalysisExplorer(c.model,result.config.scope,result.config.primary_label),el);on('.scope-drill-reference','click',()=>openAnalysisExplorer(c.model,result.config.reference_scope,result.config.reference_label),el);}
    on('.scope-evidence','click',()=>evidence(c,result,'primary',null,1),el);
    $$('[data-compare-row]',el).forEach(b=>b.addEventListener('click',()=>evidence(c,result,'primary',comp.rows[+b.dataset.compareRow].dimension,1)));
  }
  let linkSerial=0;
  async function selectLink(card,result,choice){
    if(!choice||last!==result)return;const request=++linkSerial;
    try{const value=await api(`topics/${topic.id}/link-select`,{method:'POST',body:{context_token:result.context_token,facts_token:result.facts_token,config:result.config,slot:card.slot,side:choice.side,group:choice.group}});if(!isCurrent(token)||request!==linkSerial||last!==result)return;conf=value.config;writeForm();storeConfig();if($('#detail').open)close();await draw();toast('联动身份已应用当前与对照范围；日期和原模型条件保留')}catch(e){if(isCurrent(token)&&request===linkSerial&&last===result)toast(e.message)}
  }
  async function evidence(card,result,side,group,page){
    const request=++evidenceSerial;modal(card.model.name+' · 范围证据','<div class="empty">正在读取所选范围与分组…</div>');let data;
    try{data=await api(`topics/${topic.id}/evidence`,{method:'POST',body:{context_token:result.context_token,facts_token:result.facts_token,config:result.config,slot:card.slot,side,group,page}})}catch(e){if(isCurrent(token)&&request===evidenceSerial&&$('#detail').open)$('#dialog-content').innerHTML=`<div class="inline-error">${esc(e.message)}</div>`;return}
    if(!isCurrent(token)||request!==evidenceSerial||!$('#detail').open)return;
    const direct=group!==null&&card[side].rows.some(r=>r.dimension===group)?card.link_choices?.find(c=>c.group===group):null;
    const groups=[...new Set([...card.primary.rows,...(card.reference?.rows||[])].map(r=>r.dimension))],fields=data.fields,brief=fields.slice(0,5),s=side==='primary'?result.config.scope:result.config.reference_scope;
    modal(card.model.name+' · 范围证据',`<div class="toolbar"><label>选择范围<select id="topic-evidence-side"><option value="primary" ${side==='primary'?'selected':''}>${esc(result.config.primary_label)}</option>${card.reference?`<option value="reference" ${side==='reference'?'selected':''}>${esc(result.config.reference_label)}</option>`:''}</select></label><label>分组<select id="topic-evidence-group"><option value="all">全部已筛选对象</option>${groups.map((g,i)=>`<option value="${i}" ${g===group?'selected':''}>${esc(g)}</option>`).join('')}</select></label>${direct?'<button id="topic-evidence-direct">此身份联动筛选两侧专题</button>':group!==null&&canLink(group,card.model)?'<button id="topic-evidence-link">此分组筛选当前专题</button>':''}</div><div class="notice"><span>${esc(scopeName(s))}</span><span>${num(data.total)} 条来源 · 模型v${card.model.version}</span></div>${table([...brief.map(f=>f.label),'证据'],data.rows.map((r,i)=>[...brief.map(f=>esc(r.values[f.name]??'—')),`<button data-topic-evidence-row="${i}">全部字段与来源</button>`]))}<div class="pagination"><span>第 ${data.page} 页，每页30条</span><div><button id="topic-evidence-prev" ${page<=1?'disabled':''}>上一页</button><button id="topic-evidence-next" ${page*30>=data.total?'disabled':''}>下一页</button></div></div><div id="topic-evidence-details"></div>`);
    on('#topic-evidence-side','change',e=>evidence(card,result,e.target.value,group,1));on('#topic-evidence-group','change',e=>evidence(card,result,side,e.target.value==='all'?null:groups[+e.target.value],1));on('#topic-evidence-prev','click',()=>evidence(card,result,side,group,page-1));on('#topic-evidence-next','click',()=>evidence(card,result,side,group,page+1));
    on('#topic-evidence-direct','click',()=>selectLink(card,result,{...direct,side}));
    on('#topic-evidence-link','click',async()=>{close();await linked(group,card.model)});
    $$('[data-topic-evidence-row]').forEach(b=>b.addEventListener('click',()=>{const r=data.rows[+b.dataset.topicEvidenceRow];$('#topic-evidence-details').innerHTML=`<div class="source">${r.source?`Excel：${esc(r.source.file)} · ${esc(r.source.sheet)} · 第${r.source.row}行`:'跨表模型预聚合后关联，以下列出实际参与的业务来源。'}</div><dl class="definition-grid">${fields.map(f=>`<dt>${esc(f.label)}</dt><dd>${esc(r.values[f.name]??'—')}</dd>`).join('')}</dl>${r.references.length?sourceLinks(r.references):''}`;$$('[data-lineage]',$('#topic-evidence-details')).forEach(a=>a.addEventListener('click',close))}));
  }
  on('#topic-scope-form','submit',async e=>{e.preventDefault();try{conf=readForm();$('#scope-error').textContent='';try{sessionStorage.setItem(storageKey,JSON.stringify(conf))}catch{}await draw();if(last)$('#topic-scope-editor').open=false}catch(err){$('#scope-error').textContent=err.message}});
  on('#scope-reset','click',async()=>{conf=defaultConfig();writeForm();try{sessionStorage.removeItem(storageKey)}catch{}$('#scope-error').textContent='';await draw()});
  await draw();
  if(isCurrent(token)){
   const cardsSection=document.createElement('div');cardsSection.id='topic-personal-model-cards';$('#main').appendChild(cardsSection);
   try{const html=await personalModelCardTopicMarkup(topic,{api,esc,panel,table});if(isCurrent(token)&&cardsSection.isConnected)cardsSection.innerHTML=html}
   catch(e){if(isCurrent(token)&&cardsSection.isConnected)cardsSection.textContent='个人模型口径卡暂未载入：'+e.message}
   const section=document.createElement('div');section.id='topic-personal-spc';$('#main').appendChild(section);
   try{const html=await personalSPCTopicMarkup(topic,{api,esc,panel,table,localTime});if(isCurrent(token)&&section.isConnected)section.innerHTML=html}
   catch(e){if(isCurrent(token)&&section.isConnected)section.textContent='个人受控试验暂未载入：'+e.message}
  }
 };
}
import {personalSPCTopicMarkup} from './spc_workspace.js';
import {personalModelCardTopicMarkup} from './model_cards.js';
