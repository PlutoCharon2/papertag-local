"""Immutable, content-addressed PDF copies. Never changes a user's source file."""
import hashlib
import os
import uuid
from pathlib import Path
from . import database
from .pdf_service import file_hash


def archived_pdf(digest):
    if len(digest) != 64 or any(ch not in '0123456789abcdef' for ch in digest):
        raise ValueError('无效 PDF 哈希')
    return database.DB_PATH.parent / 'pdf_archive' / (digest + '.pdf')


def archive_pdf(source: Path, digest: str):
    target = archived_pdf(digest)
    if target.is_file():
        if file_hash(target) != digest:
            raise ValueError('本地 PDF 版本副本校验失败，已保留该文件，请检查备份')
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / ('.' + uuid.uuid4().hex + '.tmp')
    h = hashlib.sha256()
    try:
        with source.open('rb') as inp, temporary.open('xb') as out:
            for chunk in iter(lambda: inp.read(1024 * 1024), b''):
                out.write(chunk)
                h.update(chunk)
            out.flush()
            os.fsync(out.fileno())
        if h.hexdigest() != digest:
            raise ValueError('文件在保存版本副本时被修改，请重新更新')
        if target.exists():
            if file_hash(target) != digest:
                raise ValueError('版本副本冲突；保留已有文件')
        else:
            # Atomic creation without replacing an existing version, even across app instances.
            if os.name == 'nt':
                os.rename(temporary, target)
            else:
                os.link(temporary, target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def preserve_existing(c):
    """Best effort for pre-0.4 imports; cannot recover an already overwritten old PDF."""
    saved = 0
    missing = []
    for paper in c.execute('SELECT id,file_hash FROM papers').fetchall():
        target = archived_pdf(paper['file_hash'])
        if target.is_file():
            continue
        success = False
        for row in c.execute('SELECT path FROM files WHERE paper_id=?', (paper['id'],)).fetchall():
            path = Path(row[0])
            if path.is_file() and file_hash(path) == paper['file_hash']:
                archive_pdf(path, paper['file_hash'])
                saved += 1
                success = True
                break
        if not success:
            missing.append(paper['id'])
    return {'saved': saved, 'unavailable': missing}
