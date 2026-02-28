#!/usr/bin/env python3
"""External integration test runner for SSH and SMB connectivity checks."""

from __future__ import annotations

import argparse
import json
import platform
import socket
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_ENV_TARGETS = {"dev", "integration"}
ENV_MARKER_FILENAME = ".cnc_target"


@dataclass
class TestResult:
    """Single test execution result."""

    __test__ = False

    name: str
    status: str
    duration_seconds: float
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class Report:
    """Integration run report."""

    timestamp_utc: str
    selected_mode: str
    platform: dict[str, str]
    results: list[TestResult]

    def to_dict(self) -> dict[str, Any]:
        passed = sum(1 for result in self.results if result.status == "passed")
        failed = len(self.results) - passed
        return {
            "timestamp_utc": self.timestamp_utc,
            "selected_mode": self.selected_mode,
            "platform": self.platform,
            "summary": {
                "total": len(self.results),
                "passed": passed,
                "failed": failed,
            },
            "results": [asdict(result) for result in self.results],
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run external integration checks over SSH and SMB without "
            "modifying system logic."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("ssh", "smb", "all"),
        default="all",
        help="Test mode: SSH only, SMB only, or both.",
    )
    parser.add_argument(
        "--report",
        default="integration_tests/report.json",
        help="Path to output JSON report.",
    )
    parser.add_argument(
        "--skip-target-check",
        action="store_true",
        help="Skip .venv target marker validation.",
    )

    # PL: Parametry testu SSH są jawnie oddzielone dla czytelności konfiguracji.
    # EN: SSH test parameters are explicitly separated for clear configuration.
    parser.add_argument("--ssh-host", help="SSH target host/IP.")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH port.")
    parser.add_argument("--ssh-user", help="SSH username.")
    parser.add_argument("--ssh-password", help="SSH password (optional).")
    parser.add_argument(
        "--ssh-key-file",
        help="Path to private key file used by paramiko (optional).",
    )
    parser.add_argument(
        "--ssh-timeout",
        type=float,
        default=10.0,
        help="SSH connection timeout in seconds.",
    )
    parser.add_argument(
        "--ssh-command",
        default="echo ssh_connectivity_ok",
        help="Read-only command executed over SSH.",
    )

    # PL: Parametry SMB umożliwiają test dostępu bez modyfikowania danych.
    # EN: SMB parameters allow access checks without changing data.
    parser.add_argument("--smb-host", help="SMB server host/IP.")
    parser.add_argument("--smb-port", type=int, default=445, help="SMB port.")
    parser.add_argument("--smb-user", help="SMB username.")
    parser.add_argument("--smb-password", help="SMB password.")
    parser.add_argument("--smb-domain", default="", help="SMB domain/workgroup.")
    parser.add_argument("--smb-share", help="SMB share name.")
    parser.add_argument(
        "--smb-path",
        default="/",
        help="Directory path inside share to list (read-only).",
    )
    parser.add_argument(
        "--smb-client-name",
        default=socket.gethostname(),
        help="Client machine name used during SMB negotiation.",
    )
    parser.add_argument(
        "--smb-server-name",
        help="Server NetBIOS name (defaults to --smb-host).",
    )
    parser.add_argument(
        "--smb-timeout",
        type=float,
        default=10.0,
        help="SMB connection timeout in seconds.",
    )

    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> list[str]:
    errors: list[str] = []

    if args.mode in ("ssh", "all"):
        if not args.ssh_host:
            errors.append("Missing --ssh-host for SSH mode.")
        if not args.ssh_user:
            errors.append("Missing --ssh-user for SSH mode.")
        if not args.ssh_password and not args.ssh_key_file:
            errors.append(
                "Provide --ssh-password or --ssh-key-file for SSH mode."
            )

    if args.mode in ("smb", "all"):
        if not args.smb_host:
            errors.append("Missing --smb-host for SMB mode.")
        if not args.smb_user:
            errors.append("Missing --smb-user for SMB mode.")
        if args.smb_password is None:
            errors.append("Missing --smb-password for SMB mode.")
        if not args.smb_share:
            errors.append("Missing --smb-share for SMB mode.")

    return errors


def resolve_environment_target() -> tuple[str | None, str | None]:
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        return None, (
            "No virtual environment is active. "
            "Activate .venv created by tools/bootstrap_env.py."
        )

    marker_path = Path(sys.prefix) / ENV_MARKER_FILENAME
    if not marker_path.exists():
        return None, (
            f"Missing environment marker: {marker_path}. "
            "Create/update .venv with tools/bootstrap_env.py."
        )

    marker_lines = marker_path.read_text(encoding="utf-8").splitlines()
    if not marker_lines:
        return None, f"Environment marker is empty: {marker_path}"

    return marker_lines[0].strip(), None


def validate_environment_target(args: argparse.Namespace) -> list[str]:
    if args.skip_target_check:
        return []

    errors: list[str] = []
    target, resolution_error = resolve_environment_target()
    if resolution_error:
        errors.append(resolution_error)
        return errors

    if target not in EXPECTED_ENV_TARGETS:
        allowed_targets = ", ".join(sorted(EXPECTED_ENV_TARGETS))
        errors.append(
            f"Unsupported environment target '{target}' for integration tests. "
            f"Expected one of: {allowed_targets}."
        )

    return errors


def run_ssh_test(args: argparse.Namespace) -> TestResult:
    start = time.perf_counter()

    try:
        import paramiko
    except ImportError as exc:
        duration = time.perf_counter() - start
        return TestResult(
            name="ssh_connectivity",
            status="failed",
            duration_seconds=round(duration, 6),
            error=(
                "Missing dependency: paramiko. Install with: "
                "pip install paramiko"
            ),
            details={"exception": str(exc)},
        )

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh_client.connect(
            hostname=args.ssh_host,
            port=args.ssh_port,
            username=args.ssh_user,
            password=args.ssh_password,
            key_filename=args.ssh_key_file,
            timeout=args.ssh_timeout,
            banner_timeout=args.ssh_timeout,
            auth_timeout=args.ssh_timeout,
            look_for_keys=args.ssh_key_file is None,
            allow_agent=args.ssh_key_file is None,
        )

        stdin, stdout, stderr = ssh_client.exec_command(args.ssh_command)
        stdin.close()

        output = stdout.read().decode("utf-8", errors="replace").strip()
        error_output = stderr.read().decode("utf-8", errors="replace").strip()
        command_exit_status = stdout.channel.recv_exit_status()

        duration = time.perf_counter() - start
        status = "passed" if command_exit_status == 0 else "failed"
        return TestResult(
            name="ssh_connectivity",
            status=status,
            duration_seconds=round(duration, 6),
            details={
                "host": args.ssh_host,
                "port": args.ssh_port,
                "command": args.ssh_command,
                "command_exit_status": command_exit_status,
                "stdout": output,
                "stderr": error_output,
            },
            error=(
                None
                if command_exit_status == 0
                else "SSH command returned a non-zero exit status."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        duration = time.perf_counter() - start
        return TestResult(
            name="ssh_connectivity",
            status="failed",
            duration_seconds=round(duration, 6),
            error=str(exc),
            details={
                "host": args.ssh_host,
                "port": args.ssh_port,
                "command": args.ssh_command,
            },
        )
    finally:
        ssh_client.close()


def run_smb_test(args: argparse.Namespace) -> TestResult:
    start = time.perf_counter()

    try:
        from smb.SMBConnection import SMBConnection
    except ImportError as exc:
        duration = time.perf_counter() - start
        return TestResult(
            name="smb_connectivity",
            status="failed",
            duration_seconds=round(duration, 6),
            error=(
                "Missing dependency: pysmb. Install with: "
                "pip install pysmb"
            ),
            details={"exception": str(exc)},
        )

    server_name = args.smb_server_name or args.smb_host

    # PL: Test SMB wykonuje wyłącznie operacje odczytu (połączenie + listowanie).
    # EN: SMB test only performs read operations (connect + list directory).
    connection = SMBConnection(
        username=args.smb_user,
        password=args.smb_password,
        my_name=args.smb_client_name,
        remote_name=server_name,
        domain=args.smb_domain,
        use_ntlm_v2=True,
        is_direct_tcp=True,
    )

    try:
        connected = connection.connect(
            ip=args.smb_host,
            port=args.smb_port,
            timeout=args.smb_timeout,
        )
        if not connected:
            duration = time.perf_counter() - start
            return TestResult(
                name="smb_connectivity",
                status="failed",
                duration_seconds=round(duration, 6),
                error="SMB connection was rejected.",
                details={
                    "host": args.smb_host,
                    "port": args.smb_port,
                    "share": args.smb_share,
                    "path": args.smb_path,
                },
            )

        entries = connection.listPath(args.smb_share, args.smb_path)
        visible_entries = [
            entry.filename
            for entry in entries
            if entry.filename not in {".", ".."}
        ]

        duration = time.perf_counter() - start
        return TestResult(
            name="smb_connectivity",
            status="passed",
            duration_seconds=round(duration, 6),
            details={
                "host": args.smb_host,
                "port": args.smb_port,
                "share": args.smb_share,
                "path": args.smb_path,
                "entry_count": len(visible_entries),
                "entries_preview": visible_entries[:10],
            },
        )
    except Exception as exc:  # noqa: BLE001
        duration = time.perf_counter() - start
        return TestResult(
            name="smb_connectivity",
            status="failed",
            duration_seconds=round(duration, 6),
            error=str(exc),
            details={
                "host": args.smb_host,
                "port": args.smb_port,
                "share": args.smb_share,
                "path": args.smb_path,
            },
        )
    finally:
        connection.close()


def write_report(report: Report, report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    validation_errors = validate_environment_target(args)
    validation_errors.extend(validate_args(args))

    if validation_errors:
        for error in validation_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2

    results: list[TestResult] = []

    if args.mode in ("ssh", "all"):
        results.append(run_ssh_test(args))

    if args.mode in ("smb", "all"):
        results.append(run_smb_test(args))

    report = Report(
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        selected_mode=args.mode,
        platform={
            "system": platform.system(),
            "release": platform.release(),
            "python_version": platform.python_version(),
        },
        results=results,
    )

    report_path = Path(args.report)
    write_report(report, report_path)

    failed_count = sum(1 for result in results if result.status != "passed")
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return 1 if failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
