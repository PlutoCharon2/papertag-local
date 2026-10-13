import os
from pathlib import Path


class AlreadyRunning(RuntimeError):
    pass


class InstanceLock:
    """One desktop host per database, preventing duplicate account inference queues."""
    def __init__(self, data_folder: Path):
        self.folder = data_folder
        self.handle = None

    def acquire(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.handle = (self.folder / 'desktop.lock').open('a+b')
        if self.handle.seek(0, 2) == 0:
            self.handle.write(b'0')
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            raise AlreadyRunning('文献库已经运行，请使用已有窗口；不会启动重复的 GPT 分析队列')

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None
