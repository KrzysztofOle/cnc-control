import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Mapping


class RebuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class RebuildConfig:
    master_dir: str
    slot_size_mb: int
    tmp_suffix: str


class RebuildEngine:
    def __init__(self, config: RebuildConfig) -> None:
        self._config = config

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "RebuildEngine":
        config = RebuildConfig(
            master_dir=environment.get("CNC_MASTER_DIR", "/var/lib/cnc-control/master"),
            slot_size_mb=int(environment.get("CNC_SHADOW_SLOT_SIZE_MB", "256")),
            tmp_suffix=environment.get("CNC_SHADOW_TMP_SUFFIX", ".tmp"),
        )
        return cls(config=config)

    def full_rebuild(self, rebuild_slot_path: str) -> None:
        if not os.path.isdir(self._config.master_dir):
            raise RebuildError("Katalog CNC_MASTER_DIR nie istnieje.")

        tmp_path = f"{rebuild_slot_path}{self._config.tmp_suffix}"
        self._cleanup_tmp(tmp_path)

        try:
            self._run_command(
                [self._resolve_binary("truncate"), "-s", f"{self._config.slot_size_mb}M", tmp_path],
                "Nie udalo sie utworzyc obrazu tymczasowego.",
            )
            self._run_command(
                [self._resolve_binary("mkfs.vfat"), "-F", "32", tmp_path],
                "Nie udalo sie sformatowac obrazu FAT.",
            )
            if self._master_has_content():
                self._run_command(
                    [
                        self._resolve_binary("mcopy"),
                        "-s",
                        "-i",
                        tmp_path,
                        f"{self._config.master_dir}/",
                        "::",
                    ],
                    "Nie udalo sie skopiowac danych do obrazu FAT.",
                )

            self._fsync_path(tmp_path)
            self._fsync_path(os.path.dirname(tmp_path) or ".")
            os.replace(tmp_path, rebuild_slot_path)
        except Exception as exc:
            self._cleanup_tmp(tmp_path)
            if isinstance(exc, RebuildError):
                raise
            raise RebuildError(str(exc)) from exc

    def dry_run_diff(self, target_dir: str) -> bool:
        result = subprocess.run(
            [
                "rsync",
                "-a",
                "--delete",
                "--dry-run",
                "--itemize-changes",
                f"{self._config.master_dir}/",
                f"{target_dir}/",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RebuildError("Nie udalo sie wykonac porownania dry-run rsync.")
        return bool(result.stdout.strip())

    @staticmethod
    def _run_command(command, error_message: str) -> None:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "Brak szczegolow"
            raise RebuildError(f"{error_message} ({detail})")

    def _master_has_content(self) -> bool:
        for _ in os.scandir(self._config.master_dir):
            return True
        return False

    @staticmethod
    def _fsync_path(path: str) -> None:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _cleanup_tmp(tmp_path: str) -> None:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            return

    @staticmethod
    def _resolve_binary(binary_name: str) -> str:
        resolved = shutil.which(binary_name)
        if resolved:
            return resolved
        for prefix in ("/usr/sbin", "/sbin", "/usr/bin", "/bin"):
            candidate = os.path.join(prefix, binary_name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return binary_name

    @property
    def master_dir(self) -> str:
        return self._config.master_dir
