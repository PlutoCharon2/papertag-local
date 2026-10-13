// Facets are derived from labels actually assigned to papers, rather than seed vocabulary.
async function loadOntology(){
  const result=await api('/ontology');state.ontology=result.labels;
  const visible=result.labels.filter(l=>l.active&&l.paper_count>0);
  for(const dim of Object.keys(state.filters))state.filters[dim]=state.filters[dim].filter(id=>visible.some(l=>l.id===id));
  $('#filters').innerHTML=Object.entries(dims).map(([dim,name])=>{
    const entries=visible.filter(l=>l.dimension===dim);if(!entries.length)return '';
    return `<details ${dim==='topic'?'open':''}><summary>${name}</summary>${entries.map(l=>`<label class="filter-label" title="${esc(l.definition)}"><input type="checkbox" data-dim="${dim}" value="${esc(l.id)}" ${(state.filters[dim]||[]).includes(l.id)?'checked':''}>${esc(l.name)} <span class="muted">${l.paper_count}</span></label>`).join('')}</details>`;
  }).join('')||'<p class="muted">尚无已使用标签。分析导入或人工标记后，筛选项会自动出现。</p>';
  $('#filters').querySelectorAll('input').forEach(el=>el.onchange=action(async()=>{state.filters[el.dataset.dim]=[...$('#filters').querySelectorAll(`input[data-dim="${el.dataset.dim}"]:checked`)].map(x=>x.value);await loadPapers()}));
  $('#ontologyList').innerHTML=`<p class="muted">${visible.length} 个已使用标签 · ${result.labels.filter(l=>!l.active).length} 个已删除标签（可恢复）</p>`+Object.entries(dims).map(([dim,name])=>`<div class="panel"><h2>${name}</h2>${result.labels.filter(l=>l.dimension===dim).map(l=>`<div class="ontology-row"><strong>${esc(l.name)}<small class="muted" style="display:block">${l.active?l.paper_count+' 篇文献':'已删除'}</small></strong><span>${esc(l.definition)}</span><div class="row"><button data-tag="${esc(l.id)}" data-op="rename">重命名</button><button data-tag="${esc(l.id)}" data-op="${l.active?'delete':'restore'}">${l.active?'删除':'恢复'}</button></div></div>`).join('')}</div>`).join('');
  $('#ontologyList').querySelectorAll('[data-op]').forEach(el=>el.onclick=action(async()=>{
    const label=state.ontology.find(l=>l.id===el.dataset.tag);const op=el.dataset.op;
    let body={},method='PATCH';
    if(op==='rename'){const name=prompt('新的标签名称',label.name);if(name===null)return;body={name};}
    if(op==='delete'){method='DELETE';body=null;}
    if(op==='restore')body={active:true};
    const res=await fetch('/api/ontology/'+encodeURIComponent(label.id),{method,headers:{'Content-Type':'application/json'},body:body===null?undefined:JSON.stringify(body)});
    if(!res.ok)throw Error((await res.json()).detail);
    await refreshLabels();notify(op==='delete'?'已删除当前标签，历史数据保留，可随时恢复':'标签已更新');
  }));
  $('#labelDimension').innerHTML=Object.entries(dims).map(([id,name])=>`<option value="${id}">${name}</option>`).join('');
  let suggestions=$('#labelSuggestions');if(!suggestions){suggestions=document.createElement('div');suggestions.id='labelSuggestions';$('#ontologyList').before(suggestions);}
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
