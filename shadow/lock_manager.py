import fcntl
import os
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

        directory = os.path.dirname(self._lock_file) or "."
        os.makedirs(directory, exist_ok=True)

        self._fd = open(self._lock_file, "a+", encoding="utf-8")
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
