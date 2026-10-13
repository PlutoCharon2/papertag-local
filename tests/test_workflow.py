import json
import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient
from backend import database
from backend.database import connect
from backend.import_service import import_file, run_job
from backend.main import app


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'test.db')
    pdf = tmp_path / 'paper.pdf'
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), 'Algorithm A uses binary feedback. It converges to a neighborhood.\nAlgorithm B uses gradient feedback. The averaged system converges almost surely.', fontsize=10)
    doc.save(pdf)
    doc.close()
    with TestClient(app) as client:
        with connect() as c:
            status, paper_id = import_file(c, pdf)
            assert status == 'added'
        yield client, paper_id, pdf, tmp_path


def analysis_for(client, paper_id):
    paper = client.get(f'/api/papers/{paper_id}').json()
    evidence = {'block_id': paper['blocks'][0]['id'], 'quote': paper['blocks'][0]['text']}
    def claim(id, label_ids, method):
        return {'id': id, 'kind': 'theoretical_result', 'text': method, 'method': method,
                'system': 'averaged system' if method == 'B' else 'original system', 'conditions': ['unknown'],
                'target': 'unknown', 'result_form': 'unknown', 'scope': 'unknown', 'residual': 'unknown',
                'label_ids': label_ids, 'evidence': [evidence]}
    return {'paper_id': paper_id, 'document_hash': paper['file_hash'], 'ontology_version': 1, 'schema_version': 1,
            'title': 'Two algorithms', 'authors': ['A'], 'year': 2025, 'doi': '', 'paper_type': 'theory', 'summary': 'Test',
            'tags': [{'label_id': label, 'evidence': [evidence]} for label in ['binary_feedback', 'practical', 'gradient_feedback', 'almost_sure']],
            'claims': [claim('a', ['binary_feedback', 'practical'], 'A'), claim('b', ['gradient_feedback', 'almost_sure'], 'B')], 'suggestions': []}


def save(client, paper_id, a):
    return client.post(f'/api/papers/{paper_id}/analysis', json={'text': json.dumps(a)})


def test_duplicate_and_multiple_paths(library):
    client, pid, pdf, tmp = library
    copy = tmp / 'copy.pdf'
    copy.write_bytes(pdf.read_bytes())
    with connect() as c:
        assert import_file(c, copy) == ('duplicate', pid)
        assert c.execute('SELECT COUNT(*) FROM papers').fetchone()[0] == 1
    assert len(client.get(f'/api/papers/{pid}').json()['files']) == 2


def test_evidence_and_packet(library):
    client, pid, *_ = library
    a = analysis_for(client, pid)
    packet = client.get(f'/api/papers/{pid}/packet')
    assert packet.status_code == 200
    assert a['document_hash'] in packet.text and 'p1_b1' in packet.text
    assert save(client, pid, a).status_code == 200
    a['tags'][0]['evidence'][0]['quote'] = 'This fabricated sentence is not present.'
    assert save(client, pid, a).status_code == 422
    assert len(client.get(f'/api/papers/{pid}').json()['history']) == 1


def test_wrong_paper_illegal_label_and_schema(library):
    client, pid, *_ = library
    a = analysis_for(client, pid)
    a['document_hash'] = 'wrong'
    assert save(client, pid, a).status_code == 422
    a = analysis_for(client, pid)
    a['tags'][0]['label_id'] = 'made_up'
    assert save(client, pid, a).status_code == 422
    a = analysis_for(client, pid)
    a['confidence'] = 1.0
    assert save(client, pid, a).status_code == 422
    assert client.post(f'/api/papers/{pid}/analysis', json={'text': '{invalid'}).status_code == 422


def test_same_claim_prevents_algorithm_conflation(library):
    client, pid, *_ = library
    assert save(client, pid, analysis_for(client, pid)).status_code == 200
    query = {'filters': {'feedback': ['binary_feedback'], 'result': ['almost_sure']}}
    assert len(client.post('/api/search', json=query).json()) == 1
    query['same_claim'] = True
    assert client.post('/api/search', json=query).json() == []
    query['filters']['result'] = ['practical']
    assert len(client.post('/api/search', json=query).json()) == 1


def test_manual_rejection_survives_reanalysis(library):
    client, pid, *_ = library
    a = analysis_for(client, pid)
    assert save(client, pid, a).status_code == 200
    client.post(f'/api/papers/{pid}/decision', json={'label_id': 'binary_feedback', 'decision': 'rejected'})
    client.post(f'/api/papers/{pid}/decision', json={'label_id': 'must_read', 'decision': 'manual'})
    assert save(client, pid, a).status_code == 200
    tags = client.get(f'/api/papers/{pid}').json()['tags']
    assert 'binary_feedback' not in {t['label_id'] for t in tags}
    assert next(t for t in tags if t['label_id'] == 'must_read')['state'] == 'manual'
    query = {'filters': {'feedback': ['binary_feedback']}, 'same_claim': True}
    assert client.post('/api/search', json=query).json() == []


def test_or_and_parent_and_reviewed(library):
    client, pid, *_ = library
    save(client, pid, analysis_for(client, pid))
    assert len(client.post('/api/search', json={'filters': {'result': ['bounded', 'almost_sure']}}).json()) == 1
    assert client.post('/api/search', json={'filters': {'result': ['almost_sure'], 'topic': ['control']}}).json() == []
    client.post(f'/api/papers/{pid}/decision', json={'label_id': 'extremum_seeking', 'decision': 'manual'})
    assert len(client.post('/api/search', json={'filters': {'topic': ['control']}, 'reviewed_only': True}).json()) == 1
    assert client.post('/api/search', json={'filters': {'result': ['almost_sure']}, 'reviewed_only': True}).json() == []


def test_empirical_and_no_theorem(library):
    client, pid, *_ = library
    a = analysis_for(client, pid)
    a['paper_type'] = 'empirical'
    a['claims'] = []
    a['tags'] = []
    assert save(client, pid, a).status_code == 200
    assert client.get(f'/api/papers/{pid}').json()['analysis']['claims'] == []


def test_ontology_version_and_personal_protection(library):
    client, pid, *_ = library
    a = analysis_for(client, pid)
    a['tags'][0]['label_id'] = 'must_read'
    assert save(client, pid, a).status_code == 422
    result = client.post('/api/ontology', json={'id': 'computer_vision', 'name': 'Computer Vision', 'dimension': 'topic', 'definition': 'Studies visual perception from images.'})
    assert result.status_code == 200
    assert save(client, pid, analysis_for(client, pid)).status_code == 422


def test_cross_site_block_and_export(library):
    client, pid, *_ = library
    assert client.post('/api/search', json={}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/settings', headers={'Host': 'evil.example'}).status_code == 403
    assert client.post('/api/export/json', json={}).status_code == 200
    assert client.post('/api/export/csv', json={}).text.startswith('\ufeffid,')


def test_corrupt_and_scan_pdf(library):
    _, _, _, tmp = library
    broken = tmp / 'broken.pdf'
    broken.write_bytes(b'not a PDF')
    with connect() as c:
        with pytest.raises(Exception):
            import_file(c, broken)
    blank = tmp / 'scan.pdf'
    doc = fitz.open()
    doc.new_page()
    doc.save(blank)
    doc.close()
    with connect() as c:
        _, pid = import_file(c, blank)
        row = c.execute('SELECT * FROM papers WHERE id=?', (pid,)).fetchone()
        assert row['status'] == 'needs_ocr'
        assert row['parse_quality'] == 'needs_review'


def test_batch_failure_isolated_and_rescan_idempotent(library):
    _, _, _, tmp = library
    broken = tmp / 'broken.pdf'
    broken.write_bytes(b'not a PDF')
    with connect() as c:
        job = c.execute("INSERT INTO jobs(path,status) VALUES(?,'waiting')", (str(tmp),)).lastrowid
    run_job(job)
    with connect() as c:
        row = c.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone()
        assert row['status'] == 'completed'
        assert row['failed'] == 1 and row['duplicates'] == 1 and row['done'] == 2
        assert c.execute('SELECT COUNT(*) FROM papers').fetchone()[0] == 1


def test_paused_waiting_job_is_not_started(library):
    _, _, _, tmp = library
    with connect() as c:
        job = c.execute("INSERT INTO jobs(path,status) VALUES(?,'paused')", (str(tmp),)).lastrowid
    run_job(job)
    with connect() as c:
        assert c.execute('SELECT status FROM jobs WHERE id=?', (job,)).fetchone()[0] == 'paused'
