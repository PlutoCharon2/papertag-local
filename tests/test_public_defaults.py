from fastapi.testclient import TestClient
from backend import database
from backend.database import connect
from backend.main import app


def test_clean_profile_has_no_predefined_document_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'library.db')
    with TestClient(app) as client:
        settings = client.get('/api/settings').json()
        assert settings['version'] == '0.7.22'
        assert settings['default_folder'] == ''
        assert not settings['folders']
        assert client.post('/api/update', json={}).status_code == 400
        assert all(not profile['has_key'] for profile in client.get('/api/ai/providers').json()['profiles'].values())
        folder = str(tmp_path / 'chosen-papers')
        with connect() as c:
            c.execute('INSERT INTO folders VALUES(?)', (folder,))
        assert client.get('/api/settings').json()['default_folder'] == folder
