from __future__ import annotations

from cnc_control.selftest.core import run_selftest
from cnc_control.selftest.journal import JournalCheckResult
from cnc_control.selftest.result import SelfTestResult
from cnc_control.selftest.shadow_checks import ShadowChecksResult


def test_result_status_depends_only_on_critical() -> None:
    result = SelfTestResult(critical=0, warnings=5, system_noise=5)
    assert result.status == "OK"

    result.merge_counts(critical=1)
    assert result.status == "FAILED"


def test_twenty_noise_entries_do_not_fail(monkeypatch) -> None:
    journal_checks = [
        {
            "name": f"journal system noise #{index}",
            "status": "WARN",
            "severity": "WARN",
            "detail": "bluetoothd",
        }
        for index in range(20)
    ]
    journal_result = JournalCheckResult(
        critical=0,
        warnings=20,
        system_noise=20,
        checks=journal_checks,
    )
    shadow_result = ShadowChecksResult(
        critical=0,
        warnings=0,
        checks=[],
    )

    monkeypatch.setattr("cnc_control.selftest.core.run_journal_checks", lambda: journal_result)
    monkeypatch.setattr("cnc_control.selftest.core.run_shadow_checks", lambda: shadow_result)

    result = run_selftest()

    assert result.critical == 0
    assert result.warnings == 20
    assert result.system_noise == 20
    assert result.status == "OK"

