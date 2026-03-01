from __future__ import annotations

from typing import Any

from .journal import JournalCheckResult, run_journal_checks
from .result import SelfTestResult
from .shadow_checks import ShadowChecksResult, run_shadow_checks


def _section_status(critical: int, warnings: int) -> str:
    if critical > 0:
        return "FAIL"
    if warnings > 0:
        return "WARN"
    return "PASS"


def _build_details(
    *,
    journal: JournalCheckResult,
    shadow: ShadowChecksResult,
) -> dict[str, Any]:
    return {
        "journal": journal.to_dict(),
        "shadow": shadow.to_dict(),
    }


def run_selftest(*, env_file: str | None = None) -> SelfTestResult:
    journal = run_journal_checks()
    if env_file is None:
        shadow = run_shadow_checks()
    else:
        shadow = run_shadow_checks(env_file=env_file)

    result = SelfTestResult()
    result.merge_counts(
        critical=journal.critical + shadow.critical,
        warnings=journal.warnings + shadow.warnings,
        system_noise=journal.system_noise,
    )

    details = _build_details(journal=journal, shadow=shadow)
    details["status"] = {
        "journal": _section_status(journal.critical, journal.warnings),
        "shadow": _section_status(shadow.critical, shadow.warnings),
    }
    result.details = details

    return result

