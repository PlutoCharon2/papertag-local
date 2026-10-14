import json
import hashlib
import pymupdf
from backend import auto_analysis_service as ai
from backend.database import connect
from test_automatic import library, payload, transport


def test_original_pdf_page_and_invalid_page(library):
    client, pid, paper = library
    original = client.get(f'/api/papers/{pid}/pdf')
    assert original.headers['content-type'] == 'application/pdf'
    assert original.content.startswith(b'%PDF-')
    assert hashlib.sha256(original.content).hexdigest() == paper['file_hash']
    viewer = client.get('/pdfjs/web/viewer.html')
    assert viewer.status_code == 200
    worker = client.get('/pdfjs/build/pdf.worker.mjs')
    assert worker.status_code == 200 and 'javascript' in worker.headers['content-type']
    response = client.get(f'/api/papers/{pid}/page/1')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/png'
    image = pymupdf.Pixmap(response.content)
    assert image.width > 500 and image.height > 500
    assert client.get(f'/api/papers/{pid}/page/0').status_code == 400
    assert client.get(f'/api/papers/{pid}/page/2').status_code == 400
    assert client.get('/api/papers/999/page/1').status_code == 404


def test_journal_from_ai_and_manual_edit_does_not_overwrite_analysis(library, monkeypatch):
    client, pid, paper = library
    data = payload(paper)
    data['journal'] = 'Reader Test Journal'
    calls = transport(monkeypatch, data)
    ai.analyze_one(ai.enqueue(pid))
    assert client.get(f'/api/papers/{pid}').json()['journal'] == 'Reader Test Journal'
    before = client.get(f'/api/papers/{pid}').json()['analysis']
    assert client.post(f'/api/papers/{pid}/journal', json={'journal': 'Correct Journal'}).status_code == 200
    detail = client.get(f'/api/papers/{pid}').json()
    assert detail['journal'] == 'Correct Journal'
    card = next(p for p in client.post('/api/search', json={}).json() if p['id'] == pid)
    assert card['journal'] == 'Correct Journal'
    assert detail['analysis'] == before
    assert len(detail['history']) == 1
    assert calls == [1]


def test_filename_year_and_venue_reused(library):
    from backend.main import paper_view
    from backend.bibliography import filename_metadata
    _, pid, _ = library
    assert filename_metadata(['D:/papers/[2023][Access]Title.pdf']) == {'year': 2023, 'venue': 'ACCESS'}
    assert filename_metadata(['D:/papers/[2023][IEEE]Title.pdf']) == {'year': 2023, 'venue': ''}
    with connect() as c:
        c.execute('INSERT INTO files VALUES(?,?)', ('D:/papers/[2023][Automatic]Title.pdf', pid))
        paper = dict(c.execute('SELECT * FROM papers WHERE id=?', (pid,)).fetchone())
        view = paper_view(c, paper)
        assert view['year'] == 2023
        assert view['publication_short'] == 'AUTOMATIC'
