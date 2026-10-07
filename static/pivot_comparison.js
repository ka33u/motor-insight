// A comparison uses complete server aggregates; the browser only pages them.
export function mountPivotComparison({root,comparison:c,esc,num,primaryLabel='当前值',referenceLabel='对照值',onSelect}){
 if(c.blocked||!c.matrix){root.innerHTML=`<p class="notice warn">${esc(c.note)}</p>`;return}
 const p=c.matrix,lookup=new Map(p.cells.map(x=>[x.row+':'+x.column,x]));
 let key=c.display_metric,rowPage=0,colPage=0,display='delta';
 const fmt=v=>typeof v==='number'?num(v,4):esc(v??'—');
 const signed=v=>v==null?'—':(v>0?'+':'')+fmt(v);
 function draw(){
  const rr=p.rows.slice(rowPage*15,(rowPage+1)*15),cc=p.columns.slice(colPage*4,(colPage+1)*4),shown=[];
  const cell=(x,total=false)=>{const i=shown.push(x)-1,v=x.values.find(v=>v.key===key),value=v[display],unit=display==='relative_pct'?'%':v.delta_unit;
   return `<td class="${total?'pivot-total':''}"><div class="pivot-compare-cell"><b class="${value==null?'compare-unknown':value>0?'compare-increase':value<0?'compare-decrease':''}">${signed(value)}${value!=null?' <small>'+esc(unit)+'</small>':''}</b><small>${esc(primaryLabel)}：${fmt(v.primary)} ${v.primary!=null?esc(v.primary_unit):''} · n=${x.primary_rows??'—'}</small><small>${esc(referenceLabel)}：${fmt(v.reference)} ${v.reference!=null?esc(v.reference_unit):''} · n=${x.reference_rows??'—'}</small>${v.reason?`<small class="compare-reason">${esc(v.reason)}</small>`:''}${onSelect?`<div class="compare-evidence"><button data-compare-cell="${i}" data-side="primary" ${!x.primary_rows?'disabled':''} aria-label="查看${esc(primaryLabel)}来源">当前侧来源</button><button data-compare-cell="${i}" data-side="reference" ${!x.reference_rows?'disabled':''} aria-label="查看${esc(referenceLabel)}来源">对照侧来源</button></div>`:''}</div></td>`};
  root.innerHTML=`<div class="toolbar"><label>对照度量<select class="compare-measure" aria-label="对照度量">${c.measures.map(m=>`<option value="${m.key}" ${key===m.key?'selected':''}>${esc(m.label)}</option>`).join('')}</select></label><label>突出显示<select class="compare-display" aria-label="突出显示"><option value="delta" ${display==='delta'?'selected':''}>差值 · 当前减对照</option><option value="relative_pct" ${display==='relative_pct'?'selected':''}>相对变化 · %</option></select></label></div><p class="source">${esc(primaryLabel)} − ${esc(referenceLabel)} · ${esc(c.dimension_label)} × ${esc(c.column_label)} · 合并后 ${p.rows.length} 行 / ${p.columns.length} 列。蓝色表示增加，橙色表示减少，不评价好坏。</p><div class="pivot-scroll" tabindex="0" aria-label="透视对照矩阵，可横向滚动"><table class="pivot-table pivot-compare-table"><thead><tr><th scope="col">${esc(c.dimension_label)} / ${esc(c.column_label)}</th>${cc.map(a=>`<th scope="col">${esc(a.label)}</th>`).join('')}<th scope="col">行合计 · 全部列</th></tr></thead><tbody>${rr.map(a=>`<tr><th scope="row">${esc(a.label)}</th>${cc.map(b=>cell(lookup.get(a.key+':'+b.key))).join('')}${cell(p.row_totals.find(x=>x.row===a.key),true)}</tr>`).join('')}<tr><th scope="row">列合计 · 全部行</th>${cc.map(b=>cell(p.column_totals.find(x=>x.column===b.key),true)).join('')}${cell(p.grand_total,true)}</tr></tbody></table></div><div class="pagination pivot-pagination"><span>行 ${p.rows.length?rowPage*15+1:0}–${Math.min((rowPage+1)*15,p.rows.length)} / ${p.rows.length} · 列 ${p.columns.length?colPage*4+1:0}–${Math.min((colPage+1)*4,p.columns.length)} / ${p.columns.length}</span><div><button data-compare-page="row-prev" ${rowPage===0?'disabled':''}>上一页行</button><button data-compare-page="row-next" ${(rowPage+1)*15>=p.rows.length?'disabled':''}>下一页行</button><button data-compare-page="col-prev" ${colPage===0?'disabled':''}>上一页列</button><button data-compare-page="col-next" ${(colPage+1)*4>=p.columns.length?'disabled':''}>下一页列</button></div></div><p class="panel-note">${esc(c.note)} 屏幕分页不改变合计；规则 ${esc(c.rule_version)}。</p>`;
  root.querySelector('.compare-measure').onchange=e=>{key=e.target.value;draw()};
  root.querySelector('.compare-display').onchange=e=>{display=e.target.value;draw()};
  root.querySelectorAll('[data-compare-cell]').forEach(b=>b.onclick=()=>onSelect(b.dataset.side,shown[+b.dataset.compareCell]));
  root.querySelectorAll('[data-compare-page]').forEach(b=>b.onclick=()=>{const [axis,direction]=b.dataset.comparePage.split('-');if(axis==='row')rowPage+=direction==='next'?1:-1;else colPage+=direction==='next'?1:-1;draw()});
 }
 draw();
}

export function pivotCell(result,selection){
 const p=result.pivot;
 return [...p.cells,...p.row_totals,...p.column_totals,p.grand_total].find(x=>x.row===selection.row&&x.column===selection.column);
}
