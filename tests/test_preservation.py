import io
import json
import zipfile
import pytest
import pymupdf
from fastapi.testclient import TestClient
from backend import database
from backend.database import connect
from backend.archive_service import archived_pdf, archive_pdf
from backend.import_service import import_file
from backend.main import app


def pdf_bytes(text):
    doc = pymupdf.open()
    doc.new_page().insert_text((40, 50), text)
    raw = doc.tobytes()
    doc.close()
    return raw


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'test.db')
    path = tmp_path / 'original.pdf'
    path.write_bytes(pdf_bytes('Original research paper version.'))
    with TestClient(app) as client:
        with connect() as c:
            _, pid = import_file(c, path)
        yield client, pid, path


def test_overwrite_keeps_old_pdf_analysis_and_decisions(library):
    client, old, path = library
    original = path.read_bytes()
    with connect() as c:
        c.execute('INSERT INTO runs(paper_id,payload) VALUES(?,?)', (old, json.dumps({'title': 'Old GPT analysis', 'tags': [], 'claims': []})))
        c.execute("INSERT INTO decisions VALUES(?,'must_read','manual',CURRENT_TIMESTAMP)", (old,))
    path.write_bytes(pdf_bytes('Modified research paper version.'))
    with connect() as c:
        status, new = import_file(c, path)
        assert status == 'modified' and new != old
    assert client.get(f'/api/papers/{old}/pdf').content == original
    assert client.get(f'/api/papers/{new}/pdf').content == path.read_bytes()
    assert client.get(f'/api/papers/{old}').json()['analysis']['title'] == 'Old GPT analysis'
    assert client.get(f'/api/papers/{old}').json()['decisions'][0]['decision'] == 'manual'
    assert len(client.post('/api/search', json={}).json()) == 1
    assert len(client.post('/api/search', json={'show_versions': True}).json()) == 2


def test_original_deleted_and_archive_corruption_not_overwritten(library):
    client, pid, path = library
    original = path.read_bytes()
    paper = client.get(f'/api/papers/{pid}').json()
    path.unlink()
    assert client.get(f'/api/papers/{pid}/pdf').content == original
    backup = archived_pdf(paper['file_hash'])
    backup.write_bytes(b'corrupted archive')
    path.write_bytes(original)
    with pytest.raises(ValueError):
        archive_pdf(path, paper['file_hash'])
    assert backup.read_bytes() == b'corrupted archive'


def test_raw_pdf_chat_bundle(library):
    client, pid, path = library
    result = client.get(f'/api/papers/{pid}/bundle')
    assert result.status_code == 200
    with zipfile.ZipFile(io.BytesIO(result.content)) as z:
        assert z.read('original.pdf') == path.read_bytes()
        assert 'schema_version 必须为 2' in z.read('analysis-guide.md').decode()


def test_scanned_page_evidence_is_explicitly_unverified(library):
    client, pid, _ = library
    paper = client.get(f'/api/papers/{pid}').json()
    payload = {'paper_id': pid, 'document_hash': paper['file_hash'], 'ontology_version': 1, 'schema_version': 2,
               'title': 'GPT classification', 'authors': [], 'paper_type': 'unknown', 'summary': '',
               'tags': [{'label_id': 'control', 'evidence': [{'block_id': '', 'page': 1, 'quote': 'Read by GPT from the PDF image.'}]}], 'claims': [], 'suggestions': []}
    result = client.post(f'/api/papers/{pid}/analysis', json={'text': json.dumps(payload)})
    assert result.status_code == 200
    evidence = client.get(f'/api/papers/{pid}').json()['analysis']['tags'][0]['evidence'][0]
    assert evidence['verification'] == 'page_only'
    payload['tags'][0]['evidence'][0]['page'] = 999
    assert client.post(f'/api/papers/{pid}/analysis', json={'text': json.dumps(payload)}).status_code == 422


def test_failed_update_preserves_previous_import(library):
    client, pid, path = library
    original = client.get(f'/api/papers/{pid}/pdf').content
    path.write_bytes(b'Broken replacement PDF')
    with connect() as c:
        with pytest.raises(Exception):
            import_file(c, path)
    assert client.get(f'/api/papers/{pid}/pdf').content == original
    assert len(client.post('/api/search', json={}).json()) == 1
