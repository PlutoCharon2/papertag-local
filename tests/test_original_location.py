import subprocess
import pytest
from desktop import DesktopAPI
from test_refresh import library,pdf


def test_open_original_location_selects_source_not_archive(library,monkeypatch):
    client,root=library
    source=root/'original source.pdf';pdf(source)
    client.post('/api/import',json={'path':str(source)})
    pid=client.post('/api/search',json={}).json()[0]['id']
    calls=[]
    monkeypatch.setattr(subprocess,'Popen',lambda args: calls.append(args))
    assert DesktopAPI().open_original_location(pid)
    assert calls==[['explorer.exe','/select,',str(source.resolve())]]
    source.unlink()
    with pytest.raises(ValueError,match='原始PDF'):
        DesktopAPI().open_original_location(pid)
    assert len(calls)==1
