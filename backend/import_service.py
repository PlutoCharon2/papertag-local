import json
import logging
import threading
from pathlib import Path
from .database import connect
from .pdf_service import parse_pdf, file_hash
from .archive_service import archive_pdf, archived_pdf, preserve_existing

logger = logging.getLogger(__name__)
lock = threading.Lock()


def import_file(c, path):
    digest = file_hash(path)
    snapshot = archive_pdf(path, digest)
    previous = c.execute('SELECT p.id,p.file_hash FROM files f JOIN papers p ON p.id=f.paper_id WHERE f.path=?', (str(path),)).fetchone()
    changed = bool(previous and previous['file_hash'] != digest)
    old = c.execute('SELECT * FROM papers WHERE file_hash=?', (digest,)).fetchone()
    if old:
        paper_id = old['id']
        c.execute('INSERT INTO files(path,paper_id) VALUES(?,?) ON CONFLICT(path) DO UPDATE SET paper_id=excluded.paper_id', (str(path), paper_id))
        if old['status'] == 'superseded':
            has_run = c.execute('SELECT 1 FROM runs WHERE paper_id=?', (paper_id,)).fetchone()
            has_text = c.execute('SELECT 1 FROM blocks WHERE paper_id=?', (paper_id,)).fetchone()
            c.execute('UPDATE papers SET status=? WHERE id=?', ('needs_review' if has_run else 'awaiting_chat' if has_text else 'needs_ocr', paper_id))
        retire_previous(c, previous, paper_id)
        return 'modified' if changed else 'duplicate', paper_id
    parsed = parse_pdf(snapshot)
    if parsed['title'] == digest:
        parsed['title'] = path.stem
    if parsed['hash'] != digest or file_hash(path) != digest:
        raise ValueError('文件在解析期间被修改，请稍后重试')
    row = c.execute('INSERT INTO papers(title,file_hash,page_count,parse_quality,status,supersedes_id) VALUES(?,?,?,?,?,?)',
                    (parsed['title'], parsed['hash'], parsed['page_count'], parsed['quality'], 'awaiting_chat' if parsed['blocks'] else 'needs_ocr', previous['id'] if changed else None))
    paper_id = row.lastrowid
    c.execute('INSERT INTO files(path,paper_id) VALUES(?,?) ON CONFLICT(path) DO UPDATE SET paper_id=excluded.paper_id', (str(path), paper_id))
    c.executemany('INSERT INTO blocks(id,paper_id,page,text,bbox) VALUES(?,?,?,?,?)',
                  [(b['id'], paper_id, b['page'], b['text'], b['bbox']) for b in parsed['blocks']])
    retire_previous(c, previous, paper_id)
    return 'modified' if changed else 'added', paper_id


def retire_previous(c, previous, paper_id):
    if previous and previous['id'] != paper_id:
        if not c.execute('SELECT 1 FROM files WHERE paper_id=?', (previous['id'],)).fetchone():
            c.execute("UPDATE papers SET status='superseded' WHERE id=?", (previous['id'],))


def run_job(job_id):
    with lock:
        with connect() as c:
            job = c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not job or job['status'] != 'waiting':
                return
            c.execute("UPDATE jobs SET status='running',done=0,added=0,modified=0,duplicates=0,failed=0,errors='[]' WHERE id=?", (job_id,))
        errors = []
        try:
            roots = json.loads(job['paths']) or [job['path']]
            archive_folder = archived_pdf('0' * 64).parent.resolve()
            with connect() as c:
                preservation = preserve_existing(c)
                if preservation['unavailable']:
                    logger.warning('Old original PDF versions unavailable: %s', preservation['unavailable'])
            discovered = set()
            for value in roots:
                path = Path(value)
                if not path.exists():
                    raise ValueError(f'导入路径不可访问：{path}')
                if path.is_file():
                    if not path.resolve().is_relative_to(archive_folder):
                        discovered.add(path.resolve())
                else:
                    discovered.update(p.resolve() for p in path.rglob('*') if p.is_file() and p.suffix.lower() == '.pdf' and not p.resolve().is_relative_to(archive_folder))
            paths = sorted(discovered)
            with connect() as c:
                c.execute('UPDATE jobs SET total=? WHERE id=?', (len(paths), job_id))
            for path in paths:
                with connect() as c:
                    state = c.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()[0]
                    if state == 'paused':
                        return
                    c.execute('UPDATE jobs SET current_file=? WHERE id=?', (str(path), job_id))
                try:
                    with connect() as c:
                        status, paper_id = import_file(c, path.resolve())
                        col = {'added': 'added', 'modified': 'modified', 'duplicate': 'duplicates'}[status]
                        c.execute(f'UPDATE jobs SET done=done+1,{col}={col}+1 WHERE id=?', (job_id,))
                    from .auto_analysis_service import schedule_import
                    schedule_import(paper_id, status)
                except Exception as exc:
                    logger.exception('PDF import failed: %s', path)
                    errors.append({'file': str(path), 'error': str(exc)})
                    with connect() as c:
                        c.execute('UPDATE jobs SET done=done+1,failed=failed+1,errors=? WHERE id=?', (json.dumps(errors, ensure_ascii=False), job_id))
            with connect() as c:
                c.execute("UPDATE jobs SET status='completed',current_file='' WHERE id=?", (job_id,))
        except Exception as exc:
            logger.exception('Import job failed')
            with connect() as c:
                c.execute("UPDATE jobs SET status='failed',errors=? WHERE id=?", (json.dumps([{'error': str(exc)}], ensure_ascii=False), job_id))


def dispatch(job_id):
    threading.Thread(target=run_job, args=(job_id,), daemon=True).start()
