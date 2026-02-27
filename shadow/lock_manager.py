import fcntl
import os
import tempfile
from contextlib import contextmanager
from typing import Iterator, Mapping


class LockManager:
    def __init__(self, lock_file: str) -> None:
        self._lock_file = lock_file
        self._fd = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "LockManager":
        lock_file = environment.get("CNC_SHADOW_LOCK_FILE", "/var/run/cnc-shadow.lock")
        return cls(lock_file=lock_file)

    def acquire(self, blocking: bool = False) -> bool:
        if self._fd is not None:
            return True

        lock_path = self._lock_file
        try:
            self._fd = self._open_lock_file(lock_path)
        except PermissionError:
            fallback_path = os.path.join(
                tempfile.gettempdir(),
                os.path.basename(self._lock_file) or "cnc-shadow.lock",
            )
            self._fd = self._open_lock_file(fallback_path)
            self._lock_file = fallback_path
        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB

        try:
            fcntl.flock(self._fd.fileno(), flags)
            return True
        except BlockingIOError:
            self._fd.close()
            self._fd = None
            return False

    @staticmethod
    def _open_lock_file(path: str):
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        return open(path, "a+", encoding="utf-8")

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
        finally:
            self._fd.close()
            self._fd = None

    @contextmanager
    def hold(self, blocking: bool = False) -> Iterator[bool]:
        acquired = self.acquire(blocking=blocking)
        try:
            yield acquired
        finally:
            if acquired:
                self.release()

    @property
    def path(self) -> str:
        return self._lock_file
