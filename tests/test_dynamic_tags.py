import json
import pymupdf
import pytest
from fastapi.testclient import TestClient
from backend import database
from backend.database import connect
from backend.import_service import import_file
from backend.main import app


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'test.db')
    pdf = tmp_path / 'sample.pdf'
    doc = pymupdf.open()
    doc.new_page().insert_text((40, 50), 'Control research with dynamic labels and local storage.')
    doc.save(pdf)
    doc.close()
    with TestClient(app) as client:
        with connect() as c:
            _, pid = import_file(c, pdf)
        yield client, pid


def test_facets_only_used_and_parent_usage(library):
    client, pid = library
    assert all(l['paper_count'] == 0 for l in client.get('/api/ontology').json()['labels'])
    client.post(f'/api/papers/{pid}/decision', json={'label_id': 'extremum_seeking', 'decision': 'manual'})
    used = {l['id']: l['paper_count'] for l in client.get('/api/ontology').json()['labels'] if l['paper_count']}
    assert used == {'control': 1, 'extremum_seeking': 1}


def test_rename_delete_restore_keep_history(library):
    client, pid = library
    client.post(f'/api/papers/{pid}/decision', json={'label_id': 'game_theory', 'decision': 'manual'})
    version = client.get('/api/ontology').json()['version']
    assert client.patch('/api/ontology/game_theory', json={'name': '博弈与均衡'}).status_code == 200
    assert client.get('/api/ontology').json()['version'] == version
    assert client.delete('/api/ontology/game_theory').status_code == 200
    assert client.get(f'/api/papers/{pid}').json()['tags'] == []
    assert client.get(f'/api/papers/{pid}').json()['decisions'][0]['label_id'] == 'game_theory'
    assert client.post(f'/api/papers/{pid}/decision', json={'label_id': 'game_theory', 'decision': 'manual'}).status_code == 400
    assert client.patch('/api/ontology/game_theory', json={'active': True}).status_code == 200
    assert client.get(f'/api/papers/{pid}').json()['tags'][0]['label_id'] == 'game_theory'


def test_add_new_field_and_reject_duplicate(library):
    client, pid = library
    new = {'id': 'new_science', 'name': '新研究领域', 'dimension': 'topic', 'definition': '来自新文献的研究主题。'}
    assert client.post('/api/ontology', json=new).status_code == 200
    new['id'] = 'another_id'
    assert client.post('/api/ontology', json=new).status_code == 400
    client.post(f'/api/papers/{pid}/decision', json={'label_id': 'new_science', 'decision': 'manual'})
    assert next(l for l in client.get('/api/ontology').json()['labels'] if l['id'] == 'new_science')['paper_count'] == 1


def test_suggestions_from_latest_local_analysis(library):
    client, pid = library
    with connect() as c:
        c.execute('INSERT INTO runs(paper_id,payload) VALUES(?,?)', (pid, json.dumps({'title': 'Paper', 'tags': [], 'suggestions': ['Computer Vision']})))
    assert client.get('/api/ontology').json()['suggestions'][0]['text'] == 'Computer Vision'
