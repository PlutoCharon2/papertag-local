"""Official CLI transport using ChatGPT auth. This module never handles credentials."""
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from .database import ROOT

CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_auth_cache = (0, {})
_login_process = None
_auth_lock = threading.Lock()


def cli_path():
    bundled = ROOT / 'runtime' / 'bin' / 'codex.exe'
    if bundled.is_file():
        return str(bundled)
    value = shutil.which('codex.exe') or shutil.which('codex')
    if value:
        return value
    app_bin = Path(os.environ.get('LOCALAPPDATA', '')) / 'OpenAI' / 'Codex' / 'bin'
    if app_bin.is_dir():
        candidates = sorted(app_bin.glob('*/codex.exe'), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            return str(candidates[0])
    return None


def account_environment():
    env = dict(os.environ)
    # Prevent inherited API credentials from silently switching the billing method.
    env.pop('OPENAI_API_KEY', None)
    env.pop('CODEX_API_KEY', None)
    return env


def auth_status(refresh=False):
    global _auth_cache
    with _auth_lock:
        if not refresh and time.monotonic() - _auth_cache[0] < 3:
            return dict(_auth_cache[1])
        binary = cli_path()
        result = {'available': bool(binary), 'logged_in': False, 'mode': 'chatgpt', 'login_running': bool(_login_process and _login_process.poll() is None)}
        if binary:
            try:
                proc = subprocess.run([binary, 'login', 'status'], env=account_environment(), capture_output=True,
                                      text=True, encoding='utf-8', errors='replace', timeout=15, creationflags=CREATE_NO_WINDOW)
                output = (proc.stdout + proc.stderr).lower()
                result['logged_in'] = proc.returncode == 0 and 'chatgpt' in output
                if not result['logged_in']:
                    result['reason'] = '请登录 ChatGPT 账号；本程序不会使用 API 密钥模式'
            except Exception:
                result['reason'] = '无法检查 Codex 登录，请重试'
        else:
            result['reason'] = '安装包缺少 Codex 运行时'
        _auth_cache = (time.monotonic(), result)
        return dict(result)


def start_login():
    global _login_process, _auth_cache
    if auth_status(refresh=True)['logged_in']:
        return {'ok': True, 'already_logged_in': True}
    binary = cli_path()
    if not binary:
        raise ValueError('未找到官方 Codex 运行时，请重新安装')
    if not _login_process or _login_process.poll() is not None:
        _login_process = subprocess.Popen([binary, '-c', 'forced_login_method="chatgpt"', 'login'],
                                         env=account_environment(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    _auth_cache = (0, {})
    return {'ok': True, 'already_logged_in': False}


def safe_error(text):
    text = re.sub(r'sk-[A-Za-z0-9_-]+', '[redacted]', text)
    text = re.sub(r'(?i)bearer\s+\S+', 'Bearer [redacted]', text)
    text = re.sub(r'https?://\S*(?:token|code|state)=\S*', '[login URL redacted]', text)
    return text[-1800:]


def strict_schema(schema):
    # Structured output requires all declared fields, including fields that may be null.
    if isinstance(schema, dict):
        if schema.get('type') == 'object' and 'properties' in schema:
            schema['required'] = list(schema['properties'])
            schema['additionalProperties'] = False
        schema.pop('default', None)
        for item in schema.values():
            strict_schema(item)
    elif isinstance(schema, list):
        for item in schema:
            strict_schema(item)
    return schema


def infer(workspace: Path, images, prompt: str, schema, timeout: int, model='', cancel=None):
    binary = cli_path()
    if not binary or not auth_status(refresh=True)['logged_in']:
        raise ValueError('ChatGPT 账号未登录，点击 GPT 登录后重试')
    schema_path = workspace / 'schema.json'
    response = workspace / 'response.json'
    schema_path.write_text(json.dumps(strict_schema(schema), ensure_ascii=False), encoding='utf-8')
    (workspace / 'prompt.txt').write_text(prompt, encoding='utf-8')
    # The model sees only attached PDF page images. No shell, browser or user plugins are needed.
    command = [binary, 'exec', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check', '--sandbox', 'read-only',
               '-c', 'forced_login_method="chatgpt"', '-c', 'features.shell_tool=false', '-c', 'features.apps=false',
               '--json', '--output-schema', str(schema_path), '--output-last-message', str(response), '-C', str(workspace)]
    if model:
        command += ['--model', model]
    for path in images:
        command += ['--image', str(path)]
    command += ['--', '-']
    (workspace / 'request_started').write_text(str(time.time()), encoding='ascii')
    with (workspace / 'events.jsonl').open('w', encoding='utf-8') as events, (workspace / 'transport.log').open('w', encoding='utf-8') as errors:
        process = subprocess.Popen(command, cwd=workspace, env=account_environment(), stdin=subprocess.PIPE,
                                   stdout=events, stderr=errors, text=True, encoding='utf-8', creationflags=CREATE_NO_WINDOW)
        process.stdin.write(prompt)
        process.stdin.close()
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if (cancel and cancel()) or time.monotonic() >= deadline:
                process.kill()
                process.wait(timeout=10)
                raise ValueError('分析已暂停' if cancel and cancel() else 'GPT 分析超时，可单独重试；旧数据已保留')
            time.sleep(.2)
    if process.returncode != 0 or not response.is_file():
        error = (workspace / 'transport.log').read_text(encoding='utf-8', errors='replace')
        for line in (workspace / 'events.jsonl').read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                event = json.loads(line)
                if event.get('type') == 'error':
                    error += '\n' + str(event.get('message', ''))
                elif event.get('item', {}).get('type') == 'error':
                    error += '\n' + str(event['item'].get('message', ''))
            except (ValueError, AttributeError):
                continue
        raise ValueError('Codex 分析失败：' + safe_error(error))
    return response.read_text(encoding='utf-8')
