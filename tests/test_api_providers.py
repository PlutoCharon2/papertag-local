import json
import threading
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from backend import api_service as service, database, auto_analysis_service as ai
from backend.database import connect
from backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'test.db')
    with TestClient(app) as result:
        yield result


def body(provider='qwen', secret='test-only-secret'):
    info = service.PROVIDERS[provider]
    return {'provider': provider, 'url': info['url'], 'model': info['model'] or 'doubao-seed-2-0-mini', 'api_key': secret}


def test_encrypted_key_not_exposed_and_reused_per_provider(client):
    assert client.post('/api/ai/provider', json=body()).status_code == 200
    public = client.get('/api/ai/providers').json()
    assert public['profiles']['qwen']['has_key']
    assert 'test-only-secret' not in json.dumps(public)
    with connect() as c:
        encrypted = service.profile(c, 'qwen')['key']
        assert 'test-only-secret' not in encrypted
    assert service.credentials()[2] == 'test-only-secret'
    client.post('/api/ai/provider', json=body('deepseek', 'other-test-secret'))
    client.post('/api/ai/provider', json=body(secret=''))
    assert service.credentials()[2] == 'test-only-secret'
    assert client.get('/api/ai/status').json()['auth']['logged_in']
    clear = {**body(secret=''), 'clear_key': True}
    client.post('/api/ai/provider', json=clear)
    assert not client.get('/api/ai/status').json()['auth']['logged_in']


def test_official_hosts_only_and_vision_model_guard(client):
    request = {**body(), 'url': 'https://evil.example/v1'}
    assert client.post('/api/ai/provider', json=request).status_code == 400
    request = {**body('zhipu'), 'model': 'glm-4.7-flash'}
    assert client.post('/api/ai/provider', json=request).status_code == 400
    request = {**body(), 'api_key': 'private' * 500}
    response = client.post('/api/ai/provider', json=request)
    assert response.status_code == 422 and 'private' not in response.text


def test_domestic_transport_uses_images_and_streamed_json(monkeypatch, tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert payload['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
        assert payload['enable_thinking'] is False
        assert request.headers['authorization'] == 'Bearer mock-key'
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"{\\\"ok\\\":true}"},"finish_reason":null}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    original = httpx.Client
    monkeypatch.setattr(service.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    image = tmp_path / 'image.png'
    image.write_bytes(b'fake-image-fixture')
    item = {'url': service.PROVIDERS['qwen']['url'], 'model': 'qwen3.7-flash'}
    request = service.build_request('qwen', item, [image], 'Read paper', {})
    raw = service.request('qwen', item, 'mock-key', request, 60, lambda: False, tmp_path)
    assert json.loads(raw) == {'ok': True}
    assert len(calls) == 1
    assert json.loads((tmp_path / 'progress.json').read_text())['characters'] > 0


def test_rate_limit_is_safe_and_not_retried(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, text='sensitive-provider-body mock-key')
    original = httpx.Client
    monkeypatch.setattr(service.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(ValueError) as error:
        service.request('qwen', {'url': service.PROVIDERS['qwen']['url']}, 'mock-key', {}, 60, lambda: False)
    assert '429' in str(error.value) and 'mock-key' not in str(error.value)
    assert len(calls) == 1


def test_unconfigured_upgrade_never_calls_model(client, monkeypatch):
    monkeypatch.setattr(ai, '_stop', threading.Event())
    with connect() as c:
        pid = c.execute("INSERT INTO papers(title,file_hash,page_count,parse_quality,status) VALUES('Pending','fixture',1,'good','awaiting_chat')").lastrowid
    monkeypatch.setattr(ai, 'source_pdf', lambda *args: Path('unused.pdf'))
    monkeypatch.setattr(service, 'infer', lambda *args: pytest.fail('Must not call without key'))
    ai.analyze_one(ai.enqueue(pid))
    assert client.get('/api/ai/jobs').json()[0]['status'] == 'waiting_login'


def test_running_job_prevents_provider_switch(client):
    with connect() as c:
        pid = c.execute("INSERT INTO papers(title,file_hash,page_count,parse_quality,status) VALUES('Active','fixture',1,'good','awaiting_chat')").lastrowid
        c.execute("INSERT INTO ai_jobs(paper_id,status) VALUES(?,'running')", (pid,))
    assert client.post('/api/ai/provider', json=body()).status_code == 400


def test_api_worker_saves_result_and_reuses_it(client, tmp_path, monkeypatch):
    import pymupdf
    from backend.import_service import import_file
    monkeypatch.setattr(ai, '_stop', threading.Event())
    pdf = tmp_path / 'sample.pdf'
    doc = pymupdf.open()
    doc.new_page().insert_text((40, 50), 'A sample research paper.')
    doc.save(pdf)
    doc.close()
    with connect() as c:
        _, pid = import_file(c, pdf)
        paper = dict(c.execute('SELECT * FROM papers WHERE id=?', (pid,)).fetchone())
    client.post('/api/ai/provider', json=body())
    payload = {'paper_id': pid, 'document_hash': paper['file_hash'], 'ontology_version': 1, 'schema_version': 2,
               'title': 'API paper', 'authors': [], 'year': None, 'doi': '', 'paper_type': 'unknown',
               'summary': 'Read by remote API', 'tags': [], 'claims': [], 'suggestions': [], 'new_labels': []}
    calls = []
    def handler(request):
        calls.append(request)
        data = {'choices': [{'delta': {'content': json.dumps(payload)}, 'finish_reason': 'stop'}]}
        return httpx.Response(200, text='data: ' + json.dumps(data) + '\n\ndata: [DONE]\n\n')
    original = httpx.Client
    monkeypatch.setattr(service.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    ai.analyze_one(ai.enqueue(pid))
    assert client.get('/api/ai/jobs').json()[0]['status'] == 'completed'
    assert client.get(f'/api/papers/{pid}').json()['analysis']['title'] == 'API paper'
    assert ai.enqueue(pid) is None
    assert len(calls) == 1


def test_bulk_pause_preserves_completed_and_resume_skips_failed(client):
    with connect() as c:
        for index, status in enumerate(['running','queued','waiting_login','completed','failed']):
            pid = c.execute("INSERT INTO papers(title,file_hash,page_count,parse_quality,status) VALUES(?,?,1,'good','awaiting_chat')", (str(index), str(index))).lastrowid
            c.execute('INSERT INTO ai_jobs(paper_id,status) VALUES(?,?)', (pid, status))
    assert client.post('/api/ai/pause-all', json={}).json()['paused'] == 3
    assert not client.get('/api/ai/status').json()['config']['enabled']
    assert client.get('/api/ai/queue').json() == {'paused': 3, 'completed': 1, 'failed': 1}
    assert client.get('/api/ai/jobs').json()[0]['status'] == 'failed'
    assert client.post('/api/ai/resume-all', json={}).json()['resumed'] == 3
    assert client.get('/api/ai/queue').json() == {'queued': 3, 'completed': 1, 'failed': 1}


def test_vision_probe_has_no_pillow_dependency(client, monkeypatch):
    client.post('/api/ai/provider', json=body())
    def fake(provider, item, key, request, timeout, cancel):
        assert request['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
        return '{"code":"4827"}'
    monkeypatch.setattr(service, 'request', fake)
    assert client.post('/api/ai/test', json={}).json()['ok']


def test_qwen_schema_requires_page_and_known_label_or_new_key(client, tmp_path):
    from backend.schemas import AutoAnalysis
    image = tmp_path / 'page.png'
    image.write_bytes(b'fixture')
    item = {'model': 'qwen3.7-flash'}
    request = service.build_request('qwen', item, [image], 'Read paper', AutoAnalysis.model_json_schema())
    schema = request['response_format']['json_schema']['schema']
    assert request['response_format']['json_schema']['strict']
    assert schema['$defs']['Evidence']['properties']['page'] == {'type': 'integer', 'minimum': 1, 'maximum': 1}
    assert 'page' in schema['$defs']['Evidence']['required']
    assert schema['$defs']['Claim']['properties']['conditions']['type'] == 'array'
    assert 'anyOf' in schema['$defs']['Tag']['properties']['label_id']
