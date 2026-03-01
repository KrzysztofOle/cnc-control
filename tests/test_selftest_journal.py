from __future__ import annotations

import json
import subprocess

from cnc_control.selftest.journal import run_journal_checks


def test_journal_bluetooth_noise_is_warning(monkeypatch) -> None:
    payload = {
        "_SYSTEMD_UNIT": "bluetooth.service",
        "SYSLOG_IDENTIFIER": "bluetoothd",
        "MESSAGE": "adapter init failed",
    }
    output = json.dumps(payload, ensure_ascii=True)

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["journalctl"],
            returncode=0,
            stdout=output,
            stderr="",
        )

    monkeypatch.setattr("cnc_control.selftest.journal.subprocess.run", fake_run)

    result = run_journal_checks()

    assert result.critical == 0
    assert result.warnings == 1
    assert result.system_noise == 1
    assert any(check["status"] == "WARN" for check in result.checks)


def test_journal_cnc_webui_crash_is_critical(monkeypatch) -> None:
    payload = {
        "_SYSTEMD_UNIT": "cnc-webui.service",
        "SYSLOG_IDENTIFIER": "systemd",
        "MESSAGE": "Main process exited, code=exited, status=1/FAILURE",
    }
    output = json.dumps(payload, ensure_ascii=True)

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["journalctl"],
            returncode=0,
            stdout=output,
            stderr="",
        )

    monkeypatch.setattr("cnc_control.selftest.journal.subprocess.run", fake_run)

    result = run_journal_checks()

    assert result.critical == 1
    assert result.warnings == 0
    assert result.system_noise == 0
    assert any(check["status"] == "FAIL" for check in result.checks)

