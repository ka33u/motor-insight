// Design metadata only. Counts describe candidate requirements, never delivery progress.
export function coverageRows(d,filters={}){
 const q=String(filters.q||'').trim().toLowerCase(),group=d.coverage_groups.find(g=>g.id===filters.group);
 return d.domains.filter(dom=>!filters.group||(group&&group.domains.includes(dom.code))).map(dom=>{
  const items=dom.items.filter(i=>(!q||JSON.stringify([dom.name,dom.code,i]).toLowerCase().includes(q))&&(!filters.priority||i.priority===filters.priority)&&(!filters.status||i.implementation===filters.status));
  return {...dom,items,total:items.length,partial:items.filter(i=>i.implementation==='模拟部分覆盖').length,planned:items.filter(i=>i.implementation==='待建设').length,pages:[...new Set(items.flatMap(i=>i.page_ids||[]))]};
 }).filter(x=>x.total);
}

// Design-only: validate a proposal against the catalog, without queries or writes.
export function buildBiDesignDraft(d,input){
 const models=d.framework.model_library||[],needs=d.domains.flatMap(dom=>dom.items.map(n=>({...n,domain_code:dom.code}))),errors=[];
 const model=models.find(m=>m.id===input.model),need=needs.find(n=>n.id===input.need),format=d.framework.presentation_choices.find(p=>p.id===input.format);
 const code=String(input.code||'').trim(),question=String(input.question||'').trim(),owner=String(input.owner||'').trim(),scope=String(input.scope||'').trim();
 if(!/^[A-Z][A-Z0-9._-]{2,79}$/.test(code))errors.push('分析编码需3—80位，以大写字母开头，使用大写字母、数字、点、下划线或短横线');
 if(!question||question.length>500)errors.push('请填写500字以内的决策问题');
 if(!owner||owner.length>200)errors.push('请填写200字以内的责任岗位');
 if(!scope||scope.length>2000)errors.push('请填写2000字以内的日期类型、观察范围及截止时点');
 if(!model||!need||!format)errors.push('请选择目录中的需求、分析模型及呈现方式');
 const metric=input.metric?d.metrics.find(m=>m.id===input.metric):null;
 if(input.metric&&!metric)errors.push('候选指标不存在');
 if(errors.length)return {errors,draft:null};
 const contract=d.framework.domain_data_contracts.find(c=>c.code===need.domain_code);
 return {errors:[],draft:{schema:'motor.bi.design-draft.v1',catalog_version:d.version,state:'设计草稿，待业务与数据评审',code,version:1,question,owner,
  requirement:{id:need.id,name:need.need,definition:need.definition,priority:need.priority,implementation:need.implementation,gap:need.gap},
  model:{id:model.id,name:model.name,grain:model.grain,collection_gate:model.collection_gate,guardrail:model.guardrail},
  metric_candidate:metric?{id:metric.id,name:metric.name,formula:metric.formula,grain:metric.grain,clock:metric.clock,source:metric.source,pitfalls:metric.pitfalls}:null,
  scope:{user_proposal:scope,domain_clock:contract.clock,dimensions:need.dimensions,comparison:'比较基线、同配置条件和目标依据须单独审定'},
  presentation:{id:format.id,name:format.name,reader:format.reader,density:format.density,cards:format.cards,visual:model.visual,detail:format.detail,drill:model.drill,mobile:format.mobile},
  action:{next_step:need.action,boundary:format.avoid,acceptance:need.acceptance},
  data_contract:contract,pending_confirmations:[...d.framework.studio_pending,...(metric?['所选指标与模型/需求的实际粒度和维度兼容性']:['主指标及可计算定义'])],notice:d.framework.studio_notice}};
}

export function renderBiDefinitionStudio(root,d,{esc,table}){
 const f=d.framework;if(!f.model_library)return;
 const needs=d.domains.flatMap(dom=>dom.items.map(n=>({...n,domain_name:dom.name}))),el=s=>root.querySelector(s);
 root.innerHTML=`<section class="bi-studio" aria-label="BI模型与定义工作坊"><div class="bi-studio-heading"><small>14种分析模型 · 受控自助设计</small><h2>把业务需求，变成可评审的BI定义</h2><p>${esc(f.studio_notice)}</p></div><details><summary>哪些对象可以自定义，编码和版本怎样管理？</summary>${table(['定义对象','回答什么','配置内容','示例编码','维护边界'],f.configurable_objects.map(r=>r.map(esc)))}${table(['规则','建议','边界'],f.coding_rules.map(r=>r.map(esc)))}</details><div class="bi-studio-layout"><form data-bi-draft-form><label>选择分析模型<select aria-label="选择分析模型" data-bi-draft-model>${f.model_library.map(m=>`<option value="${esc(m.id)}">${esc(m.name)}</option>`).join('')}</select></label><label>关联候选需求<select aria-label="关联候选需求" data-bi-draft-need>${needs.map(n=>`<option value="${esc(n.id)}">${esc(n.id+' '+n.need)}</option>`).join('')}</select></label><label>分析编码<input aria-label="分析设计编码" data-bi-draft-code maxlength="80" autocomplete="off"></label><label>要作出的决定<textarea aria-label="分析决策问题" data-bi-draft-question maxlength="500" rows="2"></textarea></label><label>责任岗位<input aria-label="分析责任岗位" data-bi-draft-owner maxlength="200"></label><label>候选主指标<select aria-label="候选主指标" data-bi-draft-metric><option value="">待定义 / 暂不指定</option>${d.metrics.map(m=>`<option value="${esc(m.id)}">${esc(m.id+' '+m.name)}</option>`).join('')}</select></label><label>呈现方式<select aria-label="草稿呈现方式" data-bi-draft-format>${f.presentation_choices.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select></label><label>范围与时间<textarea aria-label="分析范围与时间" data-bi-draft-scope rows="3" maxlength="2000" placeholder="填写：业务日期类型、观察期间、截止时点、配置与组织；比较基线另行确认"></textarea></label><a data-bi-draft-download class="bi-draft-download" aria-disabled="true">下载设计草稿 JSON</a><p data-bi-draft-errors aria-live="polite"></p></form><article data-bi-draft-preview aria-label="BI设计草稿预览"></article></div><details><summary>完整14种模型：问题、粒度、图形、证据与边界</summary>${table(['模型','决策问题 / 粒度','建议呈现 / 下钻','使用条件'],f.model_library.map(m=>[esc(m.name),esc(m.question)+'<br>'+esc(m.grain),esc(m.visual)+'<br>'+esc(m.drill),esc(m.guardrail)]))}</details><details><summary>按问题选图：14条呈现规则</summary>${table(['目的','图形','例子','防止误读'],f.chart_selection.map(r=>r.map(esc)))}</details><details><summary>尽量全面的需求，怎样检查遗漏？</summary>${table(['检查轴','候选范围','核对要求'],f.completeness_axes.map(r=>r.map(esc)))}${table(['工厂特点','定义与展示要求'],f.factory_specific_rules.map(r=>r.map(esc)))}</details></section>`;
 let current;
 function result(){return buildBiDesignDraft(d,{model:el('[data-bi-draft-model]').value,need:el('[data-bi-draft-need]').value,code:el('[data-bi-draft-code]').value,question:el('[data-bi-draft-question]').value,owner:el('[data-bi-draft-owner]').value,metric:el('[data-bi-draft-metric]').value,format:el('[data-bi-draft-format]').value,scope:el('[data-bi-draft-scope]').value})}
 function draw(){
  current=result();const errors=el('[data-bi-draft-errors]'),preview=el('[data-bi-draft-preview]'),model=f.model_library.find(m=>m.id===el('[data-bi-draft-model]').value),need=needs.find(n=>n.id===el('[data-bi-draft-need]').value);
  errors.textContent=current.errors.join('；');const download=el('[data-bi-draft-download]');download.setAttribute('aria-disabled',String(!!current.errors.length));download.setAttribute('tabindex',current.errors.length?'-1':'0');if(current.draft){download.href='data:application/json;charset=utf-8,'+encodeURIComponent(JSON.stringify(current.draft,null,2));download.download='BI设计草稿_'+current.draft.code+'.json'}else{download.removeAttribute('href');download.removeAttribute('download')}
  const draft=current.draft,format=f.presentation_choices.find(p=>p.id===el('[data-bi-draft-format]').value);
  preview.innerHTML=`<div class="bi-draft-badge">设计草稿 · 无经营数值</div><h3>${esc(model.name)}</h3><p><b>${esc(el('[data-bi-draft-question]').value)}</b></p><p>${esc(need.id+' '+need.need)} · ${esc(need.implementation)}</p><div class="bi-draft-scope"><b>范围与口径</b><p>${esc(el('[data-bi-draft-scope]').value||'请填写观察范围及截止时点')}</p><small>一行：${esc(model.grain)}；指标适用性待核验</small></div><div class="bi-draft-visual"><b>建议解释区</b><p>${esc(model.visual)}</p><small>呈现：${esc(format.name)} · ${esc(format.density)}</small></div><div class="bi-draft-action"><b>对象 → 证据 → 动作</b><p>${esc(model.drill)}</p><p>下一步：${esc(need.action)}</p></div><p><b>必须注意：</b>${esc(model.guardrail)}</p><details><summary>候选主指标定义与兼容性</summary>${draft?.metric_candidate?`<h4>${esc(draft.metric_candidate.name)}</h4><p>${esc(draft.metric_candidate.formula)}</p><p>${esc(draft.metric_candidate.grain+'；'+draft.metric_candidate.clock)}</p><p>${esc(draft.metric_candidate.pitfalls)}</p>`:'<p>主指标待定义；所选模型、需求与指标的粒度、关联和单位必须复核。</p>'}</details><p class="bi-caption">${esc(f.studio_pending.join(' · '))}</p>`;
 }
 function chooseModel(){const m=f.model_library.find(m=>m.id===el('[data-bi-draft-model]').value);el('[data-bi-draft-need]').value=m.example_need_id;el('[data-bi-draft-code]').value='ANA.'+m.id+'.DRAFT';el('[data-bi-draft-question]').value=m.question;el('[data-bi-draft-owner]').value=needs.find(n=>n.id===m.example_need_id).owner;el('[data-bi-draft-metric]').value=m.metric_ids[0]||'';el('[data-bi-draft-format]').value=m.id==='TRACE'?'object':m.id==='RECONCILIATION'?'ledger':m.id==='STATUS'||m.id==='CONSTRAINT'?'workbench':'analysis';draw()}
 el('[data-bi-draft-model]').onchange=chooseModel;
 el('[data-bi-draft-need]').onchange=()=>{el('[data-bi-draft-owner]').value=needs.find(n=>n.id===el('[data-bi-draft-need]').value).owner;draw()};
 root.querySelectorAll('input,textarea').forEach(x=>x.oninput=draw);['metric','format'].forEach(k=>el('[data-bi-draft-'+k+']').onchange=draw);
 el('[data-bi-draft-form]').onsubmit=e=>e.preventDefault();
 el('[data-bi-draft-download]').onclick=e=>{
  if(result().errors.length){e.preventDefault();return}
  const csrf=document.cookie.split('; ').find(x=>x.startsWith('csrftoken='))?.slice(10);
  if(!/^https?:$/.test(location.protocol)||!csrf||!['/','/bi-design'].includes(location.pathname))return;
  e.preventDefault();const form=document.createElement('form');form.method='POST';form.action='/api/catalog/design-draft/export';form.hidden=true;
  const input={model:el('[data-bi-draft-model]').value,need:el('[data-bi-draft-need]').value,metric:el('[data-bi-draft-metric]').value,format:el('[data-bi-draft-format]').value,code:el('[data-bi-draft-code]').value,question:el('[data-bi-draft-question]').value,owner:el('[data-bi-draft-owner]').value,scope:el('[data-bi-draft-scope]').value};
  for(const [name,value] of Object.entries({csrfmiddlewaretoken:decodeURIComponent(csrf),draft_input:JSON.stringify(input)})){const field=document.createElement('input');field.type='hidden';field.name=name;field.value=value;form.append(field)}
  root.append(form);form.submit();form.remove();
 };
 chooseModel();
 return {useNeed(id){const n=needs.find(x=>x.id===id);if(!n)return;el('[data-bi-draft-model]').value=f.model_library.find(m=>m.example_need_id===id)?.id||'STATUS';chooseModel();el('[data-bi-draft-need]').value=id;el('[data-bi-draft-code]').value='ANA.'+id.replace('-','.')+'.DRAFT';el('[data-bi-draft-question]').value=n.need+'：为决定“'+n.action+'”，应核对哪些对象和证据？';el('[data-bi-draft-owner]').value=n.owner;el('[data-bi-draft-scope]').value='';el('[data-bi-draft-metric]').value='';draw();root.scrollIntoView({block:'start'})}};
}

// Reused by the live catalog and standalone HTML. All values are design text.
export function renderBiExecutionDesign(root,d,{esc,table}){
 const plan=d.framework.execution_design;if(!plan)return;
 const metrics=new Map(d.metrics.map(m=>[m.id,m.name]));
 const metricNames=ids=>ids.length?ids.map(id=>id+' '+metrics.get(id)).join(' / '):'以对象队列与解释内容为主，不新增凑数指标';
 root.innerHTML=`<h2>把全景目录变成建设与使用方案</h2><p>${esc(plan.definition)}</p><p class="bi-caption">${esc(plan.scope_note)}</p><details open><summary>五类建设包：先补什么，什么时候进入？</summary>${table(['建议分类','候选数','分类依据','进入条件','维护投入'],plan.packages.map(p=>[esc(p.id+' '+p.name),String(p.candidate_count),esc(p.rule),esc(p.gate),esc(p.cost)]))}<p>这些是候选分类，未评审工期或真实就绪度。基础与首期页可并行；条件专题根据业务需要进入。</p></details><details><summary>26个部门领域：谁看、何时看、先回答什么？</summary>${table(['领域 / 岗位','决策与频率','内容范围 / 试点起步','容易误读的边界'],d.domains.map(dom=>{const s=dom.decision_session;return [esc(dom.code+' '+dom.name)+'<br>'+esc(s.review_owner),esc(s.question)+'<br>'+esc(s.cadence),esc(s.content)+'<br>'+esc(s.start),esc(s.blindspot)]}))}</details><details><summary>17页内容优先级：主结果、解释与护栏分开</summary>${table(['页面 / 用途','首屏结果候选','解释指标候选','可信度或业务护栏候选','阅读顺序 / 边界'],d.page_blueprints.map(p=>{const c=p.content_focus;return [esc(p.id+' '+p.name)+'<br>'+esc(c.mode),esc(metricNames(c.result_metric_ids)),esc(metricNames(c.driver_metric_ids)),esc(metricNames(c.guardrail_metric_ids)),esc(c.reading_path)+'<br>'+esc(c.boundary)]}))}<p>每页首屏选1—3个结果；指标引用仅为候选定义，并不证明该页面已实现或可立即计算。对象履历、班组页和手机优先查对象。</p></details><details><summary>低预算起步：四种来源怎样进入，怎样判断值得做？</summary>${table(['来源','起步方式','边界'],plan.collection_modes.map(r=>r.map(esc)))}${table(['取舍方向','评审问题'],plan.priority_review.map(r=>r.map(esc)))}${table(['就绪检查','需要核实'],plan.readiness_checks.map(r=>r.map(esc)))}</details><details><summary>创新体验：对象、证据、变化、协同、复盘和自助</summary>${table(['体验','呈现构思','启用边界'],plan.innovation_patterns.map(r=>r.map(esc)))}</details><p class="bi-caption">${esc(plan.review_status)} 可在下方逐项评审卡按建议建设包筛选；未决适用性、来源和责任需在实际试点确认。</p>`;
}

export function renderBiDecisionDesign(root,d,{esc,table}){
 const f=d.framework,books=f.decision_playbooks;
 if(!books)return;
 const count=d.domains.reduce((n,dom)=>n+dom.items.length,0);
 const overview=`<div class="bi-overview"><small class="bi-kicker">适配 U8 ＋ MES待上线 · 约900台/日 · 小批量定制 · 全流程自制</small><h2>BI：从可信数据，到岗位决策与复查</h2><p class="bi-lead">同一个订单、同一套口径、同一条证据链；每个岗位看见自己需要处理的问题。</p><div class="bi-layers">${f.bi_layers.map(([name,q,output,rule],i)=>`<article><span class="bi-step">${i+1}</span><div><h3>${esc(name)}</h3><b>${esc(q)}</b><p>${esc(output)}</p><small>${esc(rule)}</small></div></article>`).join('')}</div><div class="bi-overview-formats"><b>按用途呈现</b><span>经营首页 · 岗位工作台 · 专题分析 · 对象履历</span><span>对账报表 · 车间大屏 · 例会快照 · 受控外部视图</span></div><div class="bi-scope"><b>全景需求库 · ${d.domains.length}领域 / ${count}项候选 / ${d.metrics.length}项指标口径 / ${d.page_blueprints.length}页蓝图 / ${(f.model_library||[]).length}种分析模型</b><div>${d.coverage_groups.map(g=>`<span>${esc(g.name)}</span>`).join('')}</div></div><div class="bi-start"><b>先落地4页</b><span>订单交付 → 质量试验 → 单台追溯 → 数据可信度</span><small>经营首页汇总已核实结果；库存、成本、资源与预测按数据条件扩展。</small></div><p class="bi-caption">蓝图设计与已有模拟功能分别标注；尚未接入真实 U8/MES，不将候选数量作为完成率。</p></div>`;
 const panels=books.map((b,i)=>`<article class="bi-playbook" data-playbook="${esc(b.id)}" ${i?'hidden':''} aria-label="${esc(b.name)}场景设计"><div class="bi-playbook-heading"><div><small>${esc(b.owner)}</small><h3>${esc(b.question)}</h3></div><span class="bi-design-only">页面结构示意 · 数值待接入</span></div><div class="bi-range">范围条：业务日期类型 · 截止点 · 产品配置 · 组织 / 客户 · 来源更新时间</div><div class="bi-kpis">${b.cards.map(c=>`<div><small>${esc(c)}</small><strong>—</strong><span>按已确认口径取数</span></div>`).join('')}</div><div class="bi-visual"><b>解释区</b><p>${esc(b.visual)}</p><small>点击分组进入同范围对象；趋势、目标和预测仅在具备对应数据后显示。</small></div><h4>对象清单 · 以下仅示范字段结构</h4>${table(b.columns,[b.example.map(esc)])}<h4>证据路径</h4><div class="bi-evidence-path">${b.path.map((p,n)=>`<span>${n+1}. ${esc(p)}</span>`).join('<i aria-hidden="true">→</i>')}</div><div class="bi-rules"><p><b>定义：</b>${esc(b.definition)}</p><p><b>动作：</b>${esc(b.action)}</p><p><b>边界：</b>${esc(b.gate)}</p><p><b>需要的数据：</b>${esc(b.source)}</p></div><p class="bi-caption">对应需求：${esc(b.needs.join(' / '))}　·　页面蓝图：${esc(b.pages.join(' / '))}</p></article>`).join('');
 root.innerHTML=overview+`<div class="bi-workbench"><h2>6个跨部门场景，统一阅读顺序</h2><p>选一个场景，查看结果卡、解释图、对象清单、证据和动作如何组合。此处展示目标设计，具体实施状态见需求目录。</p><div class="bi-playbook-tabs" role="group" aria-label="选择BI场景">${books.map((b,i)=>`<button data-playbook-select="${esc(b.id)}" aria-pressed="${!i}" class="${!i?'active':''}">${esc(b.name)}</button>`).join('')}</div>${panels}<details class="bi-design-methods"><summary>谁来定义BI，怎样从需求交付到页面？</summary>${table(['使用者','定义方式','边界与责任'],f.definition_methods.map(r=>r.map(esc)))}<h3>统一页面结构</h3>${table(['位置','内容','交互要求'],f.page_anatomy.map(r=>r.map(esc)))}<p>${esc(f.planning_handoff)}</p></details></div>`;
 if(f.definition_objects_v9){
   const plan=document.createElement('div');plan.className='bi-definition-v9';
   plan.innerHTML=`<h2>把全景需求变成可用的 BI</h2><p>${esc(f.definition)}</p><details open><summary>页面怎样分层阅读</summary>${table(['层次','呈现内容'],f.page_pattern_v9.map(r=>r.map(esc)))}</details><details><summary>六类定义对象：从业务身份到 BI 产品</summary>${table(['对象','定义','边界'],f.definition_objects_v9.map(r=>r.map(esc)))}</details><details><summary>九种呈现形态：按岗位任务选择</summary>${table(['呈现','使用者','主内容','图形','动作','页面'],f.presentation_plan_v9.map(r=>r.map(esc)))}</details><details><summary>自定义与发布：哪些可以配置</summary>${table(['配置','定义','发布边界'],f.config_contract_v9.map(r=>r.map(esc)))}</details><details><summary>先做四页：数据前提与实际价值</summary>${table(['页面','决定','内容','最少数据','目的'],f.mvp_decisions_v9.map(r=>r.map(esc)))}</details><details><summary>指标定义与专项适用性</summary>${table(['指标契约','需要明确'],f.metric_definition_v9.map(r=>r.map(esc)))}${table(['适用方向','候选范围','启用规则'],f.conditional_review_v9.map(r=>r.map(esc)))}</details><p class="bi-caption">v9保留 ${count} 项候选；本次补充建设分类与内容优先级。这些定义是设计建议，未新增正式指标计算或审批执行能力。</p>`;
   root.querySelector('.bi-overview').after(plan);
   if(f.execution_design){
     const execution=document.createElement('div');execution.className='bi-execution-design';
     plan.append(execution);renderBiExecutionDesign(execution,d,{esc,table});
   }
 }
 root.querySelectorAll('[data-playbook-select]').forEach(button=>button.addEventListener('click',()=>{
   root.querySelectorAll('[data-playbook-select]').forEach(b=>{const active=b===button;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active))});
   root.querySelectorAll('[data-playbook]').forEach(p=>p.hidden=p.dataset.playbook!==button.dataset.playbookSelect);
 }));
 if(f.presentation_choices&&!root.closest("#offline-decision-design")&&!root.closest("#one-page")){
   const review=document.createElement('div');review.className='bi-review-design';
   root.querySelector('.bi-workbench').append(review);renderBiReviewDesign(review,d,{esc,table});
 }
}

// Shared design explorer; no authentication, business writes or external requests.
export function renderBiReviewDesign(root,d,{esc,table,onOpenRequirements}){
 const f=d.framework,needs=d.domains.flatMap(dom=>dom.items.map(i=>({...i,code:dom.code,domain:dom.name})));
 const contracts=new Map(f.domain_data_contracts.map(c=>[c.code,c]));
 root.innerHTML=`<h2>BI应怎样定义，怎样呈现？</h2><p class="bi-lead">${esc(f.bi_definition_short)}</p>${table(['组成','负责的工作','交付与边界'],f.product_boundaries.map(r=>r.map(esc)))}<h3>选择一种使用方式</h3><p>这些是建议呈现方式；点击查看默认内容、阅读顺序和使用边界。</p><div class="bi-format-tabs" role="group" aria-label="选择BI呈现方式">${f.presentation_choices.map((p,i)=>`<button type="button" data-bi-format="${esc(p.id)}" aria-pressed="${!i}" class="${i?'':'active'}">${esc(p.name)}</button>`).join('')}</div><div data-bi-format-panel></div><div data-bi-definition-studio></div><h2>逐项需求评审卡</h2><p>${esc(f.review_note)}</p><div class="bi-review-controls"><label>按领域<select data-bi-review-domain aria-label="评审需求领域"><option value="">全部26个领域</option>${d.domains.map(dom=>`<option value="${esc(dom.code)}">${esc(dom.code+' · '+dom.name)}</option>`).join('')}</select></label><label>搜索业务问题<input data-bi-review-search aria-label="搜索评审需求" placeholder="例如：保证金、换件、SN、图纸"></label><label>建设阶段<select data-bi-review-phase aria-label="评审需求阶段"><option value="">所有候选阶段</option>${[...new Set(needs.map(n=>n.priority))].map(p=>`<option>${esc(p)}</option>`).join('')}</select></label><label>建议建设包<select data-bi-review-package aria-label="建议建设包"><option value="">全部建议分类</option>${(f.execution_design?.packages||[]).map(p=>`<option value="${esc(p.id)}">${esc(p.id+' '+p.name)}</option>`).join('')}</select></label></div><div class="bi-review-layout"><div><p data-bi-review-count aria-live="polite"></p><select size="9" data-bi-review-pick aria-label="选择具体需求"></select><div class="bi-review-buttons"><button type="button" data-bi-review-reset>清除条件</button><button type="button" data-bi-review-export>导出当前筛选清单 JSON</button></div><small>导出包括需求定义和所属领域的最小数据契约，可供后续评审。</small></div><article data-bi-review-card></article></div><h3>六条跨部门路径</h3>${table(['主线','覆盖领域','需要连起来的对象与证据'],f.scenario_navigation.map(r=>r.map(esc)))}<h3>适合低预算、少IT人员的建设顺序</h3>${table(['批次','范围','先做什么','进入下一批的条件'],f.delivery_waves.map(r=>r.map(esc)))}<p class="bi-caption">来源依据：用户提供的工厂现状＋本地需求目录。字段清单是建议采集合同，未验证真实U8/MES字段及接口；现有模拟覆盖状态与真实数据就绪度分别判断。</p>`;
 const el=s=>root.querySelector(s);let selected=needs[0].id,matching=needs,studio;
 function showFormat(id){
   const p=f.presentation_choices.find(x=>x.id===id);if(!p)return;
   root.querySelectorAll('[data-bi-format]').forEach(b=>{const on=b.dataset.biFormat===id;b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on))});
   el('[data-bi-format-panel]').innerHTML=`<article class="bi-format-panel" aria-label="${esc(p.name)}呈现设计"><div class="bi-playbook-heading"><div><small>${esc(p.reader)}</small><h3>${esc(p.question)}</h3></div><span class="bi-design-only">目标设计 · 非实时业务页面</span></div><p class="bi-density">${esc(p.density)}</p><div class="bi-format-wire"><div class="bi-format-scope">日期类型 / 期间 / 截止点 / 配置 / 组织 / 来源时间</div><div class="bi-format-results">${p.cards.map(c=>`<span>${esc(c)}<small>数值与证据接入后显示</small></span>`).join('')}</div><div><b>解释与定位</b><p>${esc(p.visual)}</p></div><div><b>业务对象清单</b><p>${esc(p.detail)}</p></div><div><b>处理与复查</b><p>${esc(p.action)}</p></div></div><div class="bi-rules"><p><b>使用边界：</b>${esc(p.avoid)}</p><p><b>手机呈现：</b>${esc(p.mobile)}</p></div><p class="bi-caption">关联页面蓝图：${esc(p.pages.join(' / '))}；具体功能状态需查需求目录。</p></article>`;
 }
 function reviewRows(n){
   const c=contracts.get(n.code),proposal=n.delivery_proposal;
   const planning=proposal?[['建议建设包',proposal.package_id+' '+proposal.package_name+'；'+proposal.review_state],['建议进入条件',proposal.entry_gate],['部门决策 / 节奏',proposal.decision_context+'；'+proposal.review_cadence],['建议试点范围',proposal.first_scope],['维护责任待确认',proposal.maintainer]]:[];
   const contract=n.presentation_contract;
   const presentation=contract?[['展示问题',contract.question],['可比条件',contract.compare_gate],['跨页与返回',contract.context_binding],['对象明细',contract.detail_contract],['手机任务',contract.mobile_task],['权限与原件',contract.permissions],['导出一致性',contract.export_contract],['处理边界',contract.action_boundary]]:[];
   return [...planning,['需求编号 / 领域',n.id+' / '+n.domain],['业务问题',n.need],['使用者 / 下一步',n.owner+' / '+n.action],['建议口径',n.definition],['对象粒度 / 维度',n.grain+' / '+n.dimensions],['呈现与页面',n.view+' / '+n.page_ids.join('、')],...presentation,['来源建议',n.source],['领域最小关联键',c.key],['领域最少字段',c.fields],['时间与更新',c.clock+'；'+n.frequency],['采集起步',c.approach],['适用性 / 数据前提',n.applicability+'；'+n.prerequisite],['真实数据就绪度',c.source_status],['模拟实现情况',n.implementation+'；'+n.gap],['验收样例',n.acceptance]];
 }
 function showNeed(){
   const n=matching.find(x=>x.id===selected);const target=el('[data-bi-review-card]');
   if(!n){target.innerHTML='<p class="bi-review-empty">没有符合条件的需求。清除部分筛选后再选择。</p>';return}
   target.innerHTML=`<small>${esc(n.priority)} · ${esc(n.implementation)}</small><h3>${esc(n.id+' '+n.need)}</h3><dl>${reviewRows(n).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl><details><summary>上线评审的6道检查</summary>${table(['检查','需要确认'],f.review_gates.map(r=>r.map(esc)))}</details><button type="button" data-bi-review-save>下载本项评审卡 TXT</button> <button type="button" data-bi-review-to-draft>将这项需求带入定义工作坊</button>`;
   el('[data-bi-review-to-draft]').onclick=()=>studio?.useNeed(n.id);
   el('[data-bi-review-save]').onclick=()=>download('BI需求评审_'+n.id+'.txt',reviewRows(n).map(([k,v])=>k+'\n'+v+'\n').join('\n')+'\n待确认：适用性 / 业务负责人 / 数据负责人 / 目标口径 / 更新约定 / 样例对账 / 验收结论\n\n'+f.review_note,'text/plain;charset=utf-8');
 }
 function download(name,content,type){
   const url=URL.createObjectURL(new Blob([content],{type})),a=document.createElement('a');a.href=url;a.download=name;root.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 function drawNeeds(){
   const q=el('[data-bi-review-search]').value.trim().toLowerCase(),domain=el('[data-bi-review-domain]').value,phase=el('[data-bi-review-phase]').value,packageId=el('[data-bi-review-package]').value;
   matching=needs.filter(n=>(!domain||n.code===domain)&&(!phase||n.priority===phase)&&(!packageId||n.delivery_proposal?.package_id===packageId)&&(!q||JSON.stringify(n).toLowerCase().includes(q)));
   if(!matching.some(n=>n.id===selected))selected=matching[0]?.id||'';
   el('[data-bi-review-count]').textContent=`当前匹配 ${matching.length} / ${needs.length} 项`;
   el('[data-bi-review-pick]').innerHTML=matching.map(n=>`<option value="${esc(n.id)}" ${n.id===selected?'selected':''}>${esc(n.id+' '+n.need)}</option>`).join('');
   el('[data-bi-review-pick]').disabled=!matching.length;el('[data-bi-review-export]').disabled=!matching.length;showNeed();
 }
 root.querySelectorAll('[data-bi-format]').forEach(b=>b.onclick=()=>showFormat(b.dataset.biFormat));
 el('[data-bi-review-domain]').onchange=drawNeeds;el('[data-bi-review-phase]').onchange=drawNeeds;el('[data-bi-review-package]').onchange=drawNeeds;el('[data-bi-review-search]').oninput=drawNeeds;
 el('[data-bi-review-pick]').onchange=e=>{selected=e.target.value;showNeed()};
 el('[data-bi-review-reset]').onclick=()=>{['domain','phase','package','search'].forEach(k=>el('[data-bi-review-'+k+']').value='');drawNeeds()};
 el('[data-bi-review-export]').onclick=()=>download('BI需求清单_当前筛选.json',JSON.stringify({design_version:d.version,date:d.designDate,notice:f.review_note,filters:{domain:el('[data-bi-review-domain]').value,phase:el('[data-bi-review-phase]').value,package:el('[data-bi-review-package]').value,q:el('[data-bi-review-search]').value},count:matching.length,requirements:matching.map(n=>({...n,data_contract:contracts.get(n.code)}))},null,2),'application/json;charset=utf-8');
 if(!root.closest('#offline-review-design')){
  const content=document.createElement('div');content.className='bi-content-in-review';
  el('[data-bi-definition-studio]').before(content);
  renderBiContentPlanner(content,d,{esc,table,onOpenRequirements});
 }
 studio=renderBiDefinitionStudio(el("[data-bi-definition-studio]"),d,{esc,table});
 showFormat(f.presentation_choices[0].id);drawNeeds();
}

// Presentation prototypes from the same catalog; no numbers, queries or writes.
export function renderBiContentPlanner(root,d,{esc,table,onOpenRequirements}={}){
 const f=d.framework;if(!f.presentation_states)return;
 const needs=d.domains.flatMap(dom=>dom.items.map(n=>({...n,code:dom.code,domain:dom.name})));
 const el=s=>root.querySelector(s),filters=new Map(f.filter_library.map(x=>[x.id,x]));
 let selected='H',page='P02',state='ready';
 root.innerHTML=`<section class="bi-content-planner" aria-label="BI展示内容规划"><div class="bi-content-heading"><small>内容 · 维度 · 布局 · 交互状态</small><h2>把完整需求，落实到每一页展示</h2><p>${esc(f.content_design_note)}</p></div><div class="bi-content-summary"><span><b>${needs.length}</b>项候选</span><span><b>${d.domains.length}</b>个领域</span><span><b>${d.page_blueprints.length}</b>页布局</span><span><b>${f.component_contracts.length}</b>种组件</span><span><b>${f.presentation_states.length}</b>种状态</span></div><div class="bi-page-lab"><h3>专题页面与状态演练</h3><p>选择工作页，再切换数据状态。预览只说明阅读顺序与缺口处理，无经营数值。状态区为单张结果卡的独立示例，不会统一改变各业务卡的判定。</p><div class="bi-content-controls"><label>工作页<select data-bi-content-page aria-label="展示规划工作页">${d.page_blueprints.map(p=>`<option value="${esc(p.id)}">${esc(p.id+' · '+p.name)}</option>`).join('')}</select></label><label>演练状态<select data-bi-content-state aria-label="演练数据状态">${f.presentation_states.map(s=>`<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('')}</select></label></div><article data-bi-content-prototype aria-label="专题呈现预览" aria-live="polite"></article></div><h3>所有领域的展示内容</h3><p>点击领域查看全部候选内容与建议维度；下方清单与原需求目录使用相同编号和实施状态。</p><div class="bi-domain-buttons" role="group" aria-label="展示内容领域">${d.domains.map(dom=>`<button type="button" data-bi-content-domain="${esc(dom.code)}" aria-pressed="false"><b>${esc(dom.code+' '+dom.name)}</b><small>${dom.items.length}项候选</small></button>`).join('')}</div><div class="bi-content-controls"><label>领域<select data-bi-content-domain-select aria-label="展示内容领域选择">${d.domains.map(dom=>`<option value="${esc(dom.code)}">${esc(dom.code+' · '+dom.name)}</option>`).join('')}</select></label><label>搜索本领域<input data-bi-content-search aria-label="搜索展示内容" placeholder="业务问题、维度、来源或动作"></label></div><div data-bi-content-domain-head></div><p data-bi-content-count aria-live="polite"></p><div data-bi-content-needs></div><details><summary>16种展示组件的内容与交互定义</summary>${table(['组件','回答什么','必须显示','误读防护'],f.component_contracts.map(r=>r.map(esc)))}</details><details><summary>15种数据状态，怎样区分显示？</summary>${table(['状态','显示文案','呈现规则','边界'],f.presentation_states.map(s=>[s.name,s.label,s.render,s.boundary].map(esc)))}</details><details><summary>电机制造的8组分析维度字典</summary>${table(['维度组','候选字段','使用边界'],f.factory_dimension_library.map(r=>r.map(esc)))}</details><details><summary>15类筛选控件与12条数字呈现规则</summary>${table(['候选筛选','适用条件'],f.filter_library.map(x=>[esc(x.label),esc(x.rule)]))}${table(['显示对象','规则'],f.number_display_rules.map(r=>r.map(esc)))}</details><details><summary>一张BI页面的10项定义</summary>${table(['定义项','要明确的内容'],f.page_definition_fields.map(r=>r.map(esc)))}</details></section>`;
 function openNeed(id){
  if(onOpenRequirements){onOpenRequirements({q:id,domain:id.split('-')[0],priority:'',status:''});return}
  const target=document.querySelector('#requirements'),search=document.querySelector('#search');
  if(target&&search){search.value=id;search.dispatchEvent(new Event('input'));location.hash='requirements';target.scrollIntoView();return}
  location.hash='catalog?'+new URLSearchParams({tab:'requirements',domain:id.split('-')[0],q:id}).toString();
 }
 function drawPage(){
  const p=d.page_blueprints.find(x=>x.id===page),s=f.presentation_states.find(x=>x.id===state),spec=p.display_spec;
  const metricRows=spec.metric_ids.map(id=>d.metrics.find(m=>m.id===id)).filter(Boolean);
  el('[data-bi-content-page]').value=page;el('[data-bi-content-state]').value=state;
  el('[data-bi-content-prototype]').innerHTML=`<div class="bi-prototype-head"><div><small>${esc(p.id+' · '+p.reader)}</small><h3>${esc(p.name)}</h3><p>${esc(p.question)}</p></div><span class="bi-design-only">设计预览 · 无经营数值</span></div><div class="bi-prototype-range"><b>先固定范围与时间</b><div>${spec.filters.map(id=>`<span title="${esc(filters.get(id).rule)}">${esc(filters.get(id).label)}</span>`).join('')}</div><p>${esc(spec.time_semantics)}</p><small>${esc(spec.filter_rule)}</small></div><div class="bi-prototype-state" data-state="${esc(state)}"><b>结果卡的状态示例：${esc(s.name)}</b><strong>${esc(s.label)}</strong><p>${esc(s.render)}</p><small>${esc(s.boundary)}</small></div><div class="bi-prototype-kpis">${p.cards.map(c=>`<div><small>${esc(c)}</small><strong>—</strong><span>本卡独立定义：单位 / 分母或有效样本 / 版本 / 来源</span></div>`).join('')}</div><div class="bi-prototype-explain"><b>解释差异与限制</b><p>${esc(p.visual)}</p><small>点选只在已验证的维度关系内联动；有效样本与未覆盖对象始终可查。</small></div><div class="bi-prototype-list"><b>定位到可处理对象</b><p>${esc(p.detail)}</p><div>${spec.detail_columns.map(c=>`<span>${esc(c)}</span>`).join('')}</div><small>默认顺序：${esc(spec.default_sort)}</small></div><div class="bi-prototype-action"><b>证据 → 行动 → 复查</b><p>${esc(p.drill)}</p><p>${esc(p.decision)}</p><small>${esc(spec.mobile)}</small></div><details><summary>本页定义、关联指标和数据门槛</summary><p>${esc(p.gate)}</p><p>${esc(spec.privacy)}</p><ol>${spec.interaction.map(x=>`<li>${esc(x)}</li>`).join('')}</ol>${table(['候选指标','计算 / 时间','使用边界'],metricRows.map(m=>[esc(m.id+' '+m.name),esc(m.formula)+'<br>'+esc(m.clock),esc(m.pitfalls)]))}<p>本页关联${spec.requirement_ids.length}项候选需求；一个需求可被多个页面引用，页间不能相加计数。</p><p>模拟实施情况：${esc(p.status)}</p></details>`;
 }
 function drawDomain(){
  const dom=d.domains.find(x=>x.code===selected),q=el('[data-bi-content-search]').value.trim().toLowerCase();
  const found=dom.items.filter(n=>!q||JSON.stringify(n).toLowerCase().includes(q));
  el('[data-bi-content-domain-select]').value=selected;
  root.querySelectorAll('[data-bi-content-domain]').forEach(b=>{const active=b.dataset.biContentDomain===selected;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active))});
  el('[data-bi-content-domain-head]').innerHTML=`<h3>${esc(dom.code+' · '+dom.name)}</h3><p><b>候选维度：</b>${dom.presentation_design.dimensions.map(esc).join(' · ')}</p><p><b>时间规则：</b>${esc(dom.presentation_design.clock)}</p><small>${esc(dom.presentation_design.scope_note)}</small>`;
  el('[data-bi-content-count]').textContent=`本领域匹配 ${found.length} / ${dom.items.length} 项；全目录 ${needs.length} 项。`;
  el('[data-bi-content-needs]').innerHTML=found.length?found.map(n=>`<details class="bi-content-need"><summary>${esc(n.id+' · '+n.need)}<small>${esc(n.priority+' / '+n.implementation)}</small></summary><p><b>要判断什么：</b>${esc(n.definition)}</p><p><b>呈现：</b>${esc(n.display_design.visual)}<br><b>候选维度：</b>${n.display_design.dimensions.map(esc).join(' · ')}</p><p><b>对象与动作：</b>${esc(n.display_design.object_and_evidence)}</p><p><b>责任 / 频率：</b>${esc(n.owner+' / '+n.frequency)}</p><p><b>来源 / 前提：</b>${esc(n.source+' / '+n.prerequisite)}</p><p><b>适用边界：</b>${esc(n.applicability)}</p><p><b>目前差距：</b>${esc(n.gap)}</p><p><b>验收：</b>${esc(n.acceptance)}</p><button type="button" data-bi-content-open-need="${esc(n.id)}">查看完整评审卡 ${esc(n.id)}</button></details>`).join(''):'<p class="bi-review-empty">此领域没有匹配内容，可清除搜索或切换领域。</p>';
  root.querySelectorAll('[data-bi-content-open-need]').forEach(b=>b.onclick=()=>openNeed(b.dataset.biContentOpenNeed));
 }
 el('[data-bi-content-page]').onchange=e=>{page=e.target.value;drawPage()};
 el('[data-bi-content-state]').onchange=e=>{state=e.target.value;drawPage()};
 root.querySelectorAll('[data-bi-content-domain]').forEach(b=>b.onclick=()=>{selected=b.dataset.biContentDomain;el('[data-bi-content-search]').value='';drawDomain()});
 el('[data-bi-content-domain-select]').onchange=e=>{selected=e.target.value;el('[data-bi-content-search]').value='';drawDomain()};
 el('[data-bi-content-search]').oninput=drawDomain;
 drawPage();drawDomain();
 if(f.presentation_design){
  const presentation=document.createElement('div');presentation.className='bi-presentation-extension';
  root.prepend(presentation);renderBiPresentationDesign(presentation,d,{esc,table,onOpenRequirements});
 }
}

// Reading prototypes only: no business queries, publications or approval actions.
export function renderBiPresentationDesign(root,d,{esc,table,onOpenRequirements}){
 const f=d.framework.presentation_design;if(!f)return;
 const metricNames=new Map(d.metrics.map(m=>[m.id,m.name]));
 const needNames=new Map(d.domains.flatMap(dom=>dom.items).map(n=>[n.id,n.need]));
 const el=s=>root.querySelector(s);
 const g=f.reading_guide;
 const guide=g?`<section class="bi-reading-design" aria-label="BI方案快速阅读"><small>${esc(g.revision)}</small><h2>电机工厂的BI：从业务问题到处理对象</h2><p class="bi-lead">${esc(g.definition)}</p><p>${esc(g.factory_focus)}</p><p>${esc(g.decision_chain.join(' → '))}</p><details open><summary>低预算先回答这五个问题</summary>${table(['问题与页面','首屏内容','下一步'],g.first_questions.map(x=>[esc(x.question+' · '+x.page_id),esc(x.content),esc(x.action)]))}<p>${esc(g.budget_rule)}</p></details><details><summary>首页先选两项结果、一项护栏</summary>${table(['用途','建议指标','确认口径'],g.primary_metrics.map(([label,id,note])=>[esc(label),esc(id+' '+metricNames.get(id)),esc(note)]))}</details><details><summary>完整范围：26领域382项候选需求</summary>${table(['领域','项数','示例（完整内容见需求清单）'],g.domain_index.map(x=>[esc(x.code+' '+x.name),esc(x.count),esc(x.examples)]))}</details><details><summary>定义什么、怎样呈现、预留哪些创新</summary>${table(['定义对象','要写清'],g.definition_rules.map(r=>r.map(esc)))}${table(['界面','呈现内容'],g.display_rules.map(r=>r.map(esc)))}${table(['创新方向','设计内容'],g.innovations.map(r=>r.map(esc)))}</details><p class="bi-caption">${esc(g.boundary)}</p></section>`:'';
 root.innerHTML=`${guide}<section class="bi-reading-design" aria-label="BI内容与交互完善设计"><small>${esc(f.revision)}</small><h2>先完成阅读任务，再决定怎样排页面</h2><p class="bi-lead">${esc(f.definition)}</p><p>${esc(f.factory_definition)}</p><p class="bi-caption">${esc(f.scope)}</p><details><summary>八类定义对象：需求、模型、维度、指标、专题、协同与发布</summary>${table(['对象','定义','示例编码','责任与边界'],f.definition_objects.map(x=>[x.name,x.definition,x.example_code,x.boundary].map(esc)))}</details><div class="bi-reading-controls"><label>按任务选择呈现方式<select data-bi-reading-format aria-label="选择呈现任务">${f.formats.map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('')}</select></label><label>选择页面的默认任务<select data-bi-reading-page aria-label="选择页面阅读任务">${d.page_blueprints.map(p=>`<option value="${esc(p.id)}">${esc(p.id+' '+p.name)}</option>`).join('')}</select></label></div><article data-bi-reading-format-panel></article><article data-bi-reading-page-panel aria-live="polite"></article><details><summary>12条跨部门问题路径：从问题进入对象与证据</summary><div class="bi-reading-journeys">${f.journeys.map(j=>`<article><h4>${esc(j.question)}</h4><p>${esc(j.path)}</p><small>${esc(j.boundary)}</small><p>页面蓝图：${esc(j.page_ids.join(' / '))}</p><div>${j.need_ids.map(id=>`<button type="button" data-bi-reading-need="${esc(id)}">${esc(id+' '+needNames.get(id))}</button>`).join('')}</div><small>路径为设计，实际功能状态须查看对应需求。</small></article>`).join('')}</div></details><details><summary>26领域的可比条件与手机任务</summary>${table(['领域','允许比较前须核对','手机优先完成什么'],f.domain_comparison.map(x=>[esc(x.code+' '+x.name),esc(x.rule),esc(x.mobile_task)]))}</details><details><summary>数据不足、无权限或不能比较时怎样显示</summary>${table(['状态','显示与处理规则'],f.gates.map(x=>[esc(x.name),esc(x.render)]))}</details><details><summary>从自定义需求到受控发布</summary>${table(['步骤','定义内容'],f.configuration_flow.map(r=>r.map(esc)))}${table(['来源','起步方式','核验边界'],f.collection_start.map(r=>r.map(esc)))}</details><details><summary>需求目录还要确认哪些条件业务？</summary>${table(['方向','需企业核实','涉及领域','后续'],f.conditional_questions.map(x=>[x.subject,x.question,x.domains,x.followup].map(esc)))}</details><p class="bi-caption">${esc(f.status)} 每项需求的完整展示契约可在下方逐项评审卡查看并导出；全部需求保留原编号和模拟状态。</p></section>`;
 function drawFormat(){
  const x=f.formats.find(x=>x.id===el('[data-bi-reading-format]').value);
  el('[data-bi-reading-format-panel]').innerHTML=`<div class="bi-reading-format"><h3>${esc(x.name)}</h3><p>${esc(x.reader)}</p><dl><dt>首屏内容</dt><dd>${esc(x.content)}</dd><dt>图形</dt><dd>${esc(x.visual)}</dd><dt>节奏</dt><dd>${esc(x.cadence)}</dd><dt>密度与边界</dt><dd>${esc(x.density)}</dd></dl><small>呈现任务示例；与下方页面分别选择，不表示自动生成了生产页面。</small></div>`;
 }
 function drawPage(){
  const p=d.page_blueprints.find(x=>x.id===el('[data-bi-reading-page]').value),c=p.reading_contract;
  el('[data-bi-reading-page-panel]').innerHTML=`<div class="bi-reading-page"><div class="bi-prototype-head"><div><small>${esc(p.id+' · '+p.reader)}</small><h3>${esc(c.first_task)}</h3></div><span class="bi-design-only">阅读设计 · 无经营数值</span></div><p>${esc(c.default_reading)}</p><div class="bi-reading-context">${c.visible_context.map(x=>`<span>${esc(x)}</span>`).join('')}</div><ol class="bi-reading-zones">${c.zones.map((z,i)=>`<li><b>${esc(z)}</b><p>${esc(i===0?'先固定上述范围、截止和来源条件':i===1?'主结果候选：'+c.result_metric_ids.map(id=>id+' '+metricNames.get(id)).join(' / '):i===2?p.visual:i===3?p.detail:i===4?p.drill:c.exit_decision)}</p></li>`).join('')}</ol><p><b>手机任务：</b>${esc(c.mobile_task)}</p><p><b>数据未具备：</b>${esc(c.empty_state)}</p><details><summary>查看该页原有模拟状态及进入条件</summary><p>${esc(p.status)}</p><p>${esc(p.gate)}</p></details></div>`;
 }
 el('[data-bi-reading-format]').onchange=drawFormat;
 el('[data-bi-reading-page]').onchange=drawPage;
 el('[data-bi-reading-page]').value='P02';
 root.querySelectorAll('[data-bi-reading-need]').forEach(b=>b.onclick=()=>{
  const id=b.dataset.biReadingNeed;
  if(onOpenRequirements){onOpenRequirements({q:id,domain:id.split('-')[0],priority:'',status:''});return}
  const target=document.querySelector('#requirements'),search=document.querySelector('#search');
  if(target&&search){search.value=id;search.dispatchEvent(new Event('input'));location.hash='requirements';target.scrollIntoView();return}
  location.hash='catalog?'+new URLSearchParams({tab:'requirements',domain:id.split('-')[0],q:id}).toString();
 });
 drawFormat();drawPage();
}

export function renderPlanningCatalog(root,tab,d,{esc,table,panel,params=new URLSearchParams(),onOpenRequirements}={}){
 const f=d.framework,select=s=>root.querySelector(s),selectAll=s=>[...root.querySelectorAll(s)];
 if(tab==='specification'){
  root.innerHTML=`<div class="planning-hero"><small>BI 定义设计 · 可作为每项需求的评审卡</small><h2>先定义要作出的决定，再定义页面</h2><p>${esc(f.definition)}</p><p class="panel-note">下方为建议契约与交付示例，不会创建或修改正式指标。</p></div><div class="definition-chain">${f.definition_levels.map(([name,q,output,owner],i)=>`<article><small>0${i+1}</small><h3>${esc(name)}</h3><b>${esc(q)}</b><p>${esc(output)}</p><small>${esc(owner)}</small></article>`).join('')}</div><h2>一份分析定义，写清12件事</h2><div class="contract-cards">${f.definition_contract.map(([name,fields,example,guard],i)=>`<article><div class="eyebrow">${String(i+1).padStart(2,'0')} · ${esc(name)}</div><h3>${esc(fields)}</h3><p>${esc(example)}</p><small>${esc(guard)}</small></article>`).join('')}</div>${panel('同一套定义，适配8种使用场景','岗位和决定不同，默认内容与操作密度不同',table(['呈现形态','谁在何时使用','默认呈现','交互与边界'],f.display_channels.map(r=>r.map(esc))))}${panel('数字的状态也必须定义','无数据、缺数据与无权限不能显示成同一个0',table(['状态','应怎样呈现','边界'],f.visual_states.map(r=>r.map(esc))))}${panel('低预算下如何取舍','用具体条件筛选需求，不预设未经核实的收益或工期',table(['顺序','判断问题','执行方式'],f.prioritization.map(r=>r.map(esc))))}<p class="source">${esc(f.scope_note)}</p>`;
  // The portable document already places this introduction above the catalog.
  if(!root.closest('#offline-specification')){
    const holder=document.createElement('div');holder.className='bi-decision-intro';root.prepend(holder);
    renderBiDecisionDesign(holder,d,{esc,table});
  }
  return;
 }
 const priorities=[...new Set(d.domains.flatMap(x=>x.items.map(i=>i.priority)))];
 let active=d.coverage_groups.some(g=>g.id===params.get('group'))?params.get('group'):'';
 root.innerHTML=`<div class="planning-hero"><small>需求覆盖矩阵 · 从完整候选到首期选择</small><h2>8条业务主线，${d.domains.length}个领域</h2><p>先找到业务场景，再检查指标、对象、证据与行动。需求多不意味着首期做得多。</p><div class="planning-stats" id="coverage-stats"></div></div><div class="coverage-groups"><button data-coverage-group=""><b>全部主线</b><small>查看完整范围</small></button>${d.coverage_groups.map(g=>`<button data-coverage-group="${esc(g.id)}"><b>${esc(g.name)}</b><small>${esc(g.domains.join(' · '))}</small></button>`).join('')}</div><p id="coverage-question" class="catalog-hint"></p><div class="catalog-filter coverage-filter"><input id="coverage-search" aria-label="搜索覆盖需求" placeholder="搜索问题、数据、呈现方式或行动"><select id="coverage-priority" aria-label="覆盖需求阶段"><option value="">所有候选阶段</option>${priorities.map(p=>`<option>${esc(p)}</option>`).join('')}</select><select id="coverage-status" aria-label="覆盖实施状态"><option value="">所有实施状态</option><option>模拟部分覆盖</option><option>待建设</option></select><button id="coverage-reset">清除筛选</button></div><p id="coverage-count" class="panel-note" aria-live="polite"></p><div id="coverage-table"></div><p class="source">${esc(f.scope_note)} “模拟部分覆盖”不等于完成，以下不计算完成率。各字段筛选同时影响计数与领域明细入口。</p>`;
 select('#coverage-search').value=params.get('q')||'';
 if(priorities.includes(params.get('priority')))select('#coverage-priority').value=params.get('priority');
 if(['模拟部分覆盖','待建设'].includes(params.get('status')))select('#coverage-status').value=params.get('status');
 function draw(){
  const filters={group:active,q:select('#coverage-search').value,priority:select('#coverage-priority').value,status:select('#coverage-status').value};
  const rows=coverageRows(d,filters),total=rows.reduce((s,r)=>s+r.total,0),partial=rows.reduce((s,r)=>s+r.partial,0),planned=rows.reduce((s,r)=>s+r.planned,0);
  selectAll('[data-coverage-group]').forEach(b=>{b.classList.toggle('active',b.dataset.coverageGroup===active);b.setAttribute('aria-pressed',String(b.dataset.coverageGroup===active))});
  select('#coverage-stats').innerHTML=[[total,'项匹配需求'],[rows.length,'个匹配领域'],[partial,'项模拟部分覆盖'],[planned,'项待建设']].map(([n,label])=>`<div><strong>${n}</strong><span>${label}</span></div>`).join('');
  select('#coverage-question').textContent=d.coverage_groups.find(g=>g.id===active)?.question||'覆盖经营、制造、供应、质量、资源、财务及平台。首期围绕订单交付、质量试验、对象履历、数据可信度4个工作页。';
  select('#coverage-count').textContent=`当前匹配 ${total} / ${d.planning_summary.requirements} 项需求；每个领域的计数、阶段和明细使用同一筛选范围。`;
  select('#coverage-table').innerHTML=table(['业务领域','匹配需求与候选阶段','模拟实施状态','页面蓝图','进入清单'],rows.map(r=>{
   const phases=priorities.map(p=>[p,r.items.filter(i=>i.priority===p).length]).filter(([,n])=>n).map(([p,n])=>`${esc(p)} ${n}`).join(' · ');
   const qp=new URLSearchParams({tab:'requirements',domain:r.code});['q','priority','status'].forEach(k=>{if(filters[k])qp.set(k,filters[k])});
   return [`<b>${esc(r.code+' · '+r.name)}</b><small class="coverage-preview">${esc(r.items.slice(0,2).map(i=>i.need).join(' / '))}${r.total>2?' …':''}</small>`,`<b>${r.total} 项</b><small class="coverage-preview">${phases}</small>`,`部分覆盖 ${r.partial}<br>待建设 ${r.planned}`,r.pages.map(p=>`<span class="tag gray">${esc(p)}</span>`).join(' '),`<a href="${onOpenRequirements?'#requirements':'#catalog?'+esc(qp.toString())}" data-coverage-open="${esc(r.code)}">查看这 ${r.total} 项 ↗</a>`];
  }));
  if(onOpenRequirements)selectAll('[data-coverage-open]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();onOpenRequirements({domain:a.dataset.coverageOpen,...filters})}));
 }
 selectAll('[data-coverage-group]').forEach(b=>b.addEventListener('click',()=>{active=b.dataset.coverageGroup;draw()}));
 select('#coverage-search').addEventListener('input',draw);select('#coverage-priority').addEventListener('change',draw);select('#coverage-status').addEventListener('change',draw);
 select('#coverage-reset').addEventListener('click',()=>{active='';['#coverage-search','#coverage-priority','#coverage-status'].forEach(s=>select(s).value='');draw()});draw();
}
/** A planning view: selections do not calculate, approve, save or publish. */
export function renderBiMethodWorkshop(root,d,{esc,table}){
 const f=d.framework.method_workshop;
 if(!f){root.innerHTML='<p class="empty">分析方法设计资料尚未生成。</p>';return}
 const methods=new Map(f.methods.map(m=>[m.id,m]));
 const metrics=new Map(d.metrics.map(m=>[m.id,m.name]));
 const needs=d.domains.flatMap(dom=>dom.items.map(n=>({...n,domain_code:dom.code})));
 root.innerHTML=`<div class="bi-method-workshop"><h2>从业务问题选方法，再核对能否计算</h2><p>${esc(f.definition)}</p><p class="bi-method-notice">${esc(f.scope)}</p>
 ${d.framework.spc_trial?`<div class="bi-method-notice"><b>新增受控采样候选试算</b><p>10个合成试验、730条观测：固定基线I-MR、公差/控制限分开、断点与暂停原因、逐点来源和完整CSV。真实MSA、工况与正式能力仍待审定，浏览器/手机未验收。</p><a href="#spc">打开过程稳定性试验 ↗</a></div>`:''}
 ${d.framework.msa_trial?`<div class="bi-method-notice"><b>新增测量系统交叉采样</b><p>11个合成试验、930条重复观测：声明样件和人员，核对全部交叉单元，保留交互的ANOVA及三类百分比，逐点追到Excel行。4个完整试验可试算，7个异常试验暂停；真实MSA资格及浏览器/手机交互待验收。</p><a href="#msa">打开测量系统交叉采样 ↗</a></div>`:''}
 <div class="bi-method-controls"><label>方法选型<select data-method-control="method">${f.methods.map(m=>`<option value="${esc(m.id)}" ${m.id==='DIST'?'selected':''}>${esc(m.name)}</option>`).join('')}</select></label><label>页面预演与关联需求范围<select data-method-control="page"><option value="">全部页面的候选需求</option>${d.page_blueprints.map(p=>`<option value="${esc(p.id)}" ${p.id==='P05'?'selected':''}>${esc(p.id+' '+p.name)}</option>`).join('')}</select></label><label>在当前范围查需求<input data-method-control="search" type="search" aria-label="搜索关联候选需求" placeholder="名称、编码、来源或数据前提"></label></div>
 <div data-method-part="definition"></div><div data-method-part="page"></div>
 <h3>关联候选需求 <span data-method-part="count" aria-live="polite"></span></h3><p>列表按方法、页面和搜索取交集；全部逐项内容仍在“完整需求目录”。选型依据是明确实例、题目和领域，需逐项复核。</p><div data-method-part="requirements"></div>
 <h3>每项分析先核对六种证据</h3><div class="bi-method-gates">${f.readiness.map(g=>`<article><h4>${esc(g.name)}</h4><p>${esc(g.check)}</p><small>${esc(g.stop)}</small></article>`).join('')}</div>
 <details class="bi-method-sample" open><summary>来源预演：为什么有检测数值仍需暂停控制图？</summary><div data-method-part="sample"></div></details>
 <details><summary>设计参考与边界</summary><p>以下参考支持模型、生命周期和方法定义；本厂页面与选型为设计建议。</p>${f.references.map(r=>`<p><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.title)}</a></p>`).join('')}<p>当前是定义样稿、页面阅读路径和冻结样例；不执行算法、不发布指标、不修改业务记录。浏览器与手机实际交互尚待验收。</p></details></div>`;
 const within=s=>root.querySelector(s),part=s=>within(`[data-method-part="${s}"]`);
 function draw(){
  const id=within('[data-method-control="method"]').value,pageId=within('[data-method-control="page"]').value,term=within('[data-method-control="search"]').value.trim().toLowerCase();
  const m=methods.get(id),p=d.page_blueprints.find(x=>x.id===pageId);
  part('definition').innerHTML=`<article class="bi-method-definition"><small>候选方法 · ${esc(m.id)}</small><h3>${esc(m.name)}</h3><p class="bi-method-question">${esc(m.question)}</p><dl><dt>必需字段与证据</dt><dd>${m.inputs.map(esc).join('；')}</dd><dt>定义与计算约定</dt><dd>${esc(m.algorithm)}</dd><dt>呈现方式</dt><dd>${esc(m.view)}</dd><dt>进入条件</dt><dd>${esc(m.gate)}</dd><dt>暂停与解释边界</dt><dd>${esc(m.stop)}</dd></dl></article>`;
  if(p){
   const c=p.content_focus,s=p.reading_contract;
   part('page').innerHTML=`<article class="bi-method-preview"><small>页面布局预演 · 不含虚构经营数值</small><h3>${esc(p.id+' '+p.name)}</h3><p>${esc(p.question)}</p>${!p.analysis_methods.includes(id)?'<p class="bi-method-notice">所选方法不在本页的默认推荐中，需另行评审适用性。</p>':''}<div class="bi-method-scope">${esc(f.screen.header)}</div><div class="bi-method-results">${c.result_metric_ids.map(i=>`<div><small>主结果候选 · ${esc(i)}</small><b>${esc(metrics.get(i))}</b><span>数值待接入经核对来源</span></div>`).join('')}</div><div class="bi-method-reading"><b>解释与可比性</b><p>${esc(p.visual)}</p><small>${esc(m.view)}；${esc(m.gate)}</small></div><div class="bi-method-reading"><b>对象与来源</b><p>${esc(p.detail)}</p><small>${esc(p.drill)}</small></div><div class="bi-method-reading"><b>下一步与复查</b><p>${esc(p.decision)}</p><small>手机：${esc(s.mobile_task)}</small></div><p>没有数据：${esc(s.empty_state)}</p></article>`;
  }else part('page').innerHTML='<p>当前按全部页面查看候选需求；选择一页可展开具体阅读路径。</p>';
  const selected=needs.filter(n=>n.analysis_methods.includes(id)&&(!pageId||n.page_ids.includes(pageId))&&(!term||JSON.stringify([n.id,n.need,n.source,n.prerequisite,n.domain]).toLowerCase().includes(term)));
  part('count').textContent=`${selected.length} / ${needs.length} 项`;
  part('requirements').innerHTML=table(['候选需求','来源与粒度','进入前先核实','呈现和下一步','已有状态'],selected.map(n=>[esc(n.id+' '+n.need),esc(n.source+'；'+n.grain),esc(n.prerequisite),esc(n.view+'；'+n.action),esc(n.implementation)]));
 }
 const s=f.sample;
 part('sample').innerHTML=`<p class="bi-method-notice">${esc(s.classification)}。${esc(s.note)}</p><p>${esc(s.business_cutoff)} · ${esc(s.product_id)} · ${esc(s.spec_id)} · ${esc(s.equipment_id)}</p><p>${esc(s.sample)}</p><div class="bi-method-gates"><article><h4>${esc(s.cohort_units)} 台队列</h4><p>${esc(s.observations)} 条有效观测；${esc(s.excluded_equipment)} 台因设备排除；${esc(s.excluded_no_session)} 台无所选会话。</p></article><article><h4>${esc(s.tied_observations)} 条顺序待核实</h4><p>共享 ${esc(s.tied_timestamps)} 个时间值；不能用SN或Excel行号编造相邻采样。</p></article><article><h4>描述性分布可看</h4><p>均值 ${esc(s.mean.toFixed(10))} ${esc(s.unit)}；中位数 ${esc(s.median)} ${esc(s.unit)}。</p></article><article><h4>控制图与能力暂停</h4><p>${esc(s.paused)}</p></article></div><p>模拟规范 ${esc(s.lsl)}—${esc(s.usl)} ${esc(s.unit)}；${esc(s.outside)} 条所选项目超限。${esc(s.allowed)}</p><p>证据文件：${esc(s.evidence_file)}；补采真实顺序、测量条件、基线及适用性后重新预检，保留原观测。</p>`;
 within('[data-method-control="method"]').addEventListener('change',draw);
 within('[data-method-control="page"]').addEventListener('change',draw);
 within('[data-method-control="search"]').addEventListener('input',draw);
 draw();
}
