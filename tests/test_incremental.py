import json
import pymupdf
import pytest
from fastapi.testclient import TestClient
from backend import database, import_service
from backend.database import connect
from backend.main import app


def make_pdf(path, text):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((40, 50), text)
    doc.save(path)
    doc.close()


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'test.db')
    monkeypatch.setattr(import_service, 'dispatch', lambda _: None)
    with TestClient(app) as client:
        yield client, tmp_path


def test_unchanged_file_skips_parser_and_keeps_local_tags(library, monkeypatch):
    _, root = library
    path = root / 'a.pdf'
    make_pdf(path, 'Research paper with a verified claim. This is enough text for extraction.')
    with connect() as c:
        _, pid = import_service.import_file(c, path)
        c.execute('INSERT INTO decisions(paper_id,label_id,decision) VALUES(?,?,?)', (pid, 'must_read', 'manual'))
        c.execute('INSERT INTO runs(paper_id,payload) VALUES(?,?)', (pid, json.dumps({'tags': [], 'claims': [], 'title': 'Stored GPT result'})))
        c.execute("UPDATE papers SET status='needs_review' WHERE id=?", (pid,))
    def forbidden(_):
        raise AssertionError('Unchanged PDF must not be parsed again')
    monkeypatch.setattr(import_service, 'parse_pdf', forbidden)
    with connect() as c:
        assert import_service.import_file(c, path) == ('duplicate', pid)
        assert c.execute('SELECT COUNT(*) FROM runs WHERE paper_id=?', (pid,)).fetchone()[0] == 1
        assert c.execute('SELECT decision FROM decisions WHERE paper_id=?', (pid,)).fetchone()[0] == 'manual'


def test_modified_file_new_version_and_pending_only(library):
    client, root = library
    path = root / 'a.pdf'
    make_pdf(path, 'Original paper version with research findings.')
    with connect() as c:
        _, old = import_service.import_file(c, path)
        c.execute("INSERT INTO decisions VALUES(?,'must_read','manual',CURRENT_TIMESTAMP)", (old,))
    replacement = root / 'replacement.pdf'
    make_pdf(replacement, 'Changed paper version with NEW research findings.')
    path.write_bytes(replacement.read_bytes())
    with connect() as c:
        status, new = import_service.import_file(c, path)
        assert status == 'modified' and new != old
        assert c.execute('SELECT status FROM papers WHERE id=?', (old,)).fetchone()[0] == 'superseded'
        assert c.execute('SELECT supersedes_id FROM papers WHERE id=?', (new,)).fetchone()[0] == old
        assert c.execute('SELECT COUNT(*) FROM decisions WHERE paper_id=?', (old,)).fetchone()[0] == 1
        assert c.execute('SELECT COUNT(*) FROM decisions WHERE paper_id=?', (new,)).fetchone()[0] == 0
    found = client.post('/api/search', json={'pending_only': True}).json()
    assert [p['id'] for p in found] == [new]


def test_multi_pdf_request_and_registered_folder(library, monkeypatch):
    client, root = library
    a, b = root / 'a.pdf', root / 'b.pdf'
    make_pdf(a, 'First paper.')
    make_pdf(b, 'Second paper.')
    # Keep queue synchronous so test execution is deterministic.
    import backend.main as main
    monkeypatch.setattr(main, 'dispatch', import_service.run_job)
    result = client.post('/api/import', json={'paths': [str(a), str(b)]})
    assert result.status_code == 200
    assert len(client.post('/api/search', json={}).json()) == 2
    result = client.post('/api/import', json={'path': str(root)})
    assert result.status_code == 200
    assert str(root) in client.get('/api/settings').json()['folders']
    monkeypatch.setattr(main, 'DEFAULT_FOLDER', str(root))
    assert client.post('/api/update', json={}).status_code == 200
    jobs = client.get('/api/jobs').json()
    assert jobs[0]['added'] == 0 and jobs[0]['modified'] == 0 and jobs[0]['duplicates'] == 2


def test_desktop_picker_bridge(monkeypatch, tmp_path):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'picker.db')
    database.migrate()
    import desktop
    import webview
    class Window:
        def create_file_dialog(self, kind, **kwargs):
            if kind == webview.FileDialog.OPEN:
                assert kwargs['allow_multiple'] is True
                return ('C:/paper1.pdf', 'C:/paper2.pdf')
            if kind == webview.FileDialog.FOLDER:
                return ('D:/papers',)
    bridge = desktop.DesktopAPI()
    bridge._window = Window()
    assert len(bridge.choose_pdfs()) == 2
    assert bridge.choose_folder() == 'D:/papers'
    import webbrowser
    opened = []
    monkeypatch.setattr(webbrowser, 'open', lambda url: opened.append(url))
    assert bridge.open_chatgpt()
    assert opened == ['https://chatgpt.com/']
