"""Domestic vision APIs. Keys are encrypted with Windows user-bound DPAPI."""
import base64
import ctypes
import json
import os
import queue
import re
import threading
import time
import uuid
import secrets
from urllib.parse import urlsplit
import httpx
from .database import connect

_key_lock = threading.Lock()
_key_active = {}
_key_failures = {}
_key_cooldowns = {}
_key_cursor = {}
_bound = threading.local()


class NoKeyAvailable(ValueError):
    pass


class ProviderRejected(ValueError):
    def __init__(self,status_code,message,retry_after=60):
        super().__init__(message)
        self.status_code=status_code
        self.retry_after=retry_after


def choose_idle_key(entries):
    return secrets.choice(entries)


def key_entries(item):
    if 'keys' in item:
        return item['keys']
    return [{'id': 'legacy', 'value': item['key'], 'enabled': True}] if item.get('key') else []


def usable_keys(provider, item):
    with _key_lock:
        return [k for k in key_entries(item) if k.get('enabled', True) and (provider,k['id']) not in _key_failures
                and _key_cooldowns.get((provider,k['id']),0)<=time.monotonic()]


def pool_status(c):
    provider=selected(c)
    if provider=='codex': return {'enabled':1,'usable':1,'free':1,'busy':0,'cooling':0,'invalid':0}
    entries=[k for k in key_entries(profile(c,provider)) if k.get('enabled',True)]
    with _key_lock:
        now=time.monotonic();cooling=invalid=busy=free=0
        for key in entries:
            identity=(provider,key['id'])
            if identity in _key_failures: invalid+=1
            elif _key_cooldowns.get(identity,0)>now: cooling+=1
            elif _key_active.get(identity,0): busy+=1
            else: free+=1
    return {'enabled':len(entries),'usable':busy+free,'free':free,'busy':busy,'cooling':cooling,'invalid':invalid}


def parallelism(c):
    provider = selected(c)
    return 1 if provider == 'codex' else len(usable_keys(provider,profile(c,provider)))


def reveal_keys(provider):
    with connect() as c:
        item = profile(c, provider)
    return [{'id': k['id'], 'value': crypt(base64.b64decode(k['value']), decrypt=True).decode(),
             'enabled': k.get('enabled', True)} for k in key_entries(item)]

PROVIDERS = {
    'qwen': {'name': '千问 · 阿里云百炼', 'url': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'model': 'qwen3.7-flash', 'models': ['qwen3.7-flash', 'qwen3.7-plus'], 'help': '北京地域密钥；可填写业务空间专属 Base URL。'},
    'doubao': {'name': '豆包 · 火山方舟', 'url': 'https://ark.cn-beijing.volces.com/api/v3', 'model': '', 'models': [], 'help': '填写控制台中已开通的视觉模型 ID 或 ep- 接入点 ID。'},
    'deepseek': {'name': 'DeepSeek · 官方 API', 'url': 'https://api.deepseek.com', 'model': 'deepseek-flash', 'models': ['deepseek-flash'], 'help': '请选择支持图片输入的 Flash 模型。'},
    'zhipu': {'name': '智谱 · BigModel', 'url': 'https://open.bigmodel.cn/api/paas/v4', 'model': 'glm-4.6v-flash', 'models': ['glm-4.6v-flash', 'glm-4.6v'], 'help': '使用带 V 的视觉模型；GLM-4.7-Flash 文本模型不适用于页面图片。'},
}


def crypt(value, decrypt=False):
    if os.name != 'nt':
        raise ValueError('密钥安全保存需要 Windows DPAPI')
    class Blob(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buf = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    call = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not call(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('无法解密此 Windows 用户保存的密钥，请重新填写' if decrypt else 'Windows 密钥加密失败')
    try:
        return ctypes.string_at(target.data, target.length)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


def selected(c):
    row = c.execute("SELECT value FROM settings WHERE key='ai_provider'").fetchone()
    return row[0] if row else 'qwen'


def profile(c, provider):
    if provider not in PROVIDERS:
        raise ValueError('请选择支持的 API 服务商')
    row = c.execute('SELECT value FROM settings WHERE key=?', ('api_profile_' + provider,)).fetchone()
    return json.loads(row[0]) if row else {'url': PROVIDERS[provider]['url'], 'model': PROVIDERS[provider]['model'], 'key': ''}


def validate(provider, url, model):
    if provider not in PROVIDERS:
        raise ValueError('不支持的服务商')
    parts = urlsplit(url)
    host = parts.hostname or ''
    allowed = host == urlsplit(PROVIDERS[provider]['url']).hostname
    if provider == 'qwen':
        allowed = allowed or bool(re.fullmatch(r'[a-zA-Z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com', host))
    if parts.scheme != 'https' or not allowed or parts.username or parts.password or parts.query or parts.fragment or parts.port not in (None, 443):
        raise ValueError('Base URL 必须为所选服务商的官方 HTTPS 地址')
    if not model or not re.fullmatch(r'[a-zA-Z0-9._/-]{1,150}', model):
        raise ValueError('请填写有效的视觉模型 ID 或接入点 ID')
    if provider == 'deepseek' and model != 'deepseek-flash':
        raise ValueError('当前页面分析仅预设支持图片的 deepseek-flash')
    if provider == 'zhipu' and not re.search(r'glm-[0-9.]+v', model.lower()):
        raise ValueError('请选择智谱视觉模型（如 glm-4.6v-flash）')
    if provider == 'qwen' and not (model.startswith(('qwen3.7-', 'qwen3.6-', 'qwen3.5-', 'qwen-vl-', 'qwen3-vl-'))):
        raise ValueError('请选择千问视觉模型；普通 qwen-flash 不作为页面分析预设')


def public_configuration():
    with connect() as c:
        provider = selected(c)
        profiles = {}
        for key, info in PROVIDERS.items():
            item = profile(c, key)
            entries = key_entries(item)
            profiles[key] = {**info, 'url': item['url'], 'model': item['model'], 'has_key': bool(usable_keys(key,item)),
                'key_count': len(entries), 'keys': [{'id': k['id'], 'enabled': k.get('enabled',True),
                    'error': _key_failures.get((key,k['id']), '')} for k in entries]}
    return {'provider': provider, 'profiles': profiles}


def save(provider, url, model, api_key='', clear_key=False, keys=None):
    from .auto_analysis_service import _execution_lock
    if _execution_lock.locked():
        raise ValueError('请先全部暂停并等待请求停止，再修改API配置')
    url = url.strip().rstrip('/')
    validate(provider, url, model)
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM ai_jobs WHERE status='running'").fetchone():
            raise ValueError('请先暂停正在分析的任务，待其停止后再切换 API')
        item = profile(c, provider)
        entries = [] if clear_key else key_entries(item)
        if keys is not None and not clear_key:
            prior = {k['id']: k for k in entries}
            entries = []
            seen = set()
            secrets = set()
            for value in keys:
                row = value.model_dump() if hasattr(value, 'model_dump') else dict(value)
                key_id = row.get('id') or uuid.uuid4().hex
                if key_id in seen:
                    raise ValueError('密钥行标识重复')
                seen.add(key_id)
                secret = row.get('value','').strip()
                encrypted = base64.b64encode(crypt(secret.encode())).decode('ascii') if secret else prior.get(key_id,{}).get('value','')
                if not encrypted:
                    raise ValueError('新增密钥不能为空；不需要的空行请移除')
                plain = secret or crypt(base64.b64decode(encrypted),decrypt=True).decode()
                if plain in secrets:
                    raise ValueError('不能重复填写同一把API密钥')
                secrets.add(plain)
                entries.append({'id':key_id,'value':encrypted,'enabled':row.get('enabled',True)})
        if api_key.strip():
            encrypted = base64.b64encode(crypt(api_key.strip().encode())).decode('ascii')
            entries = [{'id':'legacy','value':encrypted,'enabled':True}]
        encrypted = entries[0]['value'] if entries else ''
        item = {'url': url, 'model': model, 'key': encrypted, 'keys': entries}
        c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('api_profile_' + provider, json.dumps(item)))
        c.execute("INSERT OR REPLACE INTO settings VALUES('ai_provider',?)", (provider,))
    with _key_lock:
        for identifier in list(_key_failures):
            if identifier[0] == provider:
                _key_failures.pop(identifier)
        for identifier in list(_key_cooldowns):
            if identifier[0]==provider: _key_cooldowns.pop(identifier)
    return {'ok': True, 'provider': provider, 'has_key': any(k.get('enabled',True) for k in entries)}


def credentials():
    if getattr(_bound,'credentials',None):
        return _bound.credentials
    with connect() as c:
        provider = selected(c)
        item = profile(c, provider)
    validate(provider, item['url'], item['model'])
    entries = usable_keys(provider,item)
    if not entries:
        raise ValueError('请在 API 配置中保存所选服务商的密钥')
    return provider, item, crypt(base64.b64decode(entries[0]['value']), decrypt=True).decode()


def bind_for_job():
    with connect() as c:
        provider = selected(c)
        item = profile(c,provider)
    validate(provider,item['url'],item['model'])
    entries = usable_keys(provider,item)
    if not entries:
        raise NoKeyAvailable('没有空闲可用密钥，任务继续排队')
    with _key_lock:
        idle=[k for k in entries if not _key_active.get((provider,k['id']),0)
              and (provider,k['id']) not in _key_failures and _key_cooldowns.get((provider,k['id']),0)<=time.monotonic()]
        if not idle: raise NoKeyAvailable('所有可用密钥正在处理其他论文，等待空闲位置')
        chosen = choose_idle_key(idle)
        identity=(provider,chosen['id'])
        _key_active[identity]=_key_active.get(identity,0)+1
    _bound.identity=identity
    try:
        _bound.credentials=(provider,item,crypt(base64.b64decode(chosen['value']),decrypt=True).decode())
    except Exception:
        release_binding()
        raise


def release_binding():
    identity=getattr(_bound,'identity',None)
    if identity:
        with _key_lock:
            _key_active[identity]=max(0,_key_active.get(identity,1)-1)
    _bound.credentials=None
    _bound.identity=None


def quarantine_binding(message):
    identity=getattr(_bound,'identity',None)
    if identity:
        with _key_lock:
            _key_failures[identity]=message
        return True
    return False


def ready():
    with connect() as c:
        provider = selected(c)
        if provider == 'codex':
            from .codex_service import auth_status
            return auth_status()
    info = public_configuration()
    item = info['profiles'][provider]
    configured = bool(item['has_key'] and item['model'])
    reason = '请完成 API 配置（服务商、视觉模型和密钥）'
    if configured:
        try:
            credentials()
        except ValueError as exc:
            configured = False
            reason = str(exc)
    with connect() as c: pool=pool_status(c)
    temporary=not configured and pool['cooling']>0
    if temporary: reason='密钥正在限流冷却，任务排队等待恢复'
    return {'available': True, 'logged_in': configured, 'mode': 'api', 'provider': provider,
            'name': item['name'], 'reason': reason,'temporarily_unavailable':temporary,'key_pool':pool}


def build_request(provider, item, images, prompt, schema, probe=False):
    content = [{'type': 'text', 'text': prompt}]
    size = 0
    for path in images:
        raw = path.read_bytes()
        size += len(raw)
        if size > 30 * 1024 * 1024:
            raise ValueError('页面图片超过 30 MB，请减少页数或降低分辨率；未发起 API 调用')
        content.append({'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(raw).decode()}})
    text = '只输出 JSON，不要 Markdown。严格遵守此 JSON Schema：' + json.dumps(schema, ensure_ascii=False)
    body = {'model': item['model'], 'messages': [{'role': 'system', 'content': text}, {'role': 'user', 'content': content}], 'stream': True, 'max_tokens': 128 if probe else 12000}
    if provider in ('qwen', 'deepseek', 'zhipu'):
        body['response_format'] = {'type': 'json_object'}
    if provider == 'qwen':
        body['enable_thinking'] = False
        body['stream_options'] = {'include_usage': True}
        if item['model'].startswith(('qwen3.7-', 'qwen3.8-')):
            schema = json.loads(json.dumps(schema))
            from .codex_service import strict_schema
            strict_schema(schema)
            definitions = schema.get('$defs', {})
            if 'Evidence' in definitions:
                pages = [int(path.stem.split('-')[-1]) if re.fullmatch(r'page-\d+', path.stem) else index for index, path in enumerate(images, 1)]
                definitions['Evidence']['properties']['page'] = {'type': 'integer', 'minimum': 1, 'maximum': len(images)} if pages == list(range(1, len(images) + 1)) else {'type': 'integer', 'enum': pages}
                definitions['Evidence']['properties']['block_id'] = {'type': 'string', 'const': ''}
                with connect() as c:
                    ids = [row[0] for row in c.execute("SELECT id FROM labels WHERE active=1 AND dimension!='personal'")]
                label = {'anyOf': [{'type': 'string', 'enum': ids}, {'type': 'string', 'pattern': '^new_[a-z0-9_]{1,60}$'}]}
                definitions['Tag']['properties']['label_id'] = label
                definitions['Claim']['properties']['label_ids']['items'] = label
                marker = '必须保持的标识字段：\n'
                if marker in prompt:
                    identities = json.loads(prompt.split(marker)[-1])
                    for field, value in identities.items():
                        schema['properties'][field]['const'] = value
            body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'paper_analysis', 'strict': True, 'schema': schema}}
    elif provider in ('doubao', 'zhipu'):
        body['thinking'] = {'type': 'disabled'}
    return body


def request(provider, item, key, body, timeout, cancel, workspace=None):
    result = queue.Queue()
    client = httpx.Client(timeout=httpx.Timeout(45, connect=10), follow_redirects=False)
    started = time.monotonic()
    identity = getattr(_bound,'identity',None)
    def run():
        try:
            output = []
            characters = 0
            first_content = None
            last_progress_write = 0
            finished = False
            with client.stream('POST', item['url'] + '/chat/completions', headers={'Authorization': 'Bearer ' + key}, json=body) as response:
                receipt = {'provider': provider, 'model': item.get('model', ''), 'endpoint': item['url'], 'http_status': response.status_code,
                           'request_id': response.headers.get('x-request-id', response.headers.get('request-id', '')), 'usage': None,
                           'key_id': identity[1] if identity else None}
                if workspace:
                    (workspace / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
                if response.status_code != 200:
                    message = {401: '密钥无效或已失效', 403: '账号或模型权限不足', 404: '模型或 API 地址不存在', 429: '额度不足或触发频率限制（429），任务将排队等待'}.get(response.status_code, '服务商请求失败')
                    try: retry_after=max(1,min(3600,float(response.headers.get('retry-after','60'))))
                    except ValueError: retry_after=60
                    raise ProviderRejected(response.status_code,f'{message}，HTTP {response.status_code}；请在服务商控制台核对',retry_after)
                for line in response.iter_lines():
                    if cancel() or time.monotonic() - started > timeout:
                        raise ValueError('API 分析已暂停或超时')
                    if not line.startswith('data:'):
                        continue
                    data = line[5:].strip()
                    if data == '[DONE]':
                        finished = True
                        break
                    event = json.loads(data)
                    receipt_changed = False
                    if event.get('id') and event['id'] != receipt.get('completion_id'):
                        receipt['completion_id'] = event['id']
                        receipt_changed = True
                    if event.get('usage'):
                        receipt['usage'] = event['usage']
                        receipt_changed = True
                    if workspace and receipt_changed:
                        (workspace / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
                    if event.get('error'):
                        raise ValueError('服务商返回流式错误，请核对额度、模型和权限')
                    for choice in event.get('choices', []):
                        fragment = choice.get('delta', {}).get('content') or ''
                        if fragment and first_content is None:
                            first_content = time.monotonic()
                            receipt['first_content_seconds'] = round(first_content - started, 2)
                            if workspace:
                                (workspace / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
                        output.append(fragment)
                        characters += len(fragment)
                        reason = choice.get('finish_reason')
                        if reason and reason != 'stop':
                            raise ValueError('输出被截断或过滤，结果未保存，请调整设置后重试')
                        finished = finished or reason == 'stop'
                    if workspace and time.monotonic() - last_progress_write >= .25:
                        now = time.monotonic()
                        (workspace / 'progress.json').write_text(json.dumps({'characters': characters, 'elapsed_seconds': int(now - started)}), encoding='utf-8')
                        last_progress_write = now
                if not finished or not ''.join(output).strip():
                    raise ValueError('API 未返回完整结果，请单独重试；不会自动重复计费调用')
            if workspace:
                receipt['api_elapsed_seconds'] = round(time.monotonic() - started, 2)
                receipt['output_seconds'] = round(time.monotonic() - first_content, 2) if first_content is not None else None
                (workspace / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
                (workspace / 'progress.json').write_text(json.dumps({'characters': characters, 'elapsed_seconds': int(time.monotonic() - started)}), encoding='utf-8')
            result.put(('ok', ''.join(output)))
        except httpx.TimeoutException:
            result.put(('error', ValueError('API 连接或接收超时，请检查网络后单独重试')))
        except Exception:
            # Provider error bodies/exception URLs may contain private data; do not persist them.
            import sys
            exc = sys.exc_info()[1]
            result.put(('error', exc if isinstance(exc, ValueError) else ValueError('API 网络或流式响应异常，请检查网络后单独重试')))
        finally:
            client.close()
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    while True:
        try:
            state, value = result.get(timeout=.2)
            if state == 'error':
                raise value
            return value
        except queue.Empty:
            if cancel() or time.monotonic() - started > timeout:
                client.close()
                raise ValueError('API 分析已暂停' if cancel() else 'API 分析超过单篇超时，旧结果保留')


def infer(workspace, images, prompt, schema, timeout, model, cancel):
    provider, item, key = credentials()
    body = build_request(provider, item, images, prompt, schema)
    (workspace / 'transport.json').write_text(json.dumps({'provider': provider, 'model': item['model'], 'started_at': time.time()}), encoding='utf-8')
    try:
        raw = request(provider, item, key, body, timeout, cancel, workspace)
    except ValueError as exc:
        if any(code in str(exc) for code in ('HTTP 401','HTTP 403')):
            quarantine_binding('密钥无效或权限不足；请修正并保存配置')
        if isinstance(exc,ProviderRejected) and exc.status_code==429:
            identity=getattr(_bound,'identity',None)
            if identity:
                with _key_lock: _key_cooldowns[identity]=time.monotonic()+exc.retry_after
        raise
    (workspace / 'response.json').write_text(raw, encoding='utf-8')
    return raw


def test_connection():
    from .auto_analysis_service import _execution_lock
    if _execution_lock.locked(): raise ValueError('请先暂停分析并等待请求停止，再测试密钥')
    import pymupdf
    from .pdf_service import PDF_LOCK
    import tempfile
    from pathlib import Path
    provider, item, key = credentials()
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'test.png'
        with PDF_LOCK, pymupdf.open() as document:
            page = document.new_page(width=320, height=100)
            page.insert_text((20, 55), 'VISION TEST 4827', fontsize=24)
            page.get_pixmap(alpha=False).save(path)
        body = build_request(provider, item, [path], '读取图片里的四位数字，输出 {"code":"数字"}。', {'type': 'object', 'properties': {'code': {'type': 'string'}}}, probe=True)
        raw = request(provider, item, key, body, 60, lambda: False)
    if json.loads(raw).get('code') != '4827':
        raise ValueError('请求成功，但图片识别测试未通过，请更换视觉模型')
    return {'ok': True, 'message': '连接与图片识别测试通过；不代表长论文准确率已验证'}
