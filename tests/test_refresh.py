import json
import pymupdf
import pytest
from fastapi.testclient import TestClient
from backend import database, main, import_service, refresh_service
from backend.database import connect


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'app/library.db')
    monkeypatch.setattr(main, 'dispatch', import_service.run_job)
    with TestClient(main.app) as client:
        yield client, tmp_path


def pdf(path):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 50), 'An original paper with enough content to parse reliably.')
        doc.save(path)


def test_manual_refresh_discovers_new_papers_without_modifying_sources(library):
    client, root = library
    sources = root / 'papers'
    sources.mkdir()
    first = sources / 'original.pdf'
    pdf(first)
    assert client.post('/api/import', json={'path': str(sources)}).status_code == 200
    second = sources / '[2026][tac]New paper.pdf'
    pdf(second)
    # Distinct content, without depending on PDF creation timestamps.
    with pymupdf.open(second) as doc:
        doc[0].insert_text((40, 85), 'Another paper')
        doc.saveIncr()
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sources.iterdir()}
    response = client.post('/api/update', json={})
    assert response.status_code == 200
    job = client.get('/api/jobs').json()[0]
    assert job['status'] == 'completed' and job['added'] == 1 and job['duplicates'] == 1
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sources.iterdir()}
    rows = client.post('/api/search', json={}).json()
    paper = next(row for row in rows if str(second) in row['files'])
    assert paper['year'] == 2026 and paper['publication_short'] == ''
    second.unlink()  # External deletion removes the item from the visible library.
    assert client.post('/api/update', json={}).status_code == 200
    assert len(client.post('/api/search', json={}).json()) == 1


def test_refresh_defaults_validation_and_persistence(library):
    client, _ = library
    assert client.get('/api/refresh/settings').json() == {'enabled': True, 'interval_minutes': 20}
    assert client.post('/api/refresh/settings', json={'enabled': True, 'interval_minutes': 0}).status_code == 422
    assert client.post('/api/refresh/settings', json={'enabled': False, 'interval_minutes': 45}).status_code == 200
    assert client.get('/api/refresh/settings').json() == {'enabled': False, 'interval_minutes': 45}


def test_timer_checks_at_twenty_minutes_and_skips_active_or_disabled(library, monkeypatch):
    client, _ = library
    calls = []
    monkeypatch.setattr(main, 'update_library', lambda: calls.append(1) or {'job_id': 9})
    monkeypatch.setattr(refresh_service, '_last_started', 100)
    assert refresh_service.check_due(1299) is None
    assert refresh_service.check_due(1300) == {'job_id': 9}
    assert refresh_service.check_due(1301) is None
    with connect() as c:
        c.execute("INSERT INTO jobs(path,status) VALUES('test','running')")
    assert refresh_service.check_due(2600) is None
    with connect() as c:
        c.execute("UPDATE jobs SET status='completed'")
    assert refresh_service.check_due(2600) == {'job_id': 9}
    client.post('/api/refresh/settings', json={'enabled': False, 'interval_minutes': 1})
    assert refresh_service.check_due(10000000000) is None
    assert calls == [1, 1]


def test_publication_short_is_abbreviation_not_uppercase_full_journal(library):
    client, root = library
    path = root / 'paper.pdf'
    pdf(path)
    with connect() as c:
        _, pid = import_service.import_file(c, path)
        c.execute('INSERT INTO runs(paper_id,payload) VALUES(?,?)', (pid, json.dumps({
            'tags': [], 'claims': [], 'year': 2024, 'journal': 'IEEE Transactions on Automatic Control',
            'journal_abbreviation': 'tac'})))
        from backend.publication import cache_key
        c.execute('INSERT INTO settings VALUES(?,?)', (cache_key('IEEE Transactions on Automatic Control'), json.dumps({
            'canonical_name': 'IEEE Transactions on Automatic Control', 'abbreviation': 'TAC', 'abbreviation_verified': True})))
    paper = client.post('/api/search', json={}).json()[0]
    assert paper['year'] == 2024 and paper['publication_short'] == 'TAC'
    with connect() as c:
        c.execute('UPDATE runs SET payload=? WHERE paper_id=?', (json.dumps({
            'tags': [], 'claims': [], 'journal': 'A Journal With No Verified Abbreviation'}), pid))
    assert client.post('/api/search', json={}).json()[0]['publication_short'] == 'A Journal With No Verified Abbreviation'


def test_check_new_queues_only_new_content_and_keeps_pause(library):
    client, root = library
    sources = root / 'check-new'
    sources.mkdir()
    pdf(sources / 'existing.pdf')
    assert client.post('/api/import', json={'path': str(sources)}).status_code == 200
    client.post('/api/ai/pause-all', json={})
    fresh = sources / 'new.pdf'
    pdf(fresh)
    with pymupdf.open(fresh) as doc:
        doc[0].insert_text((40, 90), 'New content for analysis')
        doc.saveIncr()
    original = fresh.read_bytes()
    result = client.post('/api/check-new', json={})
    assert result.status_code == 200 and result.json()['analysis_enabled'] is False
    jobs = client.get('/api/ai/jobs').json()
    assert len(jobs) == 2 and all(j['status'] == 'queued' for j in jobs)
    with connect() as c:
        paths = {r[0] for r in c.execute('SELECT path FROM files')}
        assert paths == {str(fresh), str(sources / 'existing.pdf')}
    assert client.get('/api/ai/status').json()['config']['enabled'] is False
    assert fresh.read_bytes() == original
    # An unchanged scan does not create duplicate attempts for either paper.
    assert client.post('/api/check-new', json={}).status_code == 200
    assert len(client.get('/api/ai/jobs').json()) == 2
    client.post('/api/ai/resume-all', json={})
    assert client.get('/api/ai/status').json()['config']['enabled'] is True
