import pytest
from backend.instance_lock import InstanceLock, AlreadyRunning


def test_only_one_desktop_per_database_and_lock_released(tmp_path):
    first, second = InstanceLock(tmp_path), InstanceLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(AlreadyRunning):
            second.acquire()
    finally:
        first.close()
    second.acquire()
    second.close()
