// Receipts remain in this tab's session storage; URLs contain only random local handles.
const PREFIX='motor-topic-journey:';
const HANDLE=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export function sameConfig(a,b){
 const stable=v=>Array.isArray(v)?v.map(stable):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,stable(v[k])])):v;
 return JSON.stringify(stable(a))===JSON.stringify(stable(b));
}
export function journeyRoute(params){
 const has=params.has('journey')||params.has('journey_back');if(!has)return null;
 if([...params.keys()].some(k=>!['id','journey','journey_back'].includes(k))||[...params.keys()].some(k=>params.getAll(k).length!==1)||params.has('journey')&&params.has('journey_back'))throw Error('探索路径不能同时指定个人视角、工作页、快照或其他条件，请从专题重新进入');
 const direction=params.has('journey_back')?'return':'forward',handle=params.get(direction==='return'?'journey_back':'journey');
 if(!HANDLE.test(handle||'')||!/^\d+$/.test(params.get('id')||''))throw Error('探索路径无效，请从专题重新进入');
 return {direction,handle};
}
function prefix(username){return PREFIX+encodeURIComponent(username)+':'}
export function saveJourney(storage,username,handle,prepared,now=Date.now()){
 if(!HANDLE.test(handle)||typeof prepared.receipt!=='string'||prepared.receipt.length>12000||!Number.isFinite(prepared.expires_seconds)||prepared.expires_seconds<=0||prepared.expires_seconds>7200)throw Error('探索凭据无效');
 const p=prefix(username),entries=[];
 for(let i=0;i<storage.length;i++){const key=storage.key(i);if(key?.startsWith(p))entries.push(key)}
 const valid=[];for(const key of entries){let value;try{value=JSON.parse(storage.getItem(key))}catch{}if(!value||value.expires<=now)storage.removeItem(key);else valid.push({key,created:value.created})}
 valid.sort((a,b)=>a.created-b.created);while(valid.length>=20)storage.removeItem(valid.shift().key);
 storage.setItem(p+handle,JSON.stringify({receipt:prepared.receipt,created:now,expires:now+prepared.expires_seconds*1000}));
 return handle;
}
export function loadJourney(storage,username,handle,now=Date.now()){
 if(!HANDLE.test(handle))throw Error('探索路径无效');
 let value;try{value=JSON.parse(storage.getItem(prefix(username)+handle))}catch{}
 if(!value||typeof value.receipt!=='string'||value.receipt.length>12000||!Number.isFinite(value.expires)||value.expires<=now){storage.removeItem(prefix(username)+handle);throw Error('本次临时探索已过期或不在当前浏览器标签页，请从专题重新预览')}
 return value.receipt;
}
export function configMarkup(config,esc){
 const kinds={configuration:'配置编码',work_order:'生产工单',unit:'电机SN',equipment:'设备编码',supplier:'供应商编码',material:'物料编码',workshop:'车间'};
 const scope=s=>Object.entries(s||{}).map(([key,value])=>`${{family:'产品族',customer_id:'客户',from:'开始日期',to:'结束日期'}[key]||key}：${value}`).join(' · ')||'不限范围';
 return `<p><b>${esc(config.primary_label)}</b>：${esc(scope(config.scope))}<br><b>${esc(config.reference_label)}</b>：${config.reference_scope===null?'未启用':esc(scope(config.reference_scope))}${config.links?'<br>两侧身份条件：'+esc(config.links.selections.map(s=>`${kinds[s.kind]||s.kind} = ${s.value}`).join(' · ')):''}</p>`;
}
export function previewMarkup(data,esc,table){
 return `<p>${esc(data.source.name)} → <b>${esc(data.target.name)}</b></p><p class="source">来源日期：${esc(data.source_date_roles.join(' / ')||'无可用日期')}；目标日期：${esc(data.target_date_roles.join(' / ')||'无可用日期')}。${esc(data.notice)}</p>${data.options.map(o=>`<section class="panel"><h3>${esc(o.label)}</h3>${configMarkup(o.config,esc)}${o.removed.length?'<p class="source">明确清除：'+esc(o.removed.join('、'))+'</p>':''}${o.reasons.length?'<p class="inline-error">'+esc(o.reasons.join('；'))+'</p>':''}${table(['目标分析卡','日期角色','条件适用性'],o.cards.map(c=>[esc(`${c.slot+1}. ${c.name}`),esc(c.date_label),c.ready?'可以应用；结果进入后计算':esc(c.reasons.join('；'))]))}${o.mode==='new'?'<p class="source">开始新范围只清除外部条件，不修复不可用模型；暂停的卡片仍会标明原因。</p>':''}<button data-journey-mode="${esc(o.mode)}" ${o.allowed?'':'disabled'}>选择此方式并进入</button></section>`).join('')}<p class="source">${esc(data.return_notice)} 临时路径仅当前标签页有效，最多保留20条、每条2小时；不会保存经营数值。</p>`;
}
export function bindJourney({api,esc,table,modal,toast,go,$,on,getModalRevision,isCurrent,token,topic,topics,ctx,getApplied,username}){
 on('#topic-journey-open','click',()=>{
  let config;try{config=getApplied()}catch(e){toast(e.message);return}
  const candidates=topics.filter(t=>t.id!==topic.id);
  modal('跨专题探索',`<label>目标专题<select id="journey-target"><option value="">选择另一个专题</option>${candidates.map(t=>`<option value="${t.id}">${esc(t.name)}</option>`).join('')}</select></label><p class="source">按已应用范围预览每张目标卡，不修改原模型。${candidates.length?'':'当前没有其他可访问专题。'}</p><div id="journey-preview" aria-live="polite"></div>`);
  const revision=getModalRevision(),node=$('#journey-preview');let serial=0;
  const current=n=>isCurrent(token)&&getModalRevision()===revision&&$('#detail')?.open&&node===$('#journey-preview')&&n===serial;
  const unchanged=()=>{try{return sameConfig(config,getApplied())}catch{return false}};
  on('#journey-target','change',async e=>{
   const n=++serial,target=Number(e.target.value);node.innerHTML='';if(!target)return;
   const body={target_id:target,context_token:ctx.context_token,config};node.textContent='正在核对目标卡片与日期口径…';
   try{
    const data=await api(`topics/${topic.id}/journey/preview`,{method:'POST',body});if(!current(n))return;
    if(!unchanged())throw Error('来源范围已变化，请关闭窗口并重新预览');node.innerHTML=previewMarkup(data,esc,table);
    node.querySelectorAll('[data-journey-mode]').forEach(button=>button.addEventListener('click',async()=>{
     if(!current(n))return;const buttons=[...node.querySelectorAll('[data-journey-mode]')];buttons.forEach(b=>b.disabled=true);
     try{
      if(!unchanged())throw Error('来源范围已变化，请重新预览');
      const prepared=await api(`topics/${topic.id}/journey/open`,{method:'POST',body:{...body,mode:button.dataset.journeyMode,receipt:data.receipt}});
      if(!current(n))return;if(!unchanged())throw Error('来源范围已变化，请重新预览');
      const handle=saveJourney(sessionStorage,username,crypto.randomUUID(),prepared);$('#detail').close();go('topics',{id:prepared.topic_id,journey:handle});
     }catch(error){if(current(n)){toast(error.message);buttons.forEach(b=>b.disabled=!data.options.find(o=>o.mode===b.dataset.journeyMode)?.allowed)}}
    }));
   }catch(error){if(current(n))node.textContent=error.message}
  });
 });
}
