import pytest


@pytest.fixture(autouse=True)
def no_live_models_in_unit_tests(monkeypatch):
    # Tests explicitly replace the transport; no unit test can spend account credits.
    monkeypatch.setenv('LITERATURE_DISABLE_AUTO', '1')
