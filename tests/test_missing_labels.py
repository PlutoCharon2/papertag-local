import json
from backend import auto_analysis_service as ai
from backend.database import connect
from test_automatic import library


def save_result(pid, data):
    with connect() as c:
        c.execute('INSERT INTO runs(paper_id,payload) VALUES(?,?)', (pid, json.dumps(data)))


def test_existing_topics_and_publication_never_requeued(library):
    _, pid, _ = library
    save_result(pid, {'journal': 'Automatica', 'tags': [{'label_id': 'control', 'evidence': []}]})
    assert ai.enqueue_missing_labels() == {'topics': 0, 'journal': 0}


def test_only_missing_journal_uses_metadata_job_and_preserves_analysis(library, monkeypatch):
    _, pid, _ = library
    save_result(pid, {'tags': [{'label_id': 'control', 'evidence': []}], 'claims': [], 'summary': 'retain'})
    with connect() as c:
        original = c.execute('SELECT payload FROM runs WHERE paper_id=?', (pid,)).fetchone()[0]
    assert ai.enqueue_missing_labels() == {'topics': 0, 'journal': 1}
    assert ai.enqueue_missing_labels() == {'topics': 0, 'journal': 0}
    calls = []
    from backend import journal_service
    def lookup(paper_id, source, cancel=None):
        calls.append(paper_id)
        return {'journal': 'Automatica', 'journal_abbreviation': 'AUTO', 'publication_kind': 'journal',
                'page': 1, 'quote': 'Automatica', 'reason': ''}
    monkeypatch.setattr(journal_service, 'lookup', lookup)
    with connect() as c:
        job = c.execute('SELECT id FROM ai_jobs WHERE paper_id=?', (pid,)).fetchone()[0]
    ai.analyze_one(job)
    assert calls == [pid]
    with connect() as c:
        assert c.execute('SELECT payload FROM runs WHERE paper_id=?', (pid,)).fetchall()[0][0] == original
        assert c.execute('SELECT count(*) FROM runs WHERE paper_id=?', (pid,)).fetchone()[0] == 1
        assert c.execute('SELECT status FROM ai_jobs WHERE id=?', (job,)).fetchone()[0] == 'completed'
    assert ai.enqueue_missing_labels() == {'topics': 0, 'journal': 0}


def test_missing_topics_queues_full_analysis_once(library):
    _, pid, _ = library
    save_result(pid, {'journal': 'Automatica', 'tags': []})
    assert ai.enqueue_missing_labels() == {'topics': 1, 'journal': 0}
    assert ai.enqueue_missing_labels() == {'topics': 0, 'journal': 0}
    with connect() as c:
        row = c.execute('SELECT force FROM ai_jobs WHERE paper_id=?', (pid,)).fetchone()
        assert row[0] == 1


def test_book_and_rejected_tags_are_not_missing(library):
    _, pid, _ = library
    save_result(pid, {'publication_kind': 'book', 'tags': [{'label_id': 'control', 'evidence': []}]})
    with connect() as c:
        c.execute("INSERT INTO decisions(paper_id,label_id,decision) VALUES(?,'control','rejected')", (pid,))
    assert ai.enqueue_missing_labels() == {'topics': 0, 'journal': 0}


def test_paused_task_is_not_resumed_by_update(library):
    _, pid, _ = library
    job = ai.enqueue(pid)
    ai.patch_job(job, status='paused')
    assert ai.enqueue_missing_labels() == {'topics': 0, 'journal': 0}
    with connect() as c:
        assert c.execute('SELECT status FROM ai_jobs WHERE id=?', (job,)).fetchone()[0] == 'paused'
