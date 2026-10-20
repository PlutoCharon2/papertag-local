"""One shared AI-derived display name per publication, independent of filenames."""
import hashlib
import json
import re
import unicodedata
from .publication_catalog import IEEE_TRANSACTIONS

EMPTY = {'', 'unknown', 'none', 'null', 'n/a', '未知', '未确定'}
NAMES = {
    'automatica': 'Automatica', 'neurocomputing': 'Neurocomputing',
    'energies': 'Energies', 'sensors': 'Sensors', 'entropy': 'Entropy',
    'nature': 'Nature', 'science': 'Science', 'plos': 'PLOS',
    'ieeeaccess': 'IEEE Access', 'sciencechina': 'SCIENCE CHINA',
    'sciencechinainformationsciences': 'SCIENCE CHINA Information Sciences',
    'sciencechinatechnologicalsciences': 'SCIENCE CHINA Technological Sciences',
    'ifacpapersonline': 'IFAC-PapersOnLine',
    'ieeecaajournalofautomaticsinica': 'IEEE/CAA Journal of Automatica Sinica',
    'ieeecaajournalofautomaticasinica': 'IEEE/CAA Journal of Automatica Sinica',
    'ieeetransactionsonindustrialelectronics': 'IEEE Transactions on Industrial Electronics',
}
PREFERRED = {}
for _title, _abbreviation in IEEE_TRANSACTIONS:
    _key = re.sub(r'[^\w]', '', _title.casefold()).replace('_', '')
    NAMES[_key] = _title
    PREFERRED[_key] = _abbreviation


def known(value):
    return isinstance(value, str) and value.strip().casefold() not in EMPTY


def clean_name(name):
    name = re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', name or '')).strip()
    name = re.sub(r'^\d{1,6}\s+(?=IEEE(?:\s|/))', '', name, flags=re.I)
    name = re.sub(r'\bTrans\.(?=\s+on\b)', 'Transactions', name, flags=re.I)
    # Page headers contain the journal title followed by volume/issue/page data.
    # Do not remove meaningful journal subtitles such as "Part I" or "Systems".
    suffix = r'(?:\s*[,;]\s*|\s+)(?:VOL(?:UME)?\.?|NO\.|NUMBER|ISSUE|PP\.|PAGES)\s*(?:\d|[IVXLC]+\b).*$'
    return re.sub(suffix, '', name, flags=re.I).strip(' ,;')


def identity(name):
    name = clean_name(name).casefold().replace('&', 'and')
    return re.sub(r'[^\w]', '', name, flags=re.UNICODE).replace('_', '')


def canonical_name(name):
    name = clean_name(name)
    return NAMES.get(identity(name), name)


def short_name(journal, abbreviation='', kind='unknown', verified=False):
    name = canonical_name(journal)
    if kind == 'book':
        return 'Book'
    if kind == 'preprint' or re.search(r'\barxiv\b', name, re.I):
        return 'arXiv'
    if not known(name):
        return abbreviation.strip().upper() if known(abbreviation) else ''
    if len(name.split()) == 1 or identity(name) in ('ieeeaccess', 'sciencechina'):
        return name
    if identity(name) in PREFERRED:
        return PREFERRED[identity(name)]
    if known(abbreviation) and identity(abbreviation) != identity(name):
        candidate = abbreviation.strip().upper()
        return re.sub(r'^IEEE(?:/CAA|/ASME)?\s+([A-Z][A-Z0-9/-]{1,20})$', r'\1', candidate)
    return name


def cache_key(journal):
    return 'journal_display_v2_' + hashlib.sha256(identity(journal).encode()).hexdigest()


def ai_metadata(c, paper_id, analysis=None):
    analysis = analysis or {}
    if known(analysis.get('journal')) or known(analysis.get('journal_abbreviation')) or analysis.get('publication_kind') == 'book':
        return analysis
    row = c.execute('SELECT value FROM settings WHERE key=?', (f'paper_journal_ai_{paper_id}',)).fetchone()
    return json.loads(row[0]) if row else {}


def register(c, metadata):
    name = canonical_name(metadata.get('journal', ''))
    if not known(name) or metadata.get('publication_kind') in ('book', 'thesis', 'preprint') or 'arxiv' in name.casefold():
        return
    key = cache_key(name)
    row = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    data = json.loads(row[0]) if row else {'canonical_name': name, 'abbreviation': ''}
    candidate = short_name(name, metadata.get('journal_abbreviation', ''))
    if (identity(name) in PREFERRED or not data.get('abbreviation')) and identity(candidate) != identity(name):
        data['abbreviation'] = candidate
    if identity(name) in PREFERRED:
        data['canonical_name'] = name
    c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, json.dumps(data, ensure_ascii=False)))


def view(c, paper_id, analysis=None):
    metadata = ai_metadata(c, paper_id, analysis)
    manual = c.execute('SELECT value FROM settings WHERE key=?', (f'paper_journal_{paper_id}',)).fetchone()
    name = manual[0].strip() if manual else metadata.get('journal', '').strip()
    kind = 'unknown' if manual else metadata.get('publication_kind', 'unknown')
    row = c.execute('SELECT value FROM settings WHERE key=?', (cache_key(name),)).fetchone() if name else None
    shared = json.loads(row[0]) if row else {}
    identified = canonical_name(name)
    canonical = identified if identity(identified) in PREFERRED else canonical_name(shared.get('canonical_name') or name)
    abbreviation = shared.get('abbreviation', '') if row else ('' if manual else metadata.get('journal_abbreviation', ''))
    short = short_name(canonical, abbreviation, kind)
    label = 'Book' if kind == 'book' else f'{canonical}（{short}）' if short and short.casefold() != canonical.casefold() else canonical
    return {'journal': canonical, 'publication_short': short, 'publication_label': label,
            'publication_kind': kind, 'publication_source': 'manual' if manual else ('ai' if metadata else 'unknown')}
