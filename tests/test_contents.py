import json
import pymupdf
import pytest
from backend import contents_service, auto_analysis_service as ai, codex_service
from backend.database import connect
from backend.import_service import import_file
from test_automatic import library, payload


def test_long_document_only_sends_selected_contents(library, tmp_path, monkeypatch):
    client, _, _ = library
    path = tmp_path / 'book.pdf'
    with pymupdf.open() as doc:
        for i in range(31):
            doc.new_page().insert_text((40, 50), 'Contents acoustic levitation' if i == 4 else 'Body')
        doc.save(path)
    with connect() as c:
        _, pid = import_file(c, path)
        paper = dict(c.execute('SELECT * FROM papers WHERE id=?', (pid,)).fetchone())
    calls = []
    def fake(workspace, images, prompt, schema, timeout, model, cancel):
        calls.append(len(images))
        if 'pages' in schema['properties']:
            data = {'pages': [5], 'reason': 'Contents'}
            assert len(images) == 30
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
    assert calls == [30, 1]
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
            contents_service.locate(doc, tmp_path, Transport, 60, '', lambda: False, lambda: None)


def test_sparse_directory_page_schema(library, tmp_path):
    from backend import api_service
    from backend.schemas import AutoAnalysis
    image = tmp_path / 'page-005.png'
    image.write_bytes(b'fixture')
    request = api_service.build_request('qwen', {'model': 'qwen3.7-flash'}, [image], 'Directory', AutoAnalysis.model_json_schema())
    page = request['response_format']['json_schema']['schema']['$defs']['Evidence']['properties']['page']
    assert page == {'type': 'integer', 'enum': [5]}
