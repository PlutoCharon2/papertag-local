// Directory refresh runs on the backend, including while the window is in the tray.
const refreshPanel=document.createElement('div');
refreshPanel.className='panel';
refreshPanel.innerHTML='<h2>文献库刷新</h2><form id="refreshSettingsForm"><label class="toggle"><input type="checkbox" id="refreshEnabled">定时检查已导入目录中的新论文</label><label>自动刷新间隔（分钟）<input id="refreshMinutes" type="number" min="1" max="1440" value="20" required></label><button class="primary">保存刷新设置</button><span id="refreshSettingsStatus" class="muted" role="status"></span></form><p class="muted">默认每20分钟检查一次；软件运行或隐藏到托盘时生效，退出后停止。手动点击“检查新增”立即检查。只读取已导入目录和文件，更新软件内部索引，不重命名、移动、删除或改写原始PDF。点击“检查新增”会扫描目录、移除本地已删除的条目，并将新增及库内从未分析的文献加入队列；失败、暂停或中断任务不重复提交，相同内容复用已有分析。全部暂停时只排队，点击“继续分析”后执行。定时检查是否自动分析仍由自动分析设置控制。</p>';
$('#settings').prepend(refreshPanel);
action(async()=>{const config=await api('/refresh/settings');$('#refreshEnabled').checked=config.enabled;$('#refreshMinutes').value=config.interval_minutes;})();
$('#refreshSettingsForm').onsubmit=action(async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{const config=await api('/refresh/settings',{enabled:$('#refreshEnabled').checked,interval_minutes:Number($('#refreshMinutes').value)});$('#refreshSettingsStatus').textContent=config.enabled?`已保存，每${config.interval_minutes}分钟检查一次`:'已关闭自动刷新，仍可手动刷新';notify('刷新设置已保存');}finally{button.disabled=false;}});

let scanRequestPending=false;
updateLibrary=async function(){
if(scanRequestPending)return;
scanRequestPending=true;
const buttons=[$('#updateLibrary'),$('#updateFromImport'),$('#checkNewAI')];
buttons.forEach(b=>b.disabled=true);
$('#libraryRefreshStatus').textContent='正在提交目录检查…';
try{const result=await api('/check-new',{});state.libraryScanJob=result.job_id;$('#libraryRefreshStatus').textContent='正在检查新论文…';notify(result.analysis_enabled?'已开始检查；新增及从未分析的文献将加入分析队列，旧失败任务不会重试。':'已开始检查；新增论文将排队。当前已暂停，点击“继续分析”后执行。');await loadJobs();}
catch(e){$('#libraryRefreshStatus').textContent='未启动检查：'+e.message;throw e;}
finally{scanRequestPending=false;buttons.forEach(b=>b.disabled=false);}
};
$('#updateLibrary').onclick=action(updateLibrary);
$('#updateFromImport').onclick=action(updateLibrary);
let scanSignature=null,scanPollBusy=false;
async function refreshLibraryView(){
await loadOntology();await loadPapers();
if(state.selected&&!state.papers.some(p=>p.id===state.selected)){
const selected=state.selected;const p=await api('/papers/'+selected);
if(state.selected===selected&&p.status==='source_missing'){state.selected=null;state.detail=null;$('#detail').innerHTML='<div class="empty">本地文献已删除，已从列表移除。</div>';}
}
}
async function pollLibraryRefresh(){
if(scanPollBusy)return;
scanPollBusy=true;
try{
const jobs=await api('/jobs');
const active=jobs.find(j=>['waiting','running'].includes(j.status));
const latest=jobs[0];
if(active){$('#libraryRefreshStatus').textContent=`正在检查 ${active.done}/${active.total||'…'} · 新增 ${active.added}`;}
else if(latest){$('#libraryRefreshStatus').textContent=latest.status==='completed'?`上次检查：新增 ${latest.added} · 内容变化 ${latest.modified} · 已移除 ${latest.removed||0} · 未变化 ${latest.duplicates} · 失败 ${latest.failed}`:`上次检查：${statusNames[latest.status]||latest.status}`;}
const signature=jobs.map(j=>`${j.id}:${j.status}:${j.done}`).join('|');
if(signature!==scanSignature){
const changed=scanSignature!==null;scanSignature=signature;
if(changed)await refreshLibraryView();
}
const manual=jobs.find(j=>j.id===state.libraryScanJob);
if(manual&&!['waiting','running'].includes(manual.status)){
state.libraryScanJob=null;
await refreshLibraryView();
notify(manual.status==='completed'?`检查完成：新增 ${manual.added} 篇 · 内容变化 ${manual.modified} 篇 · 已移除 ${manual.removed||0} 篇 · 失败 ${manual.failed} 篇。新增及从未分析的文献已加入队列（暂停时等待继续），旧失败任务未重试。`:`检查${statusNames[manual.status]||manual.status}，请在导入与导出查看记录。`);
}
}finally{scanPollBusy=false;}
}
action(pollLibraryRefresh)();
setInterval(()=>action(pollLibraryRefresh)(),5000);
