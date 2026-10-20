import json
import sqlite3
import pytest
from backend.publication import view, short_name


@pytest.mark.parametrize('name,abbr,kind,expected', [
    ('Automatica', 'AUTO', 'journal', 'Automatica'),
    ('Systems & Control: Foundations & Applications', 'SCFA', 'book', 'Book'),
    ('AUTOMATICA', 'AUTO', 'journal', 'Automatica'),
    ('Neurocomputing', 'NEUCOM', 'journal', 'Neurocomputing'),
    ('IEEE Transactions on Automatic Control', 'tac', 'journal', 'TAC'),
    ('IEEE Transactions on Industrial Electronics', 'IEEE T. IND. ELECTRON.', 'journal', 'TIE'),
    ('IEEE TRANSACTIONS ON INDUSTRIAL ELECTRONICS, VOL. 71, NO. 7, JULY 2024', '', 'journal', 'TIE'),
    ('Physical Communication', 'phycom', 'journal', 'PHYCOM'),
    ('arXiv preprint arXiv:2010.02479v3', 'ACHA', 'preprint', 'arXiv'),
    ('Some New Journal', '', 'journal', 'Some New Journal'),
])
def test_publication_format(name, abbr, kind, expected):
    assert short_name(name, abbr, kind, verified=True) == expected


def test_ai_priority_and_independent_backfill():
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
    data = {'journal': 'Automatica', 'journal_abbreviation': 'AUTO', 'publication_kind': 'journal'}
    c.execute('INSERT INTO settings VALUES(?,?)', ('paper_journal_ai_1', json.dumps(data)))
    assert view(c, 1)['publication_short'] == 'Automatica'
    assert view(c, 1, {'journal': 'Neurocomputing'})['publication_short'] == 'Neurocomputing'
    c.execute('INSERT INTO settings VALUES(?,?)', ('paper_journal_1', 'Sensors'))
    assert view(c, 1, data)['publication_short'] == 'Sensors'
    assert view(c, 2)['publication_short'] == ''


def test_api_candidate_can_be_used_without_website_verification():
    assert short_name('Physical Communication', 'PC', 'journal') == 'PC'
    assert short_name('IEEE Access', 'IA', 'journal') == 'IEEE Access'


def test_verified_display_has_full_name_tooltip():
    from backend.publication import cache_key
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
    name = 'IEEE Transactions on Automatic Control'
    c.execute('INSERT INTO settings VALUES(?,?)', (cache_key(name), json.dumps({
        'canonical_name': name, 'abbreviation': 'TAC', 'abbreviation_verified': True})))
    result = view(c, 1, {'journal': name, 'journal_abbreviation': 'WRONG'})
    assert result['publication_short'] == 'TAC'
    assert result['publication_label'] == name + '（TAC）'


def test_same_journal_uses_shared_name_and_abbreviation():
    from backend.publication import register, identity
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
    register(c, {'journal': 'IEEE Transactions on Automatic Control', 'journal_abbreviation': 'TAC'})
    register(c, {'journal': 'IEEE TRANSACTIONS ON AUTOMATIC CONTROL', 'journal_abbreviation': 'WRONG'})
    first = view(c, 1, {'journal': 'IEEE Transactions on Automatic Control', 'journal_abbreviation': 'TAC'})
    second = view(c, 2, {'journal': 'IEEE TRANSACTIONS ON AUTOMATIC CONTROL', 'journal_abbreviation': 'WRONG'})
    assert first['publication_label'] == second['publication_label'] == 'IEEE Transactions on Automatic Control（TAC）'
    assert identity('IFAC PapersOnLine') == identity('IFAC-Papers OnLine')
    assert short_name('', '', 'book') == 'Book'


def test_journal_header_and_clean_name_share_one_identity():
    from backend.publication import register, identity, canonical_name
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
    name = 'IEEE Transactions on Industrial Electronics'
    header = 'IEEE TRANSACTIONS ON INDUSTRIAL ELECTRONICS, VOL. 71, NO. 7, JULY 2024'
    register(c, {'journal': header, 'journal_abbreviation': 'IEEE T. IND. ELECTRON.'})
    assert identity(name) == identity(header)
    assert canonical_name(header) == name
    for raw in (name, header):
        result = view(c, 1, {'journal': raw, 'journal_abbreviation': ''})
        assert result['publication_short'] == 'TIE'
        assert result['publication_label'] == name + '（TIE）'
    subtitle = 'IEEE Transactions on Circuits and Systems II: Express Briefs'
    assert canonical_name(subtitle) == subtitle
