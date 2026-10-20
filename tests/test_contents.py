import json
import pymupdf
import pytest
from backend import contents_service, auto_analysis_service as ai, codex_service
from backend.database import connect
from backend.import_service import import_file
from test_automatic import library, payload


@pytest.mark.parametrize('max_pages', [12, 60])
def test_long_document_only_sends_selected_contents(library, tmp_path, monkeypatch, max_pages):
    client, _, _ = library
    path = tmp_path / 'book.pdf'
    with pymupdf.open() as doc:
        for i in range(max_pages + 1):
            doc.new_page().insert_text((40, 50), 'Contents acoustic levitation' if i == 4 else 'Body')
        doc.save(path)
    with connect() as c:
        c.execute("UPDATE settings SET value=? WHERE key='ai_max_pages'", (str(max_pages),))
        _, pid = import_file(c, path)
        paper = dict(c.execute('SELECT * FROM papers WHERE id=?', (pid,)).fetchone())
    calls = []
    def fake(workspace, images, prompt, schema, timeout, model, cancel):
        calls.append(len(images))
        if 'pages' in schema['properties']:
            data = {'pages': [5], 'reason': 'Contents'}
            assert len(images) == max_pages
            assert schema['properties']['pages']['items']['enum'][-1] == max_pages
        else:
            assert [p.name for p in images] == ['page-005.png']
            assert 'claims 必须为空数组' in prompt
            data = payload(paper)
            data['tags'][0]['evidence'][0]['page'] = 5
        raw = json.dumps(data)
        (workspace / 'response.json').write_text(raw, encoding='utf-8')
        return raw
    monkeypatch.setattr(codex_service, 'infer', fake)
    ai.analyze_one(ai.enqueue(pid))
    result = client.get(f'/api/papers/{pid}').json()['analysis']
    assert calls == [max_pages, 1]
    assert result['_analysis_scope'] == 'contents'
    assert result['_source_pages'] == [5]
    assert not result['claims']
    assert ai.enqueue(pid) is None


def test_directory_rejects_unseen_evidence_and_claims():
    with pytest.raises(ValueError, match='未上传'):
        contents_service.restrict(json.dumps({'claims': [], 'tags': [{'evidence': [{'page': 1}]}]}), [5])
    with pytest.raises(ValueError, match='断言'):
        contents_service.restrict(json.dumps({'claims': [{'text': 'proven'}]}), [5])


def test_no_directory_does_not_analyze_body(tmp_path):
    class Transport:
        @staticmethod
        def infer(*args):
            return '{"pages":[],"reason":"not found"}'
    with pymupdf.open() as doc:
        doc.new_page()
        with pytest.raises(ValueError, match='未找到完整目录'):
            contents_service.locate(doc, tmp_path, Transport, 60, '', lambda: False, lambda: None, max_pages=20)


def test_sparse_directory_page_schema(library, tmp_path):
    from backend import api_service
    from backend.schemas import AutoAnalysis
    image = tmp_path / 'page-005.png'
    image.write_bytes(b'fixture')
    request = api_service.build_request('qwen', {'model': 'qwen3.7-flash'}, [image], 'Directory', AutoAnalysis.model_json_schema())
    page = request['response_format']['json_schema']['schema']['$defs']['Evidence']['properties']['page']
    assert page == {'type': 'integer', 'enum': [5]}


def test_configured_limit_allows_long_paper_without_directory(library, tmp_path, monkeypatch):
    client, _, _ = library
    path = tmp_path / 'long-paper.pdf'
    with pymupdf.open() as doc:
        for i in range(33):
            doc.new_page().insert_text((40, 50), 'Paper body without contents')
        doc.save(path)
    with connect() as c:
        c.execute("UPDATE settings SET value='60' WHERE key='ai_max_pages'")
        _, pid = import_file(c, path)
        paper = dict(c.execute('SELECT * FROM papers WHERE id=?', (pid,)).fetchone())
    calls = []
    def fake(workspace, images, prompt, schema, *args):
        assert 'pages' not in schema['properties']
        calls.append(len(images))
        return json.dumps(payload(paper))
    monkeypatch.setattr(codex_service, 'infer', fake)
    ai.analyze_one(ai.enqueue(pid))
    assert calls == [33]
    assert client.get('/api/ai/jobs').json()[0]['status'] == 'completed'


def test_bad_locator_cache_is_preserved_and_retry_calls_transport(tmp_path):
    folder = tmp_path / 'contents_locator_1'
    folder.mkdir()
    (folder / 'response.json').write_text('{"pages": [', encoding='utf-8')
    calls = []
    class Transport:
        @staticmethod
        def infer(*args):
            calls.append(1)
            return '{"pages":[1],"reason":"Contents"}'
    with pymupdf.open() as doc:
        doc.new_page()
        with pytest.raises(ValueError, match='返回不完整'):
            contents_service.locate(doc, tmp_path, Transport, 60, '', lambda: False, lambda: None, max_pages=20)
        assert list(folder.glob('rejected-*.json')) and not calls
        assert contents_service.locate(doc, tmp_path, Transport, 60, '', lambda: False, lambda: None, max_pages=20) == [1]
        assert calls == [1]


def test_directory_result_tag_does_not_discard_valid_topics(library):
    client, pid, paper = library
    data = payload(paper)
    data['tags'].append({'label_id': 'asymptotic', 'evidence': [{'page': 1, 'quote': 'Contents'}]})
    with connect() as c:
        ai.commit_result(c, paper, json.dumps(data), None, [1])
    result = client.get(f'/api/papers/{pid}').json()
    assert result['status'] == 'partial_result'
    assert result['analysis']['_analysis_scope'] == 'contents'
    assert result['analysis']['_validation_issues']
    assert 'asymptotic' not in {tag['label_id'] for tag in result['tags']}
