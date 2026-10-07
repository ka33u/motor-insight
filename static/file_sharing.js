export function createFileSharing({api,esc,num,header,panel,table,on,$,$$,go,toast,localTime,isCurrent}){
 const labels={active:'当前可读',revoked:'已撤销',expired:'已到期',account_changed:'账号或岗位已变化，需重新授权'};
 const deadline=s=>s?localTime(s):'未设固定到期';
 return async function render(params,token){
  const manage=params.get('manage'),id=params.get('id');let serial=0,pending=null;
  const valid=n=>isCurrent(token)&&n===serial;
  if(manage){
   const d=await api(`file-sharing/${encodeURIComponent(manage)}`);if(!isCurrent(token))return;
   const users=new Map(d.recipients.map(r=>[r.id,r]));for(const g of d.grants)if(!users.has(g.payload.recipient_id))users.set(g.payload.recipient_id,{...g.payload.recipient,historical:true});
   $('#main').innerHTML=header('原件只读授权 · '+d.file.filename,'按文件指定接收账号，先核对原件、账号和操作，再确认。',`<a href="#device-files?id=${encodeURIComponent(manage)}">返回归档原件</a><a href="#shared-originals">我获授权的原件</a>`)+`<p class="source">${esc(d.notice)}</p><p class="source device-hash">文件标识：${esc(d.file.id)}<br>归档摘要：${esc(d.file.file_hash)}</p>`+
    (d.original_valid?'':'<div class="notice warn">原件缺失或摘要异常，新增授权暂停；仍可撤销已有授权。</div>')+
    panel('当前授权清单','每个接收账号采用最新授权或撤销；文件关联操作仍归归档人。',table(['接收账号 / 授权时岗位','当前状态','截止时间（上海）','版本 / 操作'],d.grants.map(g=>[`${esc(g.payload.recipient.display_name||g.payload.recipient.username)}<small class="block">${esc(g.payload.recipient.username)} · ${esc(g.payload.recipient.role_label)}</small>`,esc(labels[g.state]),esc(deadline(g.payload.expires_at)),`v${g.version}${g.action==='grant'?` <button data-share-revoke="${g.payload.recipient_id}">准备撤销</button>`:''}`])))+
    panel('准备授权或撤销','授权允许下载整份原件，包含文件内全部字段；平台业务和字段权限保持独立。',`<form id="share-form" class="editor"><div class="form-grid"><label>接收账号<select name="recipient_id" required><option value="">选择指定账号</option>${[...users.values()].map(u=>`<option value="${u.id}">${esc((u.display_name||u.username)+' · '+u.username+' · '+u.role_label+(u.historical?'（历史接收人）':''))}</option>`).join('')}</select></label><label>操作<select name="action"><option value="grant">授予 / 更新只读权限</option><option value="revoke">撤销该账号只读权限</option></select></label><label>可选截止时间（当前设备本地时间）<input type="datetime-local" name="expires_at" step="1"></label><label>授权或撤销依据<textarea name="reason" required minlength="5" maxlength="1000" placeholder="说明协作事项、原件用途和接收岗位。"></textarea></label></div><p class="panel-note">截止时间将转换为UTC保存，展示统一采用上海时间；到期当刻停止读取。接收账号岗位配置变化后需要重新授权。</p><button class="primary">核对原件与账号</button><div id="share-error" class="inline-error" role="alert"></div></form><div id="share-preview"></div>`)+
    panel('不可覆盖的授权沿革','完整保存指定账号、原件摘要、依据、期限和前序版本；不代表质量批准。',d.history.map(e=>`<details><summary>v${e.version} · ${e.action==='grant'?'只读授权':'撤销'} · ${esc(e.payload.recipient.username)} · ${esc(localTime(e.created_at))}</summary><p>${esc(e.payload.reason)}<br>截至：${esc(deadline(e.payload.expires_at))}<br>记录人：${esc(e.payload.actor.username)}</p><p class="device-hash">记录摘要：${esc(e.payload_hash)}</p></details>`).join('')||'<p class="empty">尚无授权记录；原件保持私有。</p>');
   const form=$('#share-form');
   function reset(){serial++;pending=null;$('#share-preview').innerHTML='';$('#share-error').textContent='';const revoke=form.elements.action.value==='revoke';form.elements.expires_at.disabled=revoke;if(revoke)form.elements.expires_at.value='';}
   form.addEventListener('input',reset);form.addEventListener('change',reset);
   $$('[data-share-revoke]').forEach(b=>b.addEventListener('click',()=>{form.elements.recipient_id.value=b.dataset.shareRevoke;form.elements.action.value='revoke';reset();form.scrollIntoView({block:'start'});}));
   on('#share-form','submit',async e=>{
    e.preventDefault();const n=++serial;pending=null;const data=new FormData(form),input=data.get('expires_at');
    const change={recipient_id:Number(data.get('recipient_id')),action:data.get('action'),reason:data.get('reason'),expires_at:input?new Date(input).toISOString().replace(/\.\d{3}Z$/,'Z'):''};
    const b=$('button.primary',form);b.disabled=true;$('#share-error').textContent='';$('#share-preview').innerHTML='';
    try{const p=await api(`file-sharing/${encodeURIComponent(manage)}/preview`,{method:'POST',body:change});if(!valid(n))return;
     pending={...p.change,token:p.token,request_id:crypto.randomUUID()};
     $('#share-preview').innerHTML=panel('确认本次操作',p.change.action==='grant'?'只读授权不会授予关联、转授权或质量批准权限。':'撤销将停止该账号后续读取。',`<p><b>${esc(p.file.filename)}</b> → ${esc(p.recipient.display_name||p.recipient.username)}（${esc(p.recipient.username)} / ${esc(p.recipient.role_label)}）</p><p>操作：${p.change.action==='grant'?'只读授权':'撤销'} · 截止：${esc(deadline(p.change.expires_at))}<br>依据：${esc(p.change.reason)}</p><p class="device-hash">归档摘要：${esc(p.file.file_hash)}</p><button id="share-confirm" class="primary">确认${p.change.action==='grant'?'只读授权':'撤销'}</button><div id="share-commit-error" class="inline-error" role="alert"></div>`);
     on('#share-confirm','click',async()=>{if(!pending||!valid(n))return;const payload=pending,button=$('#share-confirm');button.disabled=true;$$('input,select,textarea,button',form).forEach(x=>x.disabled=true);
      try{await api(`file-sharing/${encodeURIComponent(manage)}/commit`,{method:'POST',body:payload});if(!valid(n))return;toast('授权记录已保存，当前权限以最新记录为准');await render(params,token);}
      catch(err){if(!valid(n))return;$('#share-commit-error').textContent=err.message;if(err.status===400||err.status===409){pending=null;$('#share-commit-error').insertAdjacentHTML('beforeend','<p>请修改条件或重新核对后再确认。</p>');}else{button.disabled=false;button.textContent='重试同一申请';}if(form.isConnected)$$('input,select,textarea,button',form).forEach(x=>x.disabled=false);}
     });
    }catch(err){if(valid(n))$('#share-error').textContent=err.message;}finally{if(b.isConnected)b.disabled=false;}
   });return;
  }
  if(id){
   const d=await api(`shared-originals/${encodeURIComponent(id)}`);if(!isCurrent(token))return;
   $('#main').innerHTML=header(d.file.filename,'按当前账号和当前授权核查存档原件。',`<a href="#shared-originals">返回获授权原件</a>`)+`<p class="source">${esc(d.notice)}</p>`+
    panel('原件与读取依据','打开时已核验归档元数据、文件大小和摘要；下载时再次检查权限与字节。',`<p>${esc(d.file.kind.toUpperCase())} · ${num(d.file.size/1024,2)} KB<br>归档人：${esc(d.owner.display_name||d.owner.username)} · ${esc(localTime(d.file.created_at))}<br>来源用途：${esc(d.file.note)}</p><p class="device-hash">文件标识：${esc(d.file.id)}<br>SHA-256：${esc(d.file.file_hash)}</p>${d.grant?`<p>授权 v${d.grant.version} · 截止：${esc(deadline(d.grant.payload.expires_at))}<br>依据：${esc(d.grant.payload.reason)}</p>`:'<p>当前账号为归档人。</p>'}<a href="/api/shared-originals/${encodeURIComponent(id)}/original" download>下载有权读取的存档原件 ↓</a>${d.owner_access?` <a href="#shared-originals?manage=${encodeURIComponent(id)}">管理只读授权</a>`:''}`);return;
  }
  const d=await api('shared-originals');if(!isCurrent(token))return;
  $('#main').innerHTML=header('我获授权的原件','只列当前有效、未到期且账号岗位仍匹配的逐文件授权。')+`<p class="source">${esc(d.notice)}</p>`+
   panel('当前可读原件','此处不推断检测或材料证明已经批准；源业务页面按自身权限访问。',table(['文件 / 归档人','文件类型 / 大小','授权 / 截止（上海）','打开'],d.rows.map(r=>[`${esc(r.file.filename)}<small class="block">${esc(r.owner.display_name||r.owner.username)}</small>`,`${esc(r.file.kind.toUpperCase())} · ${num(r.file.size/1024,2)} KB`,`${esc(localTime(r.granted_at))}<small class="block">${esc(deadline(r.expires_at))}</small>`,`<a href="#shared-originals?id=${encodeURIComponent(r.file.id)}">核查原件与读取依据 ↗</a>`])))+
   '<p class="panel-note">列表核验授权和元数据；打开或下载时检查原件字节。空列表表示当前无有效授权，不表示工厂没有原件。</p>';
 };
}
