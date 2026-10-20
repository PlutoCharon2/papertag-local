import json
import pytest
import pymupdf
from backend import auto_analysis_service as ai, contents_service
from backend.database import connect
from backend.bibliography import display_title
from test_refresh import library, pdf


@pytest.mark.parametrize('status', ['failed','paused','interrupted','completed','partial','cached','queued','waiting_login','running'])
def test_update_fills_missing_labels_but_respects_paused_or_active_jobs(library, status):
    client, root = library
    source = root / 'papers'
    source.mkdir()
    pdf(source / 'paper.pdf')
    client.post('/api/import', json={'path': str(source)})
    with connect() as c:
        pid = c.execute('SELECT id FROM papers').fetchone()[0]
        c.execute('INSERT INTO ai_jobs(paper_id,status) VALUES(?,?)', (pid,status))
    assert client.post('/api/check-new', json={}).status_code == 200
    assert client.post('/api/ai/pending', json={}).json() == {'queued': 0}
    assert ai.enqueue(pid, unattempted_only=True) is None
    with connect() as c:
        expected = 1 if status in ('paused', 'queued', 'waiting_login', 'running') else 2
        assert c.execute('SELECT COUNT(*) FROM ai_jobs').fetchone()[0] == expected
        assert c.execute('SELECT status FROM ai_jobs ORDER BY id LIMIT 1').fetchone()[0] == status


def test_deleted_sources_hide_item_tags_and_jobs_but_keep_other_paths(library):
    client, root = library
    source = root / 'papers'
    source.mkdir()
    first,second=source/'[2026][AUTO]Test title.pdf',source/'copy.pdf'
    pdf(first)
    original=first.read_bytes()
    second.write_bytes(original)
    client.post('/api/import',json={'path':str(source)})
    item=client.post('/api/search',json={}).json()[0]
    pid=item['id']
    assert item['display_title']=='Test title'
    client.post(f'/api/papers/{pid}/decision',json={'label_id':'control','decision':'manual'})
    with connect() as c:
        c.execute("INSERT INTO ai_jobs(paper_id,status) VALUES(?,'queued')",(pid,))
    first.unlink()
    client.post('/api/check-new',json={})
    assert len(client.post('/api/search',json={}).json())==1
    second.unlink()
    client.post('/api/check-new',json={})
    assert client.post('/api/search',json={}).json()==[]
    assert client.post('/api/search',json={'show_versions':True}).json()==[]
    assert client.get('/api/ai/jobs').json()==[]
    assert client.get('/api/ai/queue').json()=={}
    assert next(l for l in client.get('/api/ontology').json()['labels'] if l['id']=='control')['paper_count']==0
    assert client.get('/api/jobs').json()[0]['removed']==1
    client.post('/api/ai/resume-all',json={})
    with connect() as c:
        assert c.execute('SELECT status FROM ai_jobs').fetchone()[0]=='paused'
    # Reappearing same content restores saved metadata and manual decisions.
    first.write_bytes(original)
    client.post('/api/check-new',json={})
    restored=client.post('/api/search',json={}).json()[0]
    assert restored['id']==pid and any(t['label_id']=='control' for t in restored['tags'])


def test_missing_standalone_pdf_is_removed_without_importing_other_files(library):
    client,root=library
    path=root/'single.pdf'
    pdf(path)
    client.post('/api/import',json={'path':str(path)})
    path.unlink()
    pdf(root/'unselected.pdf')
    assert client.post('/api/check-new',json={}).status_code==200
    assert client.post('/api/search',json={}).json()==[]


def test_offline_root_does_not_remove_existing_library_records(library):
    client,root=library
    source=root/'offline';source.mkdir();pdf(source/'paper.pdf')
    other=root/'accessible';other.mkdir()
    client.post('/api/import',json={'path':str(source)})
    client.post('/api/import',json={'path':str(other)})
    target=root/'temporarily-unmounted'
    assert source.resolve().is_relative_to(root.resolve()) and target.resolve().is_relative_to(root.resolve())
    source.rename(target)
    assert client.post('/api/check-new',json={}).status_code==200
    assert len(client.post('/api/search',json={}).json())==1


def test_titles_only_strip_matching_filename_metadata():
    path=r'C:\papers\[2026][AUTO]Input-to-state stabilization.pdf'
    assert display_title('[2026][AUTO]Input-to-state stabilization',[path])=='Input-to-state stabilization'
    assert display_title('AI extracted full title',[path])=='AI extracted full title'
    assert display_title('[H-infinity] Control',[r'C:\papers\[H-infinity] Control.pdf'])=='[H-infinity] Control'


def test_locator_cache_changes_with_configured_page_range(tmp_path):
    calls=[]
    class Transport:
        @staticmethod
        def infer(folder,images,*args):
            calls.append(len(images))
            raw=json.dumps({'pages':[1],'reason':'Contents'})
            (folder/'response.json').write_text(raw,encoding='utf-8')
            return raw
    with pymupdf.open() as doc:
        for _ in range(45): doc.new_page()
        for limit in [10,10,40]:
            assert contents_service.locate(doc,tmp_path,Transport,60,'',lambda:False,lambda:None,max_pages=limit)==[1]
    assert calls==[10,40]
