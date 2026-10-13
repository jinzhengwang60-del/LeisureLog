"""A user-data lock, not a guessed port or process name, identifies an instance."""

import os
from pathlib import Path


class InstanceLock:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.file = (root / "instance.lock").open("a+b")
        self.mutex = None
        self.acquired = False

    def acquire(self):
        try:
            self.file.seek(0)
            if self.file.read(1) == b"":
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self.acquired = True
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            api = ctypes.windll.kernel32
            api.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            api.CreateMutexW.restype = wintypes.HANDLE
            self.mutex = api.CreateMutexW(None, False, "LeisureLogDesktop")
        return True

    def close(self):
        if self.acquired:
            self.file.seek(0)
            if os.name == "nt":
                import ctypes
                import msvcrt
                from ctypes import wintypes

                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                if self.mutex:
                    ctypes.windll.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                    ctypes.windll.kernel32.CloseHandle(self.mutex)
            else:
                import fcntl

                fcntl.flock(self.file, fcntl.LOCK_UN)
        self.file.close()
