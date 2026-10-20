import pymupdf
import pytest
from fastapi.testclient import TestClient
from backend import database
from backend.database import connect, migrate
from backend.import_service import import_file
from backend.main import app


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'test.db')
    pdf = tmp_path / 'paper.pdf'
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 50), 'A control research paper.')
        doc.save(pdf)
    with TestClient(app) as client:
        with connect() as c:
            _, pid = import_file(c, pdf)
        yield client, pid, pdf


def test_favorite_persists_and_combines_with_filters(library):
    client, pid, pdf = library
    assert client.get(f'/api/papers/{pid}').json()['is_favorite'] is False
    assert client.post('/api/search', json={'favorites_only': True}).json() == []
    client.post(f'/api/papers/{pid}/decision', json={'label_id': 'control', 'decision': 'manual'})
    before = client.get(f'/api/papers/{pid}').json()
    assert client.post(f'/api/papers/{pid}/favorite', json={'is_favorite': True}).status_code == 200
    migrate()  # Restart migrations must not reset saved favorites.
    with connect() as c:
        assert import_file(c, pdf) == ('duplicate', pid)
    result = client.post('/api/search', json={'favorites_only': True, 'filters': {'topic': ['control']}, 'text': 'control'}).json()
    assert [p['id'] for p in result] == [pid]
    assert client.post('/api/search', json={'favorites_only': True, 'filters': {'topic': ['game_theory']}}).json() == []
    assert client.post(f'/api/papers/{pid}/favorite', json={'is_favorite': False}).status_code == 200
    after = client.get(f'/api/papers/{pid}').json()
    assert after['tags'] == before['tags'] and after['decisions'] == before['decisions']
    assert client.post('/api/search', json={'favorites_only': True}).json() == []
    assert client.get(f'/api/papers/{pid}/pdf').content.startswith(b'%PDF-')


def test_modified_file_inherits_favorite(library):
    client, pid, pdf = library
    client.post(f'/api/papers/{pid}/favorite', json={'is_favorite': True})
    with pymupdf.open(pdf) as doc:
        doc.new_page().insert_text((40, 50), 'New content in a revised file.')
        doc.saveIncr()
    with connect() as c:
        status, new_pid = import_file(c, pdf)
    assert status == 'modified' and new_pid != pid
    assert client.get(f'/api/papers/{new_pid}').json()['is_favorite'] is True
    assert [p['id'] for p in client.post('/api/search', json={'favorites_only': True}).json()] == [new_pid]
    assert client.get(f'/api/papers/{pid}').json()['is_favorite'] is True


def test_unknown_paper_and_invalid_favorite(library):
    client, pid, _ = library
    assert client.post('/api/papers/999999/favorite', json={'is_favorite': True}).status_code == 404
    assert client.post(f'/api/papers/{pid}/favorite', json={}).status_code == 422
