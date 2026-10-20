// Keys are fetched only when the user opens API configuration, never in status APIs.
const originalKeyLabel=$('#apiSecret').closest('label');const keyLabel=document.createElement('div');originalKeyLabel.replaceWith(keyLabel);
keyLabel.innerHTML='<span class="row" style="justify-content:space-between">API 密钥<button id="addAPIKey" type="button">新增</button></span><div id="apiKeyRows"></div>';
let keyLoadGeneration=0;
let keysLoadFailed=false;
function addKeyRow(key={}){
const row=document.createElement('div');row.className='row api-key-row';row.style.marginTop='8px';row.dataset.keyId=key.id||'';
const input=document.createElement('input');input.className='api-key-input';input.type='password';input.autocomplete='off';input.spellcheck=false;input.placeholder='填写API密钥';input.style.flex='1';input.value=key.value||'';
const enabled=document.createElement('input');enabled.type='checkbox';enabled.className='api-key-enabled';enabled.checked=key.enabled!==false;enabled.title='启用此密钥参与并行处理';enabled.style.width='auto';
const eye=document.createElement('button');eye.type='button';eye.textContent='查看';eye.onclick=()=>{input.type=input.type==='password'?'text':'password';eye.textContent=input.type==='password'?'查看':'隐藏';};
const remove=document.createElement('button');remove.type='button';remove.textContent='移除';remove.onclick=()=>{input.value='';row.remove();if(!$('#apiKeyRows').children.length)addKeyRow();renumberKeys();};
row.append(enabled,input,eye,remove);$('#apiKeyRows').append(row);renumberKeys();
}
function renumberKeys(){document.querySelectorAll('.api-key-input').forEach((el,index)=>{el.id=index===0?'apiSecret':`apiSecret${index+1}`;el.setAttribute('aria-label',`API密钥 ${index+1}`);});}
addKeyRow();
$('#addAPIKey').onclick=()=>addKeyRow();
const saveAPIButton=$('#apiProfileForm button[type="submit"]');
fillAPIProfile=async function(){
const generation=++keyLoadGeneration,provider=$('#apiProvider').value,p=apiProfiles[provider];
document.querySelectorAll('.api-key-input').forEach(input=>input.value='');$('#apiKeyRows').replaceChildren();addKeyRow();
$('#apiProfileModel').value=p.model;$('#apiBaseURL').value=p.url;$('#apiClearKey').checked=false;$('#apiProviderHelp').textContent=p.help;
$('#apiModelOptions').innerHTML=p.models.map(m=>`<option value="${esc(m)}"></option>`).join('');$('#apiTestResult').textContent='';
$('#apiKeyState').textContent='正在读取本机加密密钥…';saveAPIButton.disabled=true;$('#addAPIKey').disabled=true;keysLoadFailed=false;
try{
const response=await fetch('/api/ai/provider/keys',{method:'POST',headers:{'Content-Type':'application/json','X-PaperTag-Key-View':'1'},body:JSON.stringify({provider})});
if(!response.ok)throw Error('读取已保存密钥失败，请检查本机Windows用户或重新填写');
const data=await response.json();if(generation!==keyLoadGeneration||!apiDialog.open)return;
$('#apiKeyRows').replaceChildren();data.keys.length?data.keys.forEach(addKeyRow):addKeyRow();
$('#apiKeyState').textContent=data.keys.length?`已保存 ${data.keys.length} 把密钥；圆点中已有真实密钥，点击“查看”可显示。同一模型动态分配空闲可用密钥：每把同时处理一篇，哪把先空闲就接下一篇；全部占用时排队。`:'尚未保存密钥；点击“新增”可增加密钥行。';
}catch(e){if(generation===keyLoadGeneration){keysLoadFailed=true;$('#apiKeyState').textContent=e.message;}}
finally{if(generation===keyLoadGeneration){saveAPIButton.disabled=false;$('#addAPIKey').disabled=false;}}
};
$('#apiProvider').onchange=action(fillAPIProfile);
$('#apiProfileForm').onsubmit=action(async event=>{
event.preventDefault();saveAPIButton.disabled=true;
try{
const keys=[...document.querySelectorAll('.api-key-row')].map(row=>({id:row.dataset.keyId,value:row.querySelector('.api-key-input').value.trim(),enabled:row.querySelector('.api-key-enabled').checked})).filter(k=>k.value||k.id);
if(keysLoadFailed&&!keys.some(k=>k.value)&&!$('#apiClearKey').checked)throw Error('读取原有密钥失败，请重新填写密钥后保存');
await api('/ai/provider',{provider:$('#apiProvider').value,url:$('#apiBaseURL').value.trim(),model:$('#apiProfileModel').value.trim(),keys,clear_key:$('#apiClearKey').checked});
const data=await api('/ai/providers');apiProfiles=data.profiles;await fillAPIProfile();$('#apiTestResult').textContent='已保存。同一模型按空闲可用密钥动态分配任务；当前任务全部暂停时不会自动继续。';await updateAuth();
}finally{saveAPIButton.disabled=false;}
});
apiDialog.addEventListener('close',()=>{++keyLoadGeneration;document.querySelectorAll('.api-key-input').forEach(input=>{input.value='';input.type='password';});$('#apiKeyRows').replaceChildren();addKeyRow();});
$('#testAPI').textContent='测试首把启用密钥';
