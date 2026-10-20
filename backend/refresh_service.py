"""Check registered library sources; never modify source PDF files."""
import logging
import os
import threading
import time
from .database import connect

_stop = threading.Event()
_worker = None
_last_started = 0.0
logger = logging.getLogger(__name__)


def configuration(c):
    values = dict(c.execute("SELECT key,value FROM settings WHERE key LIKE 'refresh_%'"))
    return {'enabled': values.get('refresh_enabled', '1') == '1',
            'interval_minutes': int(values.get('refresh_interval_minutes', '20'))}


def reset_timer():
    global _last_started
    _last_started = time.monotonic()


def check_due(now=None):
    global _last_started
    now = time.monotonic() if now is None else now
    with connect() as c:
        config = configuration(c)
        busy = c.execute("SELECT 1 FROM jobs WHERE status IN ('waiting','running')").fetchone()
    if not config['enabled'] or busy or now - _last_started < config['interval_minutes'] * 60:
        return None
    _last_started = now
    from .main import update_library
    from fastapi import HTTPException
    try:
        return update_library()
    except HTTPException as exc:
        if exc.status_code not in (400, 409):
            raise
        # No registered accessible source, or a manual scan won the race.
        return None


def _loop():
    while not _stop.wait(5):
        try:
            check_due()
        except Exception:
            logger.exception('Library refresh failed')


def start_worker():
    global _worker
    if os.environ.get('LITERATURE_DISABLE_AUTO') == '1':
        return
    if _worker and _worker.is_alive():
        return
    reset_timer()
    _stop.clear()
    _worker = threading.Thread(target=_loop, daemon=True)
    _worker.start()


def stop_worker():
    _stop.set()
    if _worker:
        _worker.join(timeout=5)
