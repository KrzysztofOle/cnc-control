import os
import subprocess
import time
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class UsbTimeouts:
    stop_timeout: int
    start_timeout: int


class UsbManager:
    def __init__(self, timeouts: UsbTimeouts) -> None:
        self._timeouts = timeouts

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "UsbManager":
        stop_timeout = int(environment.get("CNC_SHADOW_USB_STOP_TIMEOUT", "10"))
        start_timeout = int(environment.get("CNC_SHADOW_USB_START_TIMEOUT", "10"))
        return cls(timeouts=UsbTimeouts(stop_timeout=stop_timeout, start_timeout=start_timeout))

    def stop_export(self) -> bool:
        result = self._run_root_command(["modprobe", "-r", "g_mass_storage"])
        if result.returncode != 0:
            return False
        return self._wait_for_module_state(expect_loaded=False, timeout_seconds=self._timeouts.stop_timeout)

    def start_export(self, active_slot_path: str) -> bool:
        if not active_slot_path:
            return False
        result = self._run_root_command(
            ["modprobe", "g_mass_storage", f"file={active_slot_path}", "ro=1"]
        )
        if result.returncode != 0:
            return False
        return self._wait_for_module_state(expect_loaded=True, timeout_seconds=self._timeouts.start_timeout)

    def _wait_for_module_state(self, expect_loaded: bool, timeout_seconds: int) -> bool:
        deadline = time.monotonic() + max(timeout_seconds, 0)
        while time.monotonic() <= deadline:
            if self._is_mass_storage_loaded() == expect_loaded:
                return True
            time.sleep(0.1)
        return self._is_mass_storage_loaded() == expect_loaded

    @staticmethod
    def _is_mass_storage_loaded() -> bool:
        result = subprocess.run(
            ["lsmod"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        for line in result.stdout.splitlines():
            if line.split() and line.split()[0] == "g_mass_storage":
                return True
        return False

    @staticmethod
    def _run_root_command(command):
        effective_command = list(command)
        if os.geteuid() != 0:
            effective_command = ["sudo", "-n", *effective_command]
        return subprocess.run(
            effective_command,
            capture_output=True,
            text=True,
            check=False,
        )
