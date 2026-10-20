"""Build a shared name catalog from existing AI results; makes no API calls."""
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['LITERATURE_DB'] = sys.argv[1]
from backend import database
from backend.analysis_service import latest
from backend.publication import ai_metadata, cache_key, identity, canonical_name, short_name, view, known

groups = defaultdict(list)
with database.connect() as c:
    old = {}
    for row in c.execute("SELECT value FROM settings WHERE key LIKE 'journal_display_%'").fetchall():
        item = json.loads(row[0])
        name = item.get('input_name', item.get('canonical_name', ''))
        if identity(name) == identity(item.get('canonical_name', '')):
            old[identity(name)] = item
    for row in c.execute('SELECT id FROM papers').fetchall():
        data = ai_metadata(c, row[0], latest(c, row[0]))
        name = data.get('journal', '')
        if known(name) and data.get('publication_kind') not in ('book', 'thesis', 'preprint') and 'arxiv' not in name.casefold():
            groups[identity(name)].append(data)
    catalog = []
    for ident, items in groups.items():
        existing = old.get(ident, {})
        # Website name casing can be reused only when it identifies the same title.
        name = canonical_name(existing.get('canonical_name') or next((a['journal'] for a in items if not a['journal'].isupper()), items[0]['journal']))
        candidates = Counter()
        for item in items:
            candidate = short_name(name, item.get('journal_abbreviation', ''))
            if identity(candidate) != identity(name):
                candidates[candidate] += 1
        compact = Counter({a: count for a, count in candidates.items() if ' ' not in a and '.' not in a})
        previous = existing.get('abbreviation', '')
        abbreviation = (compact.most_common(1)[0][0] if compact else previous if previous and ' ' not in previous and '.' not in previous
                        else candidates.most_common(1)[0][0] if candidates else previous)
        if short_name(name, abbreviation) == name:
            abbreviation = ''
        data = {'canonical_name': name, 'abbreviation': abbreviation}
        c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (cache_key(name), json.dumps(data, ensure_ascii=False)))
        # Keep aliases sharing exactly the same name and abbreviation.
        for item in items:
            c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (cache_key(item['journal']), json.dumps(data, ensure_ascii=False)))
        catalog.append({**data, 'papers': len(items)})
    # Remove obsolete website-check caches; no source URLs or website data are retained.
    for row in c.execute("SELECT key FROM settings WHERE key LIKE 'journal_display_%'").fetchall():
        if not row[0].startswith('journal_display_v2_'):
            c.execute('DELETE FROM settings WHERE key=?', (row[0],))
    counts = Counter()
    examples = []
    for p in c.execute('SELECT id FROM papers').fetchall():
        result = view(c, p[0], latest(c, p[0]))
        counts['Book' if result['publication_short'] == 'Book' else 'unresolved' if not result['publication_short'] else 'identified'] += 1
        if p[0] >= 460:
            examples.append({'id': p[0], 'label': result['publication_label'], 'display': result['publication_short']})
out = ROOT / 'output/journal-review/final-catalog.json'
out.write_text(json.dumps({'counts': dict(counts), 'catalog': catalog, 'examples': examples}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'distinct_publications': len(catalog), 'counts': dict(counts), 'report': str(out)}, ensure_ascii=False))
