import os
import select
import subprocess
from typing import Mapping, Optional


class WatcherService:
    def __init__(self, watched_dir: str) -> None:
        self._watched_dir = watched_dir
        self._process = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "WatcherService":
        watched_dir = environment.get("CNC_MASTER_DIR", "/var/lib/cnc-control/master")
        return cls(watched_dir=watched_dir)

    def start(self) -> None:
        if self._process is not None:
            return
        os.makedirs(self._watched_dir, exist_ok=True)
        self._process = subprocess.Popen(
            [
                "inotifywait",
                "-m",
                "-r",
                "-e",
                "close_write,create,delete,move",
                "--format",
                "%w%f:%e",
                self._watched_dir,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def stop(self) -> None:
        if self._process is None:
            return
        self._process.terminate()
        self._process.wait(timeout=2)
        self._process = None

    def poll_event(self, timeout_seconds: float = 0.0) -> Optional[str]:
        if self._process is None or self._process.stdout is None:
            return None

        ready, _, _ = select.select([self._process.stdout], [], [], timeout_seconds)
        if not ready:
            return None

        line = self._process.stdout.readline()
        if not line:
            return None
        return line.strip()

    @property
    def watched_dir(self) -> str:
        return self._watched_dir
