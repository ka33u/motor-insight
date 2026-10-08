export const targetKinds={module:'系统页面',model:'分析模型',topic:'分析专题',view:'个人视角',page:'个人专题页面',card:'个人口径卡',coding:'编码规则',trial:'试排与基线方案'};
export function targetFromRoute(hash){
 const [route,q='']=hash.replace(/^#/,'').split('?'),p=new URLSearchParams(q),positive=v=>/^[1-9][0-9]{0,14}$/.test(v||''),uuid=v=>/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(v||'');
 if(['finite-schedule','crew-schedule','joint-schedule','order-baselines'].includes(route)&&p.has('study')){
  if([...p.keys()].some(k=>!['study','policy','view','receipt'].includes(k)||p.getAll(k).length!==1))return null;
  const study=p.get('study'),policy=p.get('policy')||'due',view=p.get('view')||'';
  if(!study||study.length>150||/[\x00-\x1f\x7f]/.test(study)||!['due','priority'].includes(policy)||!(view===''||route==='joint-schedule'&&view==='compare'||route==='order-baselines'&&view==='trial'))return null;
  return {kind:'trial',lookup:{route,study,policy,view}};
 }
 if(route==='analysis'&&p.has('model'))return positive(p.get('model'))?{kind:'model',target:p.get('model')}:null;
 if(route==='topics'&&p.has('page'))return uuid(p.get('page'))?{kind:'page',target:p.get('page')}:null;
 if(route==='topics'&&p.has('view'))return positive(p.get('view'))?{kind:'view',target:p.get('view')}:null;
 if(route==='topics'&&p.has('id'))return positive(p.get('id'))?{kind:'topic',target:p.get('id')}:null;
 if(route==='topic-pages'&&p.has('id'))return uuid(p.get('id'))?{kind:'page',target:p.get('id')}:null;
 if(route==='model-cards'&&p.has('id'))return uuid(p.get('id'))?{kind:'card',target:p.get('id')}:null;
 if(route==='coding'&&p.has('id'))return positive(p.get('id'))?{kind:'coding',target:p.get('id')}:null;
 return /^[a-z][a-z-]*$/.test(route)?{kind:'module',target:route}:null;
}
export function groupedEntries(rows){const groups=new Map();for(const row of rows){const section=row.section||'未分组';if(!groups.has(section))groups.set(section,[]);groups.get(section).push(row)}return [...groups].map(([name,rows])=>({name,rows}))}
export function reorderEntries(rows,id,delta){
 const groups=groupedEntries(rows),g=groups.find(g=>g.rows.some(r=>r.id===id));if(!g)throw Error('收藏已变化');const pos=g.rows.findIndex(r=>r.id===id),next=pos+delta;
 if(next<0||next>=g.rows.length)return groups.flatMap(g=>g.rows.map(r=>r.id));[g.rows[pos],g.rows[next]]=[g.rows[next],g.rows[pos]];return groups.flatMap(g=>g.rows.map(r=>r.id));
}
export function workbenchMarkup(d,esc){
 if(!d.rows.length)return '<div class="desk-empty"><strong>把每天的工作放在这里</strong><p>添加常用专题、保存过的视角或模型，按“早会核查”“车间跟进”等工作步骤分组。</p><p>也可在任一已保存页面点击顶部“收藏当前入口”。</p></div>';
 return groupedEntries(d.rows).map((g,groupIndex,groups)=>`<section class="desk-section"><div class="desk-section-head"><h2>${esc(g.name)} <small>${g.rows.length}项</small></h2><div><button data-desk-group="${groupIndex}" data-delta="-1" ${groupIndex===0?'disabled':''} aria-label="上移${esc(g.name)}分组">↑ 分组</button><button data-desk-group="${groupIndex}" data-delta="1" ${groupIndex===groups.length-1?'disabled':''} aria-label="下移${esc(g.name)}分组">↓ 分组</button></div></div><div class="desk-grid">${g.rows.map((r,i)=>`<article class="desk-card desk-${r.state}"><div class="desk-eyebrow"><span>${esc(targetKinds[r.kind])}</span>${r.is_home?'<b>登录入口</b>':''}</div><h3>${esc(r.alias||r.label)}</h3>${r.alias&&r.alias!==r.label?`<p class="desk-original">${esc(r.label)}</p>`:''}<p class="desk-status">${esc(r.note)}${r.version!=null?' · v'+esc(r.version):''}</p><div class="desk-card-actions"><button class="primary" data-desk-open="${esc(r.id)}" ${r.state==='unavailable'?'disabled':''}>${r.state==='review'?'打开核对':'打开'} ↗</button><button data-desk-edit="${esc(r.id)}">整理</button><button data-desk-move="${esc(r.id)}" data-delta="-1" ${i===0?'disabled':''} aria-label="上移${esc(r.alias||r.label)}">↑</button><button data-desk-move="${esc(r.id)}" data-delta="1" ${i===g.rows.length-1?'disabled':''} aria-label="下移${esc(r.alias||r.label)}">↓</button></div></article>`).join('')}</div></section>`).join('');
}
export function createWorkbench(h){
 const {api,esc,header,modal,toast,go,$,$$,on,isCurrent,getModalRevision,refreshModels,applyModels}=h;let serial=0,quickSerial=0;
 const post=(path,body)=>api('workbench'+path,{method:'POST',body});
 const attempt=fn=>async(...args)=>{try{await fn(...args)}catch(e){toast(e.message)}};
 function editDialog(d,row,done,validParent){
  modal('整理收藏',`<form id="desk-edit" class="editor"><p>${esc(row.label)} · ${esc(targetKinds[row.kind])}</p><label>本人别名（可留空）<input name="alias" maxlength="80" value="${esc(row.alias)}"></label><label>工作分组（可留空）<input name="section" maxlength="40" value="${esc(row.section)}"></label><button class="primary">保存整理</button><button id="desk-home" type="button" ${row.state!=='ready'?'disabled':''}>${row.is_home?'取消登录入口':'设为登录入口'}</button><button id="desk-remove" type="button">移除收藏</button><p class="panel-note">移除只改变本人工作台。原模型、专题、视角及业务资料仍由原页面管理。</p></form>`);
  const rev=getModalRevision(),valid=()=>validParent()&&getModalRevision()===rev&&$('#detail').open;let busy=false;
  const save=async data=>{if(busy||!valid())return;busy=true;try{const n=await post('',{revision:d.revision,...data});if(valid()){$('#detail').close();await done(n)}}finally{busy=false}};
  on('#desk-edit','submit',e=>{e.preventDefault();return save({action:'edit',id:row.id,...Object.fromEntries(new FormData(e.currentTarget))})});
  on('#desk-home','click',()=>save({action:'home',id:row.is_home?null:row.id}));on('#desk-remove','click',()=>save({action:'remove',id:row.id}));
 }
 async function addDialog(d,done,validParent,initial=null){
  modal('添加常用入口',`<form id="desk-picker" class="desk-picker"><label>类型<select name="kind" id="desk-kind">${Object.entries(targetKinds).map(([k,label])=>`<option value="${k}" ${k===initial?.kind?'selected':''}>${esc(label)}</option>`).join('')}</select></label><label>名称或编号<input name="q" maxlength="120" id="desk-query"></label><button>查找</button></form><p class="panel-note">${esc(d.notice)}</p><div id="desk-pick-list"></div><div class="toolbar"><button id="desk-pick-prev">上一页</button><span id="desk-pick-page"></span><button id="desk-pick-next">下一页</button></div><form id="desk-add" class="editor"><p id="desk-choice">先选择一个当前可访问的目标</p><label>本人别名（可留空）<input name="alias" maxlength="80"></label><label>工作分组（可留空）<input name="section" maxlength="40" placeholder="如：早会核查、车间跟进"></label><button id="desk-add-save" class="primary" disabled>收藏到我的工作台</button></form>`);
  const rev=getModalRevision(),valid=()=>validParent()&&getModalRevision()===rev&&$('#detail').open;let selected=null,sequence=0,page=1,total=0,busy=false,applied={kind:initial?.kind||'module',q:''};
  const choose=r=>{selected=r;$('#desk-choice').textContent=r.label+' · '+targetKinds[r.kind]+' · '+r.note;$('#desk-add-save').disabled=false};
  async function search(nextPage=1,next=applied){if(busy||!valid())return;const id=++sequence;selected=null;$('#desk-add-save').disabled=true;$('#desk-choice').textContent='正在查找，请稍候';$('#desk-pick-list').innerHTML='';$('#desk-pick-prev').disabled=true;$('#desk-pick-next').disabled=true;const result=await post('/catalog',{...next,page:nextPage});if(!valid()||sequence!==id)return;applied={...next};page=result.page;total=result.total;$('#desk-choice').textContent='请选择一个目标';$('#desk-pick-list').innerHTML=result.rows.map(r=>`<button class="desk-pick" data-desk-pick="${esc(r.target)}"><b>${esc(r.label)}</b><small>${esc(r.target)} · ${esc(r.note)}</small></button>`).join('')||'<p class="empty">没有当前可访问的匹配目标。</p>';$('#desk-pick-page').textContent=`${page} / ${Math.max(1,Math.ceil(total/25))}页 · ${total}项`;$('#desk-pick-prev').disabled=page===1;$('#desk-pick-next').disabled=page*25>=total;
   $$('[data-desk-pick]').forEach(b=>b.addEventListener('click',()=>{if(valid()&&sequence===id&&!busy)choose(result.rows.find(r=>r.target===b.dataset.deskPick))}));
   if(initial){const found=result.rows.find(r=>r.kind===initial.kind&&r.target===initial.target);if(found)choose(found);initial=null}
  }
  on('#desk-picker','submit',e=>{e.preventDefault();return search(1,{kind:$('#desk-kind').value,q:$('#desk-query').value})});on('#desk-kind','change',()=>search(1,{kind:$('#desk-kind').value,q:$('#desk-query').value}));
  on('#desk-pick-prev','click',()=>search(page-1));on('#desk-pick-next','click',()=>search(page+1));
  on('#desk-add','submit',async e=>{e.preventDefault();if(busy||!selected||!valid())return;busy=true;const target={kind:selected.kind,target:selected.target},fields=Object.fromEntries(new FormData(e.currentTarget));$('#desk-add-save').disabled=true;try{const n=await post('',{action:'add',revision:d.revision,...target,...fields});if(valid()){$('#detail').close();await done(n)}}finally{busy=false;if(valid())$('#desk-add-save').disabled=!selected}});
  await search(1,{kind:initial?.kind||'module',q:initial?.target||''});
 }
 async function render(params,token){
  const id=++serial,valid=()=>isCurrent(token)&&id===serial;let d=await api('workbench');if(!valid())return;let busy=false,openSerial=0;
  async function draw(n=d){if(!valid()||n.revision<d.revision)return;d=n;$('#main').innerHTML=header('我的工作台','把常用分析和日常核查按工作步骤排在一起。每个账号独立保存。',`<button id="desk-add-open" class="primary">＋ 添加入口</button><button id="desk-refresh">刷新状态</button><button id="desk-start">登录进入工作台</button><button id="desk-reset-start">恢复总览入口</button>`)+`<div class="desk-intro"><div><b>从这里开始今天的工作</b><p>分组、排序和登录入口由你决定。打开后继续使用原页面的筛选、计算和来源。</p></div><div><span>${d.rows.length} / ${d.limit} 项收藏</span><small>${d.home_mode==='workbench'?'登录时进入我的工作台':d.home_entry?'已设置收藏为登录入口':'登录时默认进入经营总览'}</small></div></div><div id="desk-groups">${workbenchMarkup(d,esc)}</div><p class="panel-note">${esc(d.notice)} 同一目标只收藏一次；需要不同筛选时，可分别保存个人视角再收藏。</p>`;
   on('#desk-add-open','click',()=>addDialog(d,n=>draw(n),valid));on('#desk-refresh','click',async()=>{const n=await api('workbench');if(valid())await draw(n)});
   const mutate=async fields=>{if(busy||!valid())return;busy=true;try{const n=await post('',{revision:d.revision,...fields});if(valid())await draw(n)}finally{busy=false}};
   on('#desk-start','click',()=>mutate({action:'home',id:'workbench'}));on('#desk-reset-start','click',()=>mutate({action:'home',id:null}));
   $$('[data-desk-open]').forEach(b=>b.addEventListener('click',attempt(async()=>{if(!valid())return;const opening=++openSerial,r=await post('/open',{id:b.dataset.deskOpen,revision:d.revision});if(!valid()||opening!==openSerial)return;if(r.kind==='model'){const models=await refreshModels();if(!valid()||opening!==openSerial)return;applyModels(models)}if(valid()&&opening===openSerial)go(r.route,r.params)})));
   $$('[data-desk-edit]').forEach(b=>b.addEventListener('click',()=>editDialog(d,d.rows.find(r=>r.id===b.dataset.deskEdit),n=>draw(n),valid)));
   $$('[data-desk-move]').forEach(b=>b.addEventListener('click',attempt(()=>mutate({action:'order',ids:reorderEntries(d.rows,b.dataset.deskMove,Number(b.dataset.delta))}))));
   $$('[data-desk-group]').forEach(b=>b.addEventListener('click',attempt(()=>{const groups=groupedEntries(d.rows),i=Number(b.dataset.deskGroup),j=i+Number(b.dataset.delta);if(!groups[j])return;[groups[i],groups[j]]=[groups[j],groups[i]];return mutate({action:'order',ids:groups.flatMap(g=>g.rows.map(r=>r.id))})})));
  }
  await draw();
 }
 async function quickAdd(hash,token){let target=targetFromRoute(hash);if(!target)throw Error('当前地址不是可收藏的固定入口，请保存模型或视角后再收藏');const id=++quickSerial,rev=getModalRevision(),d=await api('workbench'),valid=()=>isCurrent(token)&&id===quickSerial;if(!valid()||rev!==getModalRevision())return;if(target.lookup){target=await post('/trial-target',target.lookup);if(!valid()||rev!==getModalRevision())return;}const existing=d.rows.find(r=>r.kind===target.kind&&r.target===target.target);if(existing){editDialog(d,existing,()=>toast('本人工作台已更新'),valid);return}await addDialog(d,()=>toast('已收藏到我的工作台'),valid,target)}
 return {render,quickAdd};
}
