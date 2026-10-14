// Facets are derived from labels actually assigned to papers, rather than seed vocabulary.
async function loadOntology(){
  const result=await api('/ontology');state.ontology=result.labels;
  const visible=result.labels.filter(l=>l.active&&l.paper_count>0);
  for(const dim of Object.keys(state.filters))state.filters[dim]=state.filters[dim].filter(id=>visible.some(l=>l.id===id));
  $('#filters').innerHTML=Object.entries(dims).map(([dim,name])=>{
    const entries=visible.filter(l=>l.dimension===dim);if(!entries.length)return '';
    return `<details ${dim==='topic'?'open':''}><summary>${name}</summary>${entries.map(l=>`<label class="filter-label" title="${esc(l.definition)}"><input type="checkbox" data-dim="${dim}" value="${esc(l.id)}" ${(state.filters[dim]||[]).includes(l.id)?'checked':''}>${esc(l.name)} <span class="muted">${l.paper_count}</span></label>`).join('')}</details>`;
  }).join('')||'<p class="muted">尚无已使用标签。分析导入或人工标记后，筛选项会自动出现。</p>';
  $('#filters').querySelectorAll('input').forEach(el=>el.onchange=action(async()=>{state.filters[el.dataset.dim]=[...$('#filters').querySelectorAll(`input[data-dim="${el.dataset.dim}"]:checked`)].map(x=>x.value);await loadPapers();$('.paper-column').scrollTop=0;}));
  $('#ontologyList').innerHTML=`<p class="muted">${visible.length} 个已使用标签 · ${result.labels.filter(l=>!l.active).length} 个已删除标签（可恢复）</p>`+Object.entries(dims).map(([dim,name])=>`<div class="panel"><h2>${name}</h2>${result.labels.filter(l=>l.dimension===dim).map(l=>`<div class="ontology-row" data-label-name="${esc(l.name.toLowerCase())}" data-label-active="${l.active?'1':'0'}"><strong>${esc(l.name)}<small class="muted" style="display:block">${l.active?l.paper_count+' 篇文献':'已删除'}</small></strong><span>${esc(l.definition)}</span><div class="row"><button data-tag="${esc(l.id)}" data-op="rename">重命名</button><button data-tag="${esc(l.id)}" data-op="${l.active?'delete':'restore'}">${l.active?'删除':'恢复'}</button></div></div>`).join('')}</div>`).join('');
  const tools=document.createElement('div');tools.className='label-manager-tools row';tools.innerHTML='<input id="labelManagerSearch" placeholder="搜索标签名称…"><select id="labelManagerView"><option value="all">全部标签</option><option value="active">未删除标签</option><option value="deleted">已删除（可恢复）</option></select><small class="muted">删除标签不会删除论文</small>';$('#ontologyList').prepend(tools);$('#labelManagerSearch').value=state.labelManagerSearch||'';$('#labelManagerView').value=state.labelManagerView||'all';const applyLabelSearch=()=>{state.labelManagerSearch=$('#labelManagerSearch').value;state.labelManagerView=$('#labelManagerView').value;$('#ontologyList').querySelectorAll('.ontology-row').forEach(row=>row.classList.toggle('hidden',!row.dataset.labelName.includes(state.labelManagerSearch.toLowerCase())||(state.labelManagerView==='active'&&row.dataset.labelActive!=='1')||(state.labelManagerView==='deleted'&&row.dataset.labelActive!=='0')));$('#ontologyList').querySelectorAll('.panel').forEach(panel=>panel.classList.toggle('hidden',!panel.querySelector('.ontology-row:not(.hidden)')));};$('#labelManagerSearch').oninput=applyLabelSearch;$('#labelManagerView').onchange=applyLabelSearch;applyLabelSearch();
  $('#ontologyList').querySelectorAll('[data-op]').forEach(el=>el.onclick=action(async()=>{
    const label=state.ontology.find(l=>l.id===el.dataset.tag);const op=el.dataset.op;
    let body={},method='PATCH';
    if(op==='rename'){state.editingLabel=label.id;$('#renameLabelName').value=label.name;$('#renameLabelError').textContent='';$('#renameLabelDialog').showModal();$('#renameLabelName').focus();return;}
    if(op==='delete'){method='DELETE';body=null;}
    if(op==='restore')body={active:true};
    const res=await fetch('/api/ontology/'+encodeURIComponent(label.id),{method,headers:{'Content-Type':'application/json'},body:body===null?undefined:JSON.stringify(body)});
    if(!res.ok)throw Error((await res.json()).detail);
    await refreshLabels();notify(op==='delete'?'已删除标签；论文及其他标签保留，可随时恢复':'标签已更新');
  }));
  $('#labelDimension').innerHTML=Object.entries(dims).map(([id,name])=>`<option value="${id}">${name}</option>`).join('');
  let suggestions=$('#labelSuggestions');if(!suggestions){suggestions=document.createElement('div');suggestions.id='labelSuggestions';}$('#ontologyList').after(suggestions);
  suggestions.innerHTML=result.suggestions.length?`<div class="panel"><h2>文献提出的新标签 / 阅读建议</h2><p class="muted">建议可能包含解析问题，并非都适合作为标签。选择需要的建议，确认定义后加入。</p>${result.suggestions.map((s,i)=>`<div class="tag-review"><p>${esc(s.text)}</p><small class="muted">${esc(s.title)}</small><button data-suggestion="${i}">据此添加标签</button></div>`).join('')}</div>`:'';
  suggestions.querySelectorAll('[data-suggestion]').forEach(el=>el.onclick=()=>{const s=result.suggestions[Number(el.dataset.suggestion)];const form=$('#labelForm');form.closest('details').open=true;form.elements.name.value=s.text.slice(0,150);form.elements.definition.value=s.text;form.elements.id.value='';form.scrollIntoView({behavior:'smooth',block:'start'});});
}
async function refreshLabels(){await loadOntology();await loadPapers();if(state.selected)await loadDetail(state.selected);}
$('#labelForm').onsubmit=action(async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));data.id=data.id.trim()||'tag_'+crypto.randomUUID().replaceAll('-','');data.name=data.name.trim();data.parent_id=data.parent_id||null;data.synonyms=[];await api('/ontology',data);e.target.reset();await refreshLabels();notify('已加入标签库。给文献赋予此标签后，它会自动出现在左侧筛选。');});
$('#labelForm').elements.id.required=false;
$('#labelForm').elements.id.placeholder='留空自动生成';
const detailWithStaticTags=loadDetail;
loadDetail=async function(id){await loadOntology();await detailWithStaticTags(id);};
action(async()=>{await loadOntology();await loadPapers()})();

const renameDialog=document.createElement('dialog');renameDialog.id='renameLabelDialog';renameDialog.innerHTML='<form id="renameLabelForm"><div class="dialog-heading"><h2>重命名标签</h2><button type="button" id="closeRenameLabel">关闭</button></div><p class="muted">只修改显示名称，已有论文归属和分析记录保留。</p><label>标签名称<input id="renameLabelName" required maxlength="150"></label><p id="renameLabelError" role="alert"></p><button class="primary" type="submit">保存名称</button></form>';document.body.append(renameDialog);$('#closeRenameLabel').onclick=()=>renameDialog.close();$('#renameLabelForm').onsubmit=async event=>{event.preventDefault();try{const response=await fetch('/api/ontology/'+encodeURIComponent(state.editingLabel),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('#renameLabelName').value.trim()})});if(!response.ok)throw Error((await response.json()).detail);renameDialog.close();await refreshLabels();notify('标签名称已更新，文献及原有归属保留')}catch(error){$('#renameLabelError').textContent=error.message}};
