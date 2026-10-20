"""Fill missing publication metadata via the user's existing vision API pool."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', required=True)
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    os.environ['LITERATURE_DB'] = str(Path(args.database).resolve())
    from backend import database, api_service, journal_service
    from backend.analysis_service import latest
    from backend.publication import ai_metadata, known, short_name
    from backend.archive_service import archived_pdf
    out = ROOT / 'output' / 'journal-review'
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = out / f'before-journals-{stamp}.db'
    report = out / f'backfill-{stamp}.json'

    def signature(c):
        h = hashlib.sha256()
        for table in ('papers', 'runs', 'decisions', 'labels', 'files', 'ai_jobs'):
            for row in c.execute('SELECT * FROM ' + table + ' ORDER BY rowid'):
                h.update(repr(tuple(row)).encode())
        return h.hexdigest()

    with database.connect() as c:
        with sqlite3.connect(backup) as b:
            c.backup(b)
        before = signature(c)
        pool = api_service.pool_status(c)
        workers = api_service.parallelism(c)
        if api_service.selected(c) == 'codex' or not workers:
            raise ValueError('需要配置可用的图片 API 密钥')
        busy = c.execute("SELECT count(*) FROM ai_jobs WHERE status IN ('running','queued','waiting','waiting_login')").fetchone()[0]
        if busy:
            raise ValueError('正文分析队列正在使用 API；请等待其结束')
        tasks = []
        skipped = 0
        attempted = 0
        for p in c.execute('SELECT * FROM papers ORDER BY id').fetchall():
            metadata = ai_metadata(c, p['id'], latest(c, p['id']))
            if known(metadata.get('journal')) or known(metadata.get('journal_abbreviation')):
                skipped += 1
                continue
            if c.execute('SELECT 1 FROM settings WHERE key=?', (f"paper_journal_ai_{p['id']}",)).fetchone():
                attempted += 1
                continue
            source = archived_pdf(p['file_hash'])
            if not source.is_file():
                source = next((Path(r[0]) for r in c.execute('SELECT path FROM files WHERE paper_id=?', (p['id'],)) if Path(r[0]).is_file()), None)
            tasks.append((dict(p), source))
    if args.limit:
        tasks = tasks[:args.limit]
    summary = {'database': str(database.DB_PATH), 'backup': str(backup), 'workers': workers,
               'skipped_existing_ai': skipped, 'skipped_previous_attempts': attempted,
               'requested': len(tasks), 'results': []}
    print(json.dumps({k: v for k, v in summary.items() if k != 'results'}, ensure_ascii=False), flush=True)

    def analyze(task):
        p, source = task
        result = {'paper_id': p['id'], 'title': p['title']}
        if source is None:
            return {**result, 'status': 'failed', 'error': '没有可读取的PDF'}
        for attempt in range(3):
            try:
                api_service.bind_for_job()
                data = journal_service.lookup(p['id'], source)
                data['checked_at'] = datetime.now().isoformat()
                data['source'] = 'pdf_pages_1_2'
                data['file_hash'] = p['file_hash']
                with database.connect() as c:
                    # A concurrent completed analysis takes priority; never overwrite it.
                    existing = ai_metadata(c, p['id'], latest(c, p['id']))
                    if known(existing.get('journal')) or known(existing.get('journal_abbreviation')):
                        return {**result, 'status': 'skipped_concurrent'}
                    c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',
                              (f"paper_journal_ai_{p['id']}", json.dumps(data, ensure_ascii=False)))
                    from backend.publication import register
                    register(c, data)
                return {**result, 'status': 'identified' if known(data['journal']) else 'undetermined',
                        **data, 'display': short_name(data['journal'], data['journal_abbreviation'], data['publication_kind'])}
            except Exception as exc:
                # Never log provider bodies or credentials.
                error = type(exc).__name__
            finally:
                api_service.release_binding()
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
        return {**result, 'status': 'failed', 'error': error}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for future in as_completed([executor.submit(analyze, task) for task in tasks]):
            item = future.result()
            summary['results'].append(item)
            report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'done': len(summary['results']), 'total': len(tasks), 'paper_id': item['paper_id'],
                              'status': item['status'], 'journal': item.get('journal', '')}, ensure_ascii=False), flush=True)
    with database.connect() as c:
        summary['analysis_tags_files_jobs_unchanged'] = signature(c) == before
    summary['counts'] = {s: sum(r['status'] == s for r in summary['results'])
                         for s in ('identified', 'undetermined', 'failed', 'skipped_concurrent')}
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(report), 'counts': summary['counts'],
                      'analysis_tags_files_jobs_unchanged': summary['analysis_tags_files_jobs_unchanged']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
