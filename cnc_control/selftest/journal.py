from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any

CRITICAL_MESSAGE_KEYWORDS = (
    "shadow",
    "g_mass_storage",
    "dwc2",
    "fsm",
    "rebuild",
    "export",
)

SYSTEM_NOISE_KEYWORDS = (
    "bluetoothd",
    "wpa_supplicant",
    "dhcpcd",
    "networkmanager",
    "avahi-daemon",
    "modemmanager",
    "systemd-resolved",
)


@dataclass
class JournalCheckResult:
    critical: int = 0
    warnings: int = 0
    system_noise: int = 0
    checks: list[dict[str, str]] = field(default_factory=list)

    def add_check(self, *, name: str, status: str, severity: str, detail: str) -> None:
        self.checks.append(
            {
                "name": name,
                "status": status,
                "severity": severity,
                "detail": detail,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        if self.critical > 0:
            section_status = "FAIL"
        elif self.warnings > 0:
            section_status = "WARN"
        else:
            section_status = "PASS"
        return {
            "status": section_status,
            "critical": self.critical,
            "warnings": self.warnings,
            "system_noise": self.system_noise,
            "checks": self.checks,
        }


def _run_journalctl() -> subprocess.CompletedProcess[str]:
    command = ["journalctl", "-p", "3", "-o", "json", "--no-pager"]
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(
            args=command,
            returncode=127,
            stdout="",
            stderr=str(exc),
        )


def _entry_detail(payload: dict[str, Any]) -> str:
    unit = str(payload.get("_SYSTEMD_UNIT") or payload.get("UNIT") or "").strip()
    identifier = str(payload.get("SYSLOG_IDENTIFIER") or payload.get("_COMM") or "").strip()
    message = str(payload.get("MESSAGE") or "").strip()
    source = unit or identifier or "journal"
    if message:
        return f"{source}: {message}"
    return source


def _is_critical(payload: dict[str, Any]) -> bool:
    unit = str(payload.get("_SYSTEMD_UNIT") or payload.get("UNIT") or "").strip().casefold()
    message = str(payload.get("MESSAGE") or "").strip().casefold()

    if unit.startswith("cnc-"):
        return True

    for keyword in CRITICAL_MESSAGE_KEYWORDS:
        if keyword in message:
            return True
    return False


def _is_system_noise(payload: dict[str, Any]) -> bool:
    unit = str(payload.get("_SYSTEMD_UNIT") or payload.get("UNIT") or "").strip().casefold()
    identifier = str(payload.get("SYSLOG_IDENTIFIER") or payload.get("_COMM") or "").strip().casefold()
    message = str(payload.get("MESSAGE") or "").strip().casefold()
    for keyword in SYSTEM_NOISE_KEYWORDS:
        if keyword in unit or keyword in identifier or keyword in message:
            return True
    return False


def _iter_journal_payloads(stdout: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payloads.append(parsed)
    return payloads


def run_journal_checks() -> JournalCheckResult:
    result = JournalCheckResult()
    journal = _run_journalctl()

    if journal.returncode != 0:
        detail = (journal.stderr or journal.stdout or "").strip()
        if not detail:
            detail = f"journalctl rc={journal.returncode}"
        result.warnings += 1
        result.add_check(
            name="journalctl command",
            status="WARN",
            severity="WARN",
            detail=detail,
        )
        return result

    payloads = _iter_journal_payloads(journal.stdout)
    if not payloads:
        result.add_check(
            name="journalctl entries",
            status="PASS",
            severity="WARN",
            detail="No priority<=3 entries",
        )
        return result

    for payload in payloads:
        detail = _entry_detail(payload)
        if _is_critical(payload):
            result.critical += 1
            result.add_check(
                name="journal critical entry",
                status="FAIL",
                severity="CRITICAL",
                detail=detail,
            )
            continue

        if _is_system_noise(payload):
            result.warnings += 1
            result.system_noise += 1
            result.add_check(
                name="journal system noise",
                status="WARN",
                severity="WARN",
                detail=detail,
            )
            continue

        result.warnings += 1
        result.add_check(
            name="journal unrelated error",
            status="WARN",
            severity="WARN",
            detail=detail,
        )

    if result.critical == 0 and not result.checks:
        result.add_check(
            name="journalctl entries",
            status="PASS",
            severity="WARN",
            detail="No relevant entries",
        )

    return result
