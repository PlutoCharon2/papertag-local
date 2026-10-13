statusNames.awaiting_chat='待 GPT 聊天分析（需上传）';statusNames.superseded='历史版本 · 已保留';
statusNames.needs_ocr='无可用文本 · 请让 GPT 读取原始 PDF';
const baseSearchBody=searchBody;
searchBody=function(){const q=baseSearchBody();q.show_versions=$('#showVersions').checked;return q};
$('#showVersions').onchange=action(loadPapers);
$('#clearFilters').addEventListener('click',()=>{$('#showVersions').checked=false});
function evidenceHTML(items,paper){return items.map(e=>{const b=paper.blocks.find(b=>b.id===e.block_id);const page=b?.page||e.page||1;const exact=!!b&&(e.verification!=='page_only');return `<div class="evidence"><a target="_blank" rel="noopener" href="/api/papers/${paper.id}/pdf#page=${page}">PDF 第 ${page} 页 ↗</a> · ${exact?'原文引用可定位':'仅页码依据 · 引用未核验'}<blockquote>${esc(e.quote)}</blockquote>${b?`<details><summary>查看来源文本块</summary><div class="body-text">${esc(b.text)}</div></details>`:'<p class="muted">此依据来自 GPT 阅读原始 PDF。软件仅检查页码范围，必须打开 PDF 人工核对。</p>'}</div>`}).join('')}
const detailBeforePreservation=loadDetail;
loadDetail=async function(id){await detailBeforePreservation(id);const p=state.detail;const heading=document.createElement('div');heading.className='panel';heading.innerHTML=`<strong>${p.archived?'PDF 版本副本已保存在本地':'旧版导入记录尚无 PDF 副本，请更新保存可用文件'}</strong><p class="muted">标签和分析保留在本地；新增或修改内容才需要 GPT 分析。历史版本不会被新版分析覆盖。</p><a href="/api/papers/${id}/bundle">下载原始 PDF + GPT 分析要求（ZIP）</a>${p.supersedes_id?` <button id="previousPDFVersion">查看修改前的版本</button>`:''}`;$('#detail').prepend(heading);if($('#previousPDFVersion'))$('#previousPDFVersion').onclick=action(()=>loadDetail(p.supersedes_id));};
