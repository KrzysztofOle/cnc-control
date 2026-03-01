from __future__ import annotations

import subprocess


def run_root_command(cmd: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """
    PL: Wykonuje polecenie przez `sudo -n` bez propagowania wyjatkow.
    EN: Executes a command via `sudo -n` without propagating exceptions.
    """
    full_cmd = ["sudo", "-n", *cmd]
    try:
        completed = subprocess.run(
            full_cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return 124, stdout, f"{stderr} timeout"
    except Exception as exc:  # noqa: BLE001
        return 1, "", str(exc)

