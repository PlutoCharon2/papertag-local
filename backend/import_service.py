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
        if old['status'] in ('superseded', 'source_missing'):
            has_run = c.execute('SELECT payload FROM runs WHERE paper_id=? ORDER BY id DESC LIMIT 1', (paper_id,)).fetchone()
            has_text = c.execute('SELECT 1 FROM blocks WHERE paper_id=?', (paper_id,)).fetchone()
            restored = ('partial_result' if json.loads(has_run[0]).get('_partial') else 'needs_review') if has_run else 'awaiting_chat' if has_text else 'needs_ocr'
            c.execute('UPDATE papers SET status=? WHERE id=?', (restored, paper_id))
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
        if c.execute('SELECT is_favorite FROM papers WHERE id=?', (previous['id'],)).fetchone()[0]:
            c.execute('UPDATE papers SET is_favorite=1 WHERE id=?', (paper_id,))
        if not c.execute('SELECT 1 FROM files WHERE paper_id=?', (previous['id'],)).fetchone():
            c.execute("UPDATE papers SET status='superseded' WHERE id=?", (previous['id'],))


def reconcile_deleted_sources(c):
    """Remove absent paths only after confirming their directory is accessible."""
    roots = [Path(r[0]) for r in c.execute('SELECT path FROM folders')]
    removed = set()
    for row in c.execute('SELECT path,paper_id FROM files').fetchall():
        path = Path(row['path'])
        try:
            path.stat()
            continue
        except FileNotFoundError:
            pass
        except OSError:
            continue
        candidates = [path.parent] + [p for p in roots if path.is_relative_to(p)]
        accessible = False
        for parent in candidates:
            try:
                # Enumerating distinguishes a readable source from an offline drive.
                list(parent.iterdir())
                accessible = True
                break
            except OSError:
                continue
        if not accessible:
            continue
        c.execute('DELETE FROM files WHERE path=?', (row['path'],))
        if not c.execute('SELECT 1 FROM files WHERE paper_id=?', (row['paper_id'],)).fetchone():
            c.execute("UPDATE papers SET status='source_missing' WHERE id=?", (row['paper_id'],))
            c.execute("UPDATE ai_jobs SET status='paused',stage='本地源文件已删除，已从文献库列表移除' WHERE paper_id=? AND status IN ('running','queued','waiting_login')", (row['paper_id'],))
            removed.add(row['paper_id'])
    return len(removed)


def run_job(job_id):
    with lock:
        with connect() as c:
            job = c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not job or job['status'] != 'waiting':
                return
            analyze_new = c.execute('SELECT value FROM settings WHERE key=?', (f'import_analyze_new_{job_id}',)).fetchone()
            analyze_new = bool(analyze_new and analyze_new[0] == '1')
            reconcile_missing = c.execute('SELECT value FROM settings WHERE key=?', (f'import_reconcile_missing_{job_id}',)).fetchone()
            reconcile_missing = bool(reconcile_missing and reconcile_missing[0] == '1')
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
                    if reconcile_missing and path.suffix.lower() == '.pdf' and path.parent.is_dir():
                        continue
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
                    from .auto_analysis_service import schedule_import, enqueue
                    if analyze_new and status == 'added':
                        enqueue(paper_id)
                    else:
                        schedule_import(paper_id, status)
                except Exception as exc:
                    logger.exception('PDF import failed: %s', path)
                    errors.append({'file': str(path), 'error': str(exc)})
                    with connect() as c:
                        c.execute('UPDATE jobs SET done=done+1,failed=failed+1,errors=? WHERE id=?', (json.dumps(errors, ensure_ascii=False), job_id))
            if reconcile_missing:
                with connect() as c:
                    removed = reconcile_deleted_sources(c)
                    c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (f'import_removed_{job_id}', str(removed)))
            if analyze_new:
                from .auto_analysis_service import enqueue_unattempted
                enqueue_unattempted()
            if reconcile_missing:
                from .auto_analysis_service import enqueue_missing_labels
                filled = enqueue_missing_labels()
                with connect() as c:
                    c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',
                              (f'import_fill_labels_{job_id}', json.dumps(filled)))
            with connect() as c:
                c.execute("UPDATE jobs SET status='completed',current_file='' WHERE id=?", (job_id,))
        except Exception as exc:
            logger.exception('Import job failed')
            with connect() as c:
                c.execute("UPDATE jobs SET status='failed',errors=? WHERE id=?", (json.dumps([{'error': str(exc)}], ensure_ascii=False), job_id))


def dispatch(job_id):
    threading.Thread(target=run_job, args=(job_id,), daemon=True).start()
