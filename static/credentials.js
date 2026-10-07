export function createCredentialWorkspace({api,esc,modal,toast,$,$$,on,getContext,isCurrent,getModalRevision,onSignedOut}){
 let serial=0;
 const valid=(n,rev,c)=>n===serial&&isCurrent(c)&&$('#detail').open&&getModalRevision()===rev;
 const inputs=`<label>新口令<input name="password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label><label>再次输入新口令<input name="confirmation" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label>`;
 const clear=form=>$$('input[type=password]',form).forEach(el=>el.value='');
 $('#detail').addEventListener('close',()=>$$('.credential-form').forEach(clear));
 async function openSelf(){
  const c=getContext(),n=++serial;modal('修改本人登录口令','<p class="empty">正在核对当前账号…</p>');const rev=getModalRevision();
  try{const d=await api('credentials');if(valid(n,rev,c))selfForm(d,c)}catch(err){if(valid(n,rev,c))$('#dialog-content').innerHTML=`<p class="inline-error" role="alert">${esc(err.message)}</p>`}
 }
 function selfForm(d,c){
  modal('修改口令 · '+d.username,`<form id="credential-self-form" class="editor credential-form"><p class="source">${esc(d.notice)}</p><p>${esc(d.rules)}</p><label>当前口令<input name="current_password" type="password" autocomplete="current-password" maxlength="128" required></label>${inputs}<p id="credential-error" class="inline-error" role="alert"></p><button class="primary">保存并重新登录</button><p class="panel-note">核对凭据10分钟有效。忘记当前口令时，请由管理员从账号详情重设。</p></form>`);
  on('#credential-self-form','submit',async e=>{
   e.preventDefault();const form=e.target,b=$('button.primary',form),n=++serial,rev=getModalRevision();b.disabled=true;
   let body={context_token:d.context_token,current_password:$('[name=current_password]',form).value,password:$('[name=password]',form).value,confirmation:$('[name=confirmation]',form).value};
   if(body.password!==body.confirmation){$('#credential-error').textContent='两次输入的新口令不一致';clear(form);b.disabled=false;return}
   try{const out=await api('credentials/change',{method:'POST',body});if(isCurrent(c)){onSignedOut(d.username);toast(out.notice)}}
   catch(err){if(valid(n,rev,c)){showError(err,form,()=>openSelf());b.disabled=err.status===409}}
   finally{clear(form);body=null}
  });
 }
 async function openReset(d,afterSaved){
  const c=getContext(),n=++serial;modal('核对口令重设 · '+d.user.username,'<p class="empty">正在核对当前账号版本…</p>');const rev=getModalRevision();
  try{const p=await api(`accounts/${d.user.id}/password/preview`,{method:'POST',body:{receipt:d.receipt}});if(valid(n,rev,c))resetForm(p,c,afterSaved)}
  catch(err){if(valid(n,rev,c))$('#dialog-content').innerHTML=`<p class="inline-error" role="alert">${esc(err.message)}</p><p>关闭弹窗，重新读取账号详情后再核对。</p>`}
 }
 function resetForm(p,c,afterSaved){
  const u=p.target;modal('重设口令 · '+u.username,`<form id="credential-reset-form" class="editor credential-form"><dl class="definition-grid"><dt>账号</dt><dd>${esc(u.username)} · ${esc(u.display_name)}</dd><dt>当前岗位与状态</dt><dd>${esc(u.role_label)} · ${u.is_active?'启用':'停用；重设后仍停用'}</dd><dt>权限配置修订 / 登录版本</dt><dd>${u.revision} / ${u.session_epoch}；保存只推进登录版本</dd><dt>原有内容</dt><dd>${p.owned_models} 个模型、${p.owned_topics} 个专题；保持原归属</dd></dl><p class="source">${esc(p.notice)}</p><p>${esc(p.rules)}</p>${inputs}<label>重设依据<textarea name="reason" minlength="5" maxlength="1000" required placeholder="说明已核对的账号身份及口令恢复原因，不填写口令"></textarea></label><p id="credential-error" class="inline-error" role="alert"></p><button class="primary">确认重设口令</button><p class="panel-note">新口令不会在结果或审计中显示；由管理员按现有交接方式告知账号使用人。没有自动通知或发送口令。</p></form>`);
  on('#credential-reset-form','submit',async e=>{
   e.preventDefault();const form=e.target,b=$('button.primary',form),n=++serial,rev=getModalRevision();b.disabled=true;
   let body={preview_token:p.preview_token,password:$('[name=password]',form).value,confirmation:$('[name=confirmation]',form).value,reason:$('[name=reason]',form).value};
   if(body.password!==body.confirmation){$('#credential-error').textContent='两次输入的新口令不一致';clear(form);b.disabled=false;return}
   try{const out=await api(`accounts/${u.id}/password/reset`,{method:'POST',body});if(isCurrent(c)){toast('已重设 '+out.username+' 的口令；岗位和状态保持不变');if(valid(n,rev,c)){clear(form);await afterSaved()}}}
   catch(err){if(valid(n,rev,c)){showError(err,form,()=>afterSaved());b.disabled=err.status===409}}
   finally{clear(form);body=null}
  });
 }
 function showError(err,form,reload){
  $('#credential-error',form).textContent=err.message;
  if(err.status===409){const button=document.createElement('button');button.type='button';button.textContent='重新读取账号并核对';button.addEventListener('click',reload);$('#credential-error',form).append(document.createElement('br'),button)}
 }
 return {openSelf,openReset};
}
