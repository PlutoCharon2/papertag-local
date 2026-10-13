import os
import sqlite3
import sys
from pathlib import Path
from contextlib import contextmanager
from .ontology import SEEDS

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
DATA_ROOT = Path(os.environ.get('LITERATURE_DATA', str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ResearchLiteratureLibrary' / 'data' if getattr(sys, 'frozen', False) else ROOT / 'data')))
DB_PATH = Path(os.environ.get('LITERATURE_DB', str(DATA_ROOT / 'literature.db')))


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def migrate():
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY)')
        if not c.execute('SELECT 1 FROM migrations WHERE version=1').fetchone():
            c.executescript('''
                CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO settings VALUES ('ontology_version','1');
                CREATE TABLE labels(id TEXT PRIMARY KEY, dimension TEXT NOT NULL, name TEXT NOT NULL,
                    definition TEXT NOT NULL, parent_id TEXT REFERENCES labels(id), synonyms TEXT NOT NULL DEFAULT '[]', active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE papers(id INTEGER PRIMARY KEY, title TEXT NOT NULL, file_hash TEXT UNIQUE NOT NULL,
                    page_count INTEGER NOT NULL, parse_quality TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE files(path TEXT PRIMARY KEY, paper_id INTEGER NOT NULL REFERENCES papers(id));
                CREATE TABLE blocks(id TEXT NOT NULL, paper_id INTEGER NOT NULL REFERENCES papers(id),
                    page INTEGER NOT NULL, text TEXT NOT NULL, bbox TEXT NOT NULL, PRIMARY KEY(paper_id,id));
                CREATE TABLE runs(id INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL REFERENCES papers(id),
                    payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE decisions(paper_id INTEGER NOT NULL REFERENCES papers(id), label_id TEXT NOT NULL REFERENCES labels(id),
                    decision TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(paper_id,label_id));
                CREATE TABLE jobs(id INTEGER PRIMARY KEY, path TEXT NOT NULL, status TEXT NOT NULL,
                    total INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0, added INTEGER NOT NULL DEFAULT 0,
                    duplicates INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
                    current_file TEXT NOT NULL DEFAULT '', errors TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE INDEX blocks_paper ON blocks(paper_id);
                CREATE INDEX runs_paper ON runs(paper_id,id);
                INSERT INTO migrations VALUES(1);
            ''')
            for dim, rows in SEEDS.items():
                for label_id, name, definition in rows:
                    parent = 'control' if label_id in ('extremum_seeking', 'adaptive_control', 'event_control') else None
                    c.execute('INSERT INTO labels(id,dimension,name,definition,parent_id) VALUES(?,?,?,?,?)',
                              (label_id, dim, name, definition, parent))
        if not c.execute('SELECT 1 FROM migrations WHERE version=2').fetchone():
            c.executescript('''
                CREATE TABLE folders(path TEXT PRIMARY KEY);
                ALTER TABLE jobs ADD COLUMN paths TEXT NOT NULL DEFAULT '[]';
                ALTER TABLE jobs ADD COLUMN modified INTEGER NOT NULL DEFAULT 0;
                ALTER TABLE papers ADD COLUMN supersedes_id INTEGER REFERENCES papers(id);
                INSERT INTO migrations VALUES(2);
            ''')
        if not c.execute('SELECT 1 FROM migrations WHERE version=3').fetchone():
            c.executescript('''
                CREATE TABLE ai_jobs(id INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL REFERENCES papers(id),
                    status TEXT NOT NULL DEFAULT 'queued', stage TEXT NOT NULL DEFAULT '等待 GPT',
                    error TEXT NOT NULL DEFAULT '', force INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                    page_count INTEGER NOT NULL DEFAULT 0, rendered INTEGER NOT NULL DEFAULT 0,
                    run_id INTEGER REFERENCES runs(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT);
                CREATE UNIQUE INDEX ai_one_active ON ai_jobs(paper_id) WHERE status IN ('queued','waiting_login','running');
                INSERT OR IGNORE INTO settings VALUES('ai_enabled','1');
                INSERT OR IGNORE INTO settings VALUES('ai_max_pages','32');
                INSERT OR IGNORE INTO settings VALUES('ai_timeout','1200');
                INSERT OR IGNORE INTO settings VALUES('ai_model','');
                INSERT INTO migrations VALUES(3);
            ''')
        if not c.execute('SELECT 1 FROM migrations WHERE version=4').fetchone():
            c.execute("INSERT OR IGNORE INTO settings VALUES('ai_provider','qwen')")
            c.execute('INSERT INTO migrations VALUES(4)')


def labels(c):
    return [dict(r) for r in c.execute('SELECT * FROM labels ORDER BY dimension,name')]


def ontology_version(c):
    return int(c.execute("SELECT value FROM settings WHERE key='ontology_version'").fetchone()[0])
