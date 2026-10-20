import json
import sqlite3
import pytest
from backend.publication import cache_key, canonical_name, identity, register, short_name, view
from backend.publication_catalog import IEEE_TRANSACTIONS


@pytest.mark.parametrize('title,expected', IEEE_TRANSACTIONS)
@pytest.mark.parametrize('variant', ['full', 'header', 'placeholder_header', 'trans_header'])
def test_ieee_transactions_family_replaces_old_cache(title, expected, variant):
    if variant == 'header':
        raw = '123 ' + title.upper() + ', VOL. 71, NO. 10, OCTOBER 2024'
    elif variant == 'placeholder_header':
        raw = title.upper() + ',VOL. XX, NO. X, 2024'
    elif variant == 'trans_header':
        raw = title.replace('Transactions', 'Trans.') + ', VOL. 71'
    else:
        raw = title
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
    c.execute('INSERT INTO settings VALUES(?,?)', (cache_key(raw), json.dumps({
        'canonical_name': raw, 'abbreviation': 'IEEE TRANS. WRONG'})))
    result = view(c, 1, {'journal': raw, 'journal_abbreviation': ''})
    assert result['journal'] == title
    assert result['publication_short'] == expected
    assert result['publication_label'] == title + '（' + expected + '）'
    register(c, {'journal': raw, 'journal_abbreviation': 'WRONG'})
    cached = json.loads(c.execute('SELECT value FROM settings WHERE key=?', (cache_key(title),)).fetchone()[0])
    assert cached == {'canonical_name': title, 'abbreviation': expected}


def test_historical_and_different_transactions_are_distinct():
    assert identity('IEEE Transactions on Neural Networks') != identity('IEEE Transactions on Neural Networks and Learning Systems')
    assert short_name('IEEE Transactions on Neural Networks') == 'TNN'
    assert short_name('IEEE Transactions on Neural Networks and Learning Systems') == 'TNNLS'
    assert short_name('IEEE Transactions on Control Systems Technology') == 'TCST'
    assert short_name('IEEE Transactions on Circuits and Systems for Video Technology') == 'TCSVT'
    assert short_name('IEEE Transactions on Consumer Electronics', 'TCSE') == 'TCE'


def test_unknown_transactions_does_not_invent_initials():
    assert short_name('IEEE Transactions on An Unlisted Subject') == 'IEEE Transactions on An Unlisted Subject'
    assert short_name('IEEE Access', 'IA') == 'IEEE Access'
    assert short_name('Automatica', 'AUTO') == 'Automatica'


def test_wrong_cached_journal_cannot_replace_identified_ieee_title():
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
    title = 'IEEE Transactions on Circuits and Systems for Video Technology'
    c.execute('INSERT INTO settings VALUES(?,?)', (cache_key(title), json.dumps({
        'canonical_name': 'IEEE Transactions on Control Systems Technology', 'abbreviation': 'TCST'})))
    result = view(c, 1, {'journal': title})
    assert result['publication_short'] == 'TCSVT'
    assert result['journal'] == title
    assert short_name('IEEE TRANSACTIONS ON CIRCUITS AND SYSTEMS—Ⅱ: EXPRESS BRIEFS') == 'TCAS-II'
