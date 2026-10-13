import hashlib
import json
import pymupdf as fitz
from pathlib import Path

PARSER_VERSION = 'pymupdf-blocks-v1'


def file_hash(path: Path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def parse_pdf(path: Path):
    digest = file_hash(path)
    blocks = []
    low_pages = []
    with fitz.open(str(path)) as doc:
        if doc.needs_pass:
            raise ValueError('PDF 有密码，暂不支持解密导入')
        if not len(doc):
            raise ValueError('PDF 没有页面')
        title = (doc.metadata.get('title') or '').strip()
        if not title or len(title) < 5 or title.lower().startswith(('untitled', 'microsoft')):
            title = path.stem
        count = len(doc)
        for p, page in enumerate(doc, 1):
            page_chars = 0
            for n, block in enumerate(page.get_text('blocks', sort=True), 1):
                if block[6] != 0 or not block[4].strip():
                    continue
                text = block[4].strip()
                page_chars += len(text)
                blocks.append({'id': f'p{p}_b{n}', 'page': p, 'text': text, 'bbox': json.dumps(list(block[:4]))})
            if page_chars < 80:
                low_pages.append(p)
    return {'hash': digest, 'title': title, 'page_count': count, 'blocks': blocks,
            'quality': 'needs_review' if low_pages else 'text_extracted', 'low_pages': low_pages}
