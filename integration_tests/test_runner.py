#!/usr/bin/env python3
"""Multi-platform integration runner for CNC Control deployment checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import types
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urljoin, urlparse

# PL: Zapewnia wpis modułu dla loaderow testowych, ktore nie rejestruja modułu w sys.modules.
# EN: Ensures module registration for test loaders that do not register it in sys.modules.
if __name__ not in sys.modules:
    module_placeholder = types.ModuleType(__name__)
    module_placeholder.__dict__.update(globals())
    sys.modules[__name__] = module_placeholder

EXPECTED_ENV_TARGETS = {"dev", "integration"}
ENV_MARKER_FILENAME = ".cnc_target"


def parse_status_mode(output: str) -> str | None:
    for line in output.splitlines():
        if "Tryb pracy:" not in line:
            continue
        value = line.split("Tryb pracy:", 1)[1].strip().casefold()
        if value.startswith("shadow"):
            return "SHADOW"
        if value.startswith("usb"):
            return "USB"
        if value.startswith("siec") or value.startswith("sieć"):
            return "NET"
    return None


def parse_status_mount_point(output: str) -> str | None:
    for line in output.splitlines():
        if not line.startswith("Punkt montowania:"):
            continue
        value = line.split("Punkt montowania:", 1)[1].strip()
        return value or None
    return None


def parse_env_text(content: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        result[key] = value
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


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


@dataclass
class TestResult:
    """Single test phase execution result."""

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
    target: dict[str, Any]
    platform: dict[str, str]
    results: list[TestResult]
    measurements: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        passed = sum(1 for result in self.results if result.status == "passed")
        failed = sum(1 for result in self.results if result.status == "failed")
        skipped = sum(1 for result in self.results if result.status == "skipped")
        return {
            "timestamp_utc": self.timestamp_utc,
            "selected_mode": self.selected_mode,
            "target": self.target,
            "platform": self.platform,
            "summary": {
                "total": len(self.results),
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
            },
            "measurements": self.measurements,
            "results": [asdict(result) for result in self.results],
        }


class SkipPhaseError(RuntimeError):
    """Raised when a phase should be explicitly skipped."""


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.results: list[TestResult] = []
        self.measurements: dict[str, Any] = {}
        self.preflight_ok = False
        self.session = None
        self.ssh_client = None
        self.remote_env: dict[str, str] = {}
        self.remote_repo: str | None = None
        self.upload_dir: str | None = None
        self.mount_point: str | None = None
        self.udc_name: str | None = None
        self.shadow_enabled = False
        self.shadow_master_dir: str | None = None
        self.webui_url = (args.webui_url or f"http://{args.host}:8080").rstrip("/")
        run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        self.run_prefix = f"it_{run_stamp}_{Path.cwd().name}"
        self.local_temp_dir = Path(tempfile.mkdtemp(prefix="cnc_it_"))
        self.created_files: set[str] = set()
        self.smb_created_files: set[str] = set()

    def log_console(self, message: str) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        print(f"[{timestamp}] {message}", file=sys.stderr, flush=True)

    def close(self) -> None:
        if self.ssh_client is not None:
            self.ssh_client.close()
            self.ssh_client = None
        if self.session is not None:
            self.session.close()
            self.session = None
        shutil.rmtree(self.local_temp_dir, ignore_errors=True)

    def run(self) -> None:
        selected = self.resolve_selected_phases(self.args.mode)
        selected_names = [name for name, _fn in selected]
        self.log_console(
            "START integration run: "
            f"mode={self.args.mode}, phases={['phase_0_preflight', *selected_names, 'phase_6_cleanup']}"
        )
        self.run_phase("phase_0_preflight", self.phase_0_preflight)

        for phase_name, phase_fn in selected:
            if not self.preflight_ok:
                self.run_phase(
                    phase_name,
                    lambda: (_ for _ in ()).throw(
                        SkipPhaseError("Skipped because phase_0_preflight failed.")
                    ),
                )
                continue
            self.run_phase(phase_name, phase_fn)

        self.run_phase("phase_6_cleanup", self.phase_6_cleanup)
        self.log_console("END integration run")

    def resolve_selected_phases(
        self, mode: str
    ) -> list[tuple[str, Callable[[], dict[str, Any]]]]:
        phase_map: dict[str, list[tuple[str, Callable[[], dict[str, Any]]]]] = {
            "preflight": [],
            "ssh": [],
            "net": [("phase_1_net_webui", self.phase_1_net_webui)],
            "smb": [("phase_2_smb", self.phase_2_smb)],
            "usb": [("phase_3_usb", self.phase_3_usb)],
            "sync": [("phase_4_sync_net_to_usb", self.phase_4_sync_net_to_usb)],
            "perf": [("phase_5_performance", self.phase_5_performance)],
            "shadow": [
                ("phase_shadow_1_watcher", self.phase_shadow_1_watcher),
                ("phase_shadow_2_sync_files", self.phase_shadow_2_sync_files),
                ("phase_shadow_3_gcode_runtime", self.phase_shadow_3_gcode_runtime),
            ],
            "all": [
                ("phase_1_net_webui", self.phase_1_net_webui),
                ("phase_2_smb", self.phase_2_smb),
                ("phase_3_usb", self.phase_3_usb),
                ("phase_4_sync_net_to_usb", self.phase_4_sync_net_to_usb),
                ("phase_5_performance", self.phase_5_performance),
                ("phase_shadow_1_watcher", self.phase_shadow_1_watcher),
                ("phase_shadow_2_sync_files", self.phase_shadow_2_sync_files),
                ("phase_shadow_3_gcode_runtime", self.phase_shadow_3_gcode_runtime),
            ],
        }
        return phase_map[mode]

    def run_phase(
        self, name: str, action: Callable[[], dict[str, Any]]
    ) -> None:
        self.log_console(f"PHASE START: {name}")
        started = time.perf_counter()
        status = "passed"
        details: dict[str, Any] = {}
        error: str | None = None

        try:
            details = action()
        except SkipPhaseError as exc:
            status = "skipped"
            error = str(exc)
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error = str(exc)

        duration = round(time.perf_counter() - started, 6)
        self.results.append(
            TestResult(
                name=name,
                status=status,
                duration_seconds=duration,
                details=details,
                error=error,
            )
        )
        summary = f"PHASE END: {name} -> {status} ({duration:.3f}s)"
        if error:
            summary = f"{summary}; reason={error}"
        self.log_console(summary)
        if name == "phase_0_preflight" and status == "passed":
            self.preflight_ok = True

    def phase_0_preflight(self) -> dict[str, Any]:
        self.ensure_requests_session()
        self.connect_ssh()

        ssh_probe = self.ssh_exec("echo preflight_ssh_ok", check=True)
        initial_env_payload = self.read_remote_env()

        repo_path = initial_env_payload.get("CNC_CONTROL_REPO")
        if not repo_path:
            repo_path = f"/home/{self.args.ssh_user}/cnc-control"
        self.remote_repo = repo_path

        remote_refresh = self.refresh_remote_target(
            repo_path=repo_path,
            env_payload=initial_env_payload,
        )

        env_payload = self.read_remote_env()
        self.remote_env = env_payload
        self.remote_repo = env_payload.get("CNC_CONTROL_REPO") or self.remote_repo

        self.upload_dir = (
            env_payload.get("CNC_UPLOAD_DIR")
            or env_payload.get("CNC_MOUNT_POINT")
            or env_payload.get("CNC_USB_MOUNT")
        )
        self.mount_point = (
            env_payload.get("CNC_MOUNT_POINT")
            or env_payload.get("CNC_USB_MOUNT")
            or self.upload_dir
        )

        if not self.upload_dir:
            raise RuntimeError(
                "Brak CNC_UPLOAD_DIR/CNC_MOUNT_POINT w /etc/cnc-control/cnc-control.env"
            )

        status_cmd = f"{shlex.quote(str(PurePosixPath(self.remote_repo or repo_path) / 'status.sh'))}"
        status_result = self.ssh_exec(status_cmd, check=True)
        status_mode = parse_status_mode(status_result["stdout"])
        status_mount = parse_status_mount_point(status_result["stdout"])

        udc_result = self.ssh_exec(
            "if [ -d /sys/class/udc ]; then ls -A /sys/class/udc | head -n 1; fi",
            check=False,
        )
        self.udc_name = (udc_result["stdout"] or "").strip() or None

        api_status = self.fetch_api_status()
        shadow_from_env = str(env_payload.get("CNC_SHADOW_ENABLED", "")).strip().casefold()
        self.shadow_enabled = shadow_from_env in {"1", "true", "yes", "on"}
        if str(api_status.get("mode") or "").upper() == "SHADOW":
            self.shadow_enabled = True
        self.shadow_master_dir = env_payload.get("CNC_MASTER_DIR") or "/var/lib/cnc-control/master"
        if self.shadow_enabled:
            self.upload_dir = self.shadow_master_dir

        return {
            "ssh": {
                "host": self.args.host,
                "user": self.args.ssh_user,
                "stdout": ssh_probe["stdout"],
            },
            "remote_refresh": remote_refresh,
            "env": {
                "repo": self.remote_repo,
                "upload_dir": self.upload_dir,
                "mount_point": self.mount_point,
                "shadow_enabled": env_payload.get("CNC_SHADOW_ENABLED"),
                "shadow_master_dir": self.shadow_master_dir,
            },
            "status_sh": {
                "mode": status_mode,
                "mount_point": status_mount,
            },
            "udc": {
                "present": bool(self.udc_name),
                "name": self.udc_name,
            },
            "webui": {
                "url": self.webui_url,
                "api_status_mode": api_status.get("mode"),
                "switching": api_status.get("switching"),
            },
            "shadow_enabled": self.shadow_enabled,
        }

    def refresh_remote_target(
        self,
        *,
        repo_path: str,
        env_payload: dict[str, str],
    ) -> dict[str, Any]:
        if self.args.skip_remote_refresh:
            return {
                "status": "skipped",
                "reason": "Skipped by --skip-remote-refresh.",
            }
        self.log_console(f"REMOTE REFRESH: repo={repo_path}")

        repo_path_quoted = shlex.quote(repo_path)
        venv_dir = env_payload.get("CNC_VENV_DIR") or str(PurePosixPath(repo_path) / ".venv")

        self.ssh_exec(
            f"test -d {repo_path_quoted}",
            check=True,
        )
        self.ssh_exec(
            f"git -C {repo_path_quoted} rev-parse --is-inside-work-tree",
            check=True,
        )

        branch_result = self.ssh_exec(
            f"git -C {repo_path_quoted} rev-parse --abbrev-ref HEAD",
            check=True,
        )
        head_before_result = self.ssh_exec(
            f"git -C {repo_path_quoted} rev-parse HEAD",
            check=True,
        )
        origin_result = self.ssh_exec(
            f"git -C {repo_path_quoted} remote get-url origin",
            check=False,
        )

        pull_result = self.ssh_exec(
            f"git -C {repo_path_quoted} pull --ff-only",
            timeout=self.args.remote_refresh_timeout,
            check=True,
        )
        self.log_console("REMOTE REFRESH: git pull --ff-only done")

        head_after_result = self.ssh_exec(
            f"git -C {repo_path_quoted} rev-parse HEAD",
            check=True,
        )

        bootstrap_and_install_command = (
            "set -euo pipefail\n"
            f"repo_path={shlex.quote(repo_path)}\n"
            f"venv_dir={shlex.quote(venv_dir)}\n"
            "cd \"$repo_path\"\n"
            "if [ ! -x \"$venv_dir/bin/python3\" ]; then\n"
            "  python3 tools/bootstrap_env.py --target rpi --venv-dir \"$venv_dir\"\n"
            "fi\n"
            "\"$venv_dir/bin/python3\" -m pip install --editable '.[rpi]'\n"
        )
        self.ssh_exec(
            bootstrap_and_install_command,
            timeout=self.args.remote_refresh_timeout,
            check=True,
        )
        self.log_console("REMOTE REFRESH: editable install done")

        config_refresh_command = (
            "set -euo pipefail\n"
            f"repo_path={shlex.quote(repo_path)}\n"
            f"venv_dir={shlex.quote(venv_dir)}\n"
            "if [ \"$(id -u)\" -eq 0 ]; then\n"
            "  env SUDO_USER=\"${SUDO_USER:-root}\" CNC_VENV_DIR=\"$venv_dir\" "
            "bash \"$repo_path/tools/setup_webui.sh\" \"$repo_path\"\n"
            "  bash \"$repo_path/tools/setup_usb_service.sh\" \"$repo_path\"\n"
            "  env CNC_VENV_DIR=\"$venv_dir\" bash \"$repo_path/tools/setup_led_service.sh\" \"$repo_path\"\n"
            "else\n"
            "  sudo -n env SUDO_USER=\"$USER\" CNC_VENV_DIR=\"$venv_dir\" "
            "bash \"$repo_path/tools/setup_webui.sh\" \"$repo_path\"\n"
            "  sudo -n bash \"$repo_path/tools/setup_usb_service.sh\" \"$repo_path\"\n"
            "  sudo -n env CNC_VENV_DIR=\"$venv_dir\" "
            "bash \"$repo_path/tools/setup_led_service.sh\" \"$repo_path\"\n"
            "fi\n"
        )
        self.ssh_exec(
            config_refresh_command,
            timeout=self.args.remote_refresh_timeout,
            check=True,
        )
        self.log_console("REMOTE REFRESH: setup_webui/setup_usb/setup_led done")

        selftest_report = self.run_remote_selftest_with_auto_repair(
            repo_path=repo_path,
            venv_dir=venv_dir,
            env_payload=env_payload,
        )
        self.log_console("REMOTE REFRESH: cnc_selftest completed")
        selftest_result = selftest_report["result"]
        selftest_payload = selftest_report["payload"]

        required_services = (
            "cnc-webui.service",
            "cnc-usb.service",
            "cnc-led.service",
        )
        systemd_states: dict[str, str] = {}
        for service_name in required_services:
            state_result = self.ssh_exec(
                f"systemctl is-active {shlex.quote(service_name)}",
                check=False,
            )
            state = (state_result["stdout"] or "").strip()
            systemd_states[service_name] = state or "unknown"
            if state != "active":
                raise RuntimeError(
                    f"Wymagana usługa systemd nie jest aktywna: {service_name} -> {state or 'unknown'}"
                )

        journal_result = self.ssh_exec(
            "journalctl -p 3 -n 20 --no-pager",
            check=False,
        )
        if journal_result["exit_status"] != 0:
            fallback_journal = self.ssh_exec(
                "sudo -n journalctl -p 3 -n 20 --no-pager",
                check=True,
            )
            journal_output = fallback_journal["stdout"]
        else:
            journal_output = journal_result["stdout"]

        journal_lines = [line for line in journal_output.splitlines() if line.strip()]
        journal_cnc_lines = self.filter_cnc_journal_lines(journal_lines)
        if journal_cnc_lines:
            journal_preview = "\n".join(journal_cnc_lines[-5:])
            raise RuntimeError(
                "Wykryto wpisy ERROR/CRITICAL zwiazane z CNC w journalctl -p 3 -n 20:\n"
                f"{journal_preview}"
            )

        refresh_details: dict[str, Any] = {
            "status": "ok",
            "repo": {
                "path": repo_path,
                "origin": origin_result["stdout"] or None,
                "branch": branch_result["stdout"],
                "head_before": head_before_result["stdout"],
                "head_after": head_after_result["stdout"],
                "updated": head_before_result["stdout"] != head_after_result["stdout"],
                "pull_stdout": pull_result["stdout"],
            },
            "venv": {
                "path": venv_dir,
            },
            "systemd": systemd_states,
            "journal_priority_le_3_entries_total": len(journal_lines),
            "journal_priority_le_3_entries_cnc": len(journal_cnc_lines),
        }
        if isinstance(selftest_payload, dict):
            refresh_details["selftest"] = {
                "format": "json",
                "summary": selftest_payload.get("summary"),
                "result": selftest_payload.get("result"),
                "attempts": selftest_report["attempts"],
                "auto_repair_runtime_lun": selftest_report["auto_repair_runtime_lun"],
                "auto_repair_details": selftest_report.get("auto_repair_details"),
            }
        else:
            refresh_details["selftest"] = {
                "format": "text",
                "stdout_preview": "\n".join(
                    (selftest_result["stdout"] or "").splitlines()[-10:]
                ),
                "attempts": selftest_report["attempts"],
                "auto_repair_runtime_lun": selftest_report["auto_repair_runtime_lun"],
                "auto_repair_details": selftest_report.get("auto_repair_details"),
            }

        return refresh_details

    def run_remote_selftest_with_auto_repair(
        self,
        *,
        repo_path: str,
        venv_dir: str,
        env_payload: dict[str, str],
    ) -> dict[str, Any]:
        first_result, first_payload = self.run_remote_selftest(
            repo_path=repo_path,
            venv_dir=venv_dir,
        )
        if first_result["exit_status"] == 0:
            return {
                "result": first_result,
                "payload": first_payload,
                "attempts": 1,
                "auto_repair_runtime_lun": False,
                "auto_repair_details": None,
            }

        auto_repair_details: dict[str, Any] | None = None
        if (
            not self.args.disable_selftest_auto_repair
            and self.is_runtime_lun_mismatch_failure(first_payload)
        ):
            repair_result = self.repair_runtime_lun_shadow_slot(env_payload)
            auto_repair_details = {
                "kind": "runtime_lun_shadow_slot",
                "stdout": repair_result["stdout"],
                "stderr": repair_result["stderr"],
            }
            second_result, second_payload = self.run_remote_selftest(
                repo_path=repo_path,
                venv_dir=venv_dir,
            )
            if second_result["exit_status"] == 0:
                return {
                    "result": second_result,
                    "payload": second_payload,
                    "attempts": 2,
                    "auto_repair_runtime_lun": True,
                    "auto_repair_details": auto_repair_details,
                }
            first_result = second_result
            first_payload = second_payload

        raise RuntimeError(
            self.build_selftest_failure_message(
                result=first_result,
                payload=first_payload,
                auto_repair_details=auto_repair_details,
            )
        )

    def run_remote_selftest(
        self,
        *,
        repo_path: str,
        venv_dir: str,
    ) -> tuple[dict[str, Any], Any]:
        selftest_command = (
            "set -euo pipefail\n"
            f"repo_path={shlex.quote(repo_path)}\n"
            f"venv_dir={shlex.quote(venv_dir)}\n"
            "cd \"$repo_path\"\n"
            "if [ ! -f \"$venv_dir/bin/activate\" ]; then\n"
            "  echo \"Missing virtualenv activate script: $venv_dir/bin/activate\" >&2\n"
            "  exit 1\n"
            "fi\n"
            ". \"$venv_dir/bin/activate\"\n"
            "./tools/cnc_selftest.sh --json\n"
        )
        result = self.ssh_exec(
            selftest_command,
            timeout=self.args.remote_selftest_timeout,
            check=False,
        )
        payload = self.parse_json_if_possible(result["stdout"])
        return result, payload

    def is_runtime_lun_mismatch_failure(self, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        runtime = payload.get("runtime")
        if not isinstance(runtime, dict):
            return False
        checks = runtime.get("checks")
        if not isinstance(checks, list):
            return False
        mismatch_present = False
        for check in checks:
            if not isinstance(check, dict):
                continue
            name = str(check.get("name") or "")
            status = str(check.get("status") or "").upper()
            if name == "Runtime LUN image matches expected" and status == "FAIL":
                mismatch_present = True
                break
        if not mismatch_present:
            return False
        summary = payload.get("summary")
        if isinstance(summary, dict):
            critical = int(summary.get("critical") or 0)
            return critical <= 1
        return True

    def repair_runtime_lun_shadow_slot(self, env_payload: dict[str, str]) -> dict[str, Any]:
        slot_file = env_payload.get("CNC_ACTIVE_SLOT_FILE") or "/var/lib/cnc-control/shadow_active_slot.state"
        image_a = env_payload.get("CNC_USB_IMG_A") or "/var/lib/cnc-control/cnc_usb_a.img"
        image_b = env_payload.get("CNC_USB_IMG_B") or "/var/lib/cnc-control/cnc_usb_b.img"

        command = (
            "set -euo pipefail\n"
            f"slot_file={shlex.quote(slot_file)}\n"
            f"image_a={shlex.quote(image_a)}\n"
            f"image_b={shlex.quote(image_b)}\n"
            "runtime_file='/sys/module/g_mass_storage/parameters/file'\n"
            "if [ ! -f \"$slot_file\" ]; then\n"
            "  echo \"Missing active slot file: $slot_file\" >&2\n"
            "  exit 1\n"
            "fi\n"
            "slot_raw=\"$(tr -d '\\r\\n\\t ' < \"$slot_file\")\"\n"
            "slot=\"$(printf '%s' \"$slot_raw\" | tr '[:lower:]' '[:upper:]')\"\n"
            "if [ \"$slot\" = 'A' ]; then\n"
            "  expected=\"$image_a\"\n"
            "elif [ \"$slot\" = 'B' ]; then\n"
            "  expected=\"$image_b\"\n"
            "else\n"
            "  echo \"Invalid active slot value: $slot\" >&2\n"
            "  exit 1\n"
            "fi\n"
            "runtime_before=\"$(cat \"$runtime_file\" 2>/dev/null || true)\"\n"
            "run_root() {\n"
            "  if [ \"$(id -u)\" -eq 0 ]; then\n"
            "    \"$@\"\n"
            "  else\n"
            "    sudo -n \"$@\"\n"
            "  fi\n"
            "}\n"
            "if [ \"$runtime_before\" != \"$expected\" ]; then\n"
            "  run_root modprobe -r g_mass_storage || true\n"
            "  run_root modprobe g_mass_storage \"file=$expected\" ro=1 removable=1\n"
            "fi\n"
            "runtime_after=\"$(cat \"$runtime_file\" 2>/dev/null || true)\"\n"
            "if [ \"$runtime_after\" != \"$expected\" ]; then\n"
            "  echo \"Runtime LUN mismatch after repair: runtime=$runtime_after expected=$expected\" >&2\n"
            "  exit 1\n"
            "fi\n"
            "printf 'slot=%s expected=%s runtime_before=%s runtime_after=%s\\n' "
            "\"$slot\" \"$expected\" \"$runtime_before\" \"$runtime_after\"\n"
        )
        return self.ssh_exec(
            command,
            timeout=self.args.remote_refresh_timeout,
            check=True,
        )

    def build_selftest_failure_message(
        self,
        *,
        result: dict[str, Any],
        payload: Any,
        auto_repair_details: dict[str, Any] | None,
    ) -> str:
        parts = [
            f"cnc_selftest failed (rc={result['exit_status']})",
        ]

        if isinstance(payload, dict):
            summary = payload.get("summary")
            if isinstance(summary, dict):
                parts.append(
                    "summary="
                    f"status:{summary.get('status')}, "
                    f"critical:{summary.get('critical')}, "
                    f"warnings:{summary.get('warnings')}"
                )
            failed_checks = self.extract_failed_check_messages(payload, limit=3)
            if failed_checks:
                parts.append("failed_checks=" + " | ".join(failed_checks))

        if auto_repair_details:
            parts.append("auto_repair_attempted=true")

        stderr_preview = (result.get("stderr") or "").strip()
        if stderr_preview:
            parts.append(f"stderr={stderr_preview}")

        stdout_preview = "\n".join((result.get("stdout") or "").splitlines()[-10:])
        if stdout_preview:
            parts.append(f"stdout_tail={stdout_preview}")

        return "; ".join(parts)

    def extract_failed_check_messages(self, payload: dict[str, Any], limit: int) -> list[str]:
        messages: list[str] = []
        for section_name, section_payload in payload.items():
            if section_name == "summary":
                continue
            if not isinstance(section_payload, dict):
                continue
            checks = section_payload.get("checks")
            if not isinstance(checks, list):
                continue
            for check in checks:
                if not isinstance(check, dict):
                    continue
                status = str(check.get("status") or "").upper()
                if status != "FAIL":
                    continue
                name = str(check.get("name") or "?")
                detail = str(check.get("detail") or "")
                messages.append(f"{section_name}:{name}:{detail}")
                if len(messages) >= limit:
                    return messages
        return messages

    def filter_cnc_journal_lines(self, journal_lines: list[str]) -> list[str]:
        pattern = re.compile(
            r"(cnc[-_]|cnc-control|shadow|shadow_usb_export|led_status|webui)",
            flags=re.IGNORECASE,
        )
        return [line for line in journal_lines if pattern.search(line)]

    def parse_json_if_possible(self, content: str) -> Any:
        text = content.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def phase_1_net_webui(self) -> dict[str, Any]:
        if self.shadow_enabled:
            raise SkipPhaseError("Tryb SHADOW aktywny - faza NET/WebUI pominięta.")
        switched = self.switch_mode("NET")

        uploaded_single = self.upload_files_via_webui(
            count=1,
            label="net_single",
        )
        uploaded_batch = self.upload_files_via_webui(
            count=5,
            label="net_batch",
        )
        all_uploaded = uploaded_single + uploaded_batch

        current_files = set(self.remote_list_files(self.upload_dir))
        missing = [name for name in all_uploaded if name not in current_files]
        if missing:
            raise RuntimeError(f"Brak przesłanych plików na RPi: {', '.join(missing)}")

        delete_response = self.delete_files_via_webui(all_uploaded)

        after_delete = set(self.remote_list_files(self.upload_dir))
        leftovers = [name for name in all_uploaded if name in after_delete]
        if leftovers:
            raise RuntimeError(f"Pliki nie zostaly usunięte: {', '.join(leftovers)}")

        return {
            "switch": switched,
            "uploaded_single": uploaded_single,
            "uploaded_batch": uploaded_batch,
            "delete": delete_response,
        }

    def phase_2_smb(self) -> dict[str, Any]:
        if not self.args.smb_share:
            raise SkipPhaseError("Brak --smb-share, faza SMB pominięta.")

        file_name = f"{self.run_prefix}_smb_probe.nc"
        self.smb_created_files.add(file_name)
        local_file = self.create_local_file(
            file_name,
            [
                "%",
                "(SMB put/delete test)",
                "G90",
                "G0 X0 Y0",
                "M30",
                "%",
            ],
        )

        try:
            try:
                result = self.run_smb_probe_with_pysmb(file_name, local_file)
            except Exception as exc:  # noqa: BLE001
                if self.is_pysmb_dialect_error(exc):
                    fallback = self.run_smb_probe_with_macos_mount(file_name, local_file)
                    result = {
                        "client": "pysmb_with_macos_smbfs_fallback",
                        "pysmb_error": str(exc),
                        "fallback": fallback,
                    }
                else:
                    raise
            self.smb_created_files.discard(file_name)
            return result
        finally:
            if file_name in self.smb_created_files:
                self.smb_created_files.discard(file_name)

    def run_smb_probe_with_pysmb(self, file_name: str, local_file: Path) -> dict[str, Any]:
        connection, meta = self.open_smb_connection()
        try:
            with local_file.open("rb") as handle:
                connection.storeFile(self.args.smb_share, file_name, handle)

            entries = connection.listPath(self.args.smb_share, "/")
            visible_names = sorted(
                [
                    entry.filename
                    for entry in entries
                    if entry.filename not in {".", ".."}
                ],
                key=str.casefold,
            )
            if file_name not in visible_names:
                raise RuntimeError("Plik SMB nie jest widoczny po zapisie.")

            connection.deleteFiles(self.args.smb_share, file_name)

            entries_after = connection.listPath(self.args.smb_share, "/")
            visible_after = {
                entry.filename
                for entry in entries_after
                if entry.filename not in {".", ".."}
            }
            if file_name in visible_after:
                raise RuntimeError("Plik SMB nadal istnieje po usunięciu.")

            return {
                "client": "pysmb",
                "connection": meta,
                "file": file_name,
                "entries_preview": visible_names[:10],
            }
        finally:
            connection.close()

    def is_pysmb_dialect_error(self, exc: Exception) -> bool:
        message = str(exc).casefold()
        return "does not support any of the pysmb dialects" in message

    def run_smb_probe_with_macos_mount(
        self, file_name: str, local_file: Path
    ) -> dict[str, Any]:
        if platform.system() != "Darwin":
            raise RuntimeError(
                "pysmb dialect negotiation failed and no fallback is available on this OS."
            )

        mount_point, preexisting = self.find_existing_macos_smb_mount()
        mounted_here = False

        if mount_point is None:
            temp_mount = Path(tempfile.mkdtemp(prefix="cnc_smb_mount_"))
            mount_url = self.build_macos_smb_url()
            mount_cmd = ["mount_smbfs", mount_url, str(temp_mount)]
            mount_proc = subprocess.run(
                mount_cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            if mount_proc.returncode != 0:
                raise RuntimeError(
                    "SMB fallback mount failed: "
                    f"{(mount_proc.stderr or mount_proc.stdout).strip()}"
                )
            mount_point = temp_mount
            mounted_here = True

        target = mount_point / file_name
        sidecar = mount_point / f"._{file_name}"
        shutil.copyfile(local_file, target)
        if not target.exists():
            raise RuntimeError("Fallback SMB: plik nie istnieje po zapisie.")

        listing = sorted(
            [
                item.name
                for item in mount_point.iterdir()
                if item.is_file() and not item.name.startswith(".")
            ],
            key=str.casefold,
        )
        if file_name not in listing:
            raise RuntimeError("Fallback SMB: plik nie jest widoczny po zapisie.")

        target.unlink(missing_ok=False)
        sidecar.unlink(missing_ok=True)
        if target.exists():
            raise RuntimeError("Fallback SMB: plik nadal istnieje po usunięciu.")
        if sidecar.exists():
            raise RuntimeError("Fallback SMB: plik sidecar nadal istnieje po usunięciu.")

        if mounted_here:
            umount_proc = subprocess.run(
                ["umount", str(mount_point)],
                capture_output=True,
                text=True,
                check=False,
            )
            if umount_proc.returncode != 0:
                raise RuntimeError(
                    "Fallback SMB umount failed: "
                    f"{(umount_proc.stderr or umount_proc.stdout).strip()}"
                )
            try:
                mount_point.rmdir()
            except OSError:
                pass

        return {
            "client": "macos_smbfs",
            "mount_point": str(mount_point),
            "used_existing_mount": preexisting,
            "file": file_name,
            "entries_preview": listing[:10],
        }

    def find_existing_macos_smb_mount(self) -> tuple[Path | None, bool]:
        if platform.system() != "Darwin":
            return None, False

        share = (self.args.smb_share or "").casefold()

        mount_proc = subprocess.run(
            ["mount"],
            capture_output=True,
            text=True,
            check=False,
        )
        if mount_proc.returncode != 0:
            return None, False

        for line in (mount_proc.stdout or "").splitlines():
            if "(smbfs" not in line:
                continue
            if " on " not in line:
                continue
            source, rest = line.split(" on ", 1)
            mount_path_raw = rest.split(" (", 1)[0].strip()
            src_norm = source.casefold()
            if share and f"/{share}" not in src_norm:
                continue
            mount_path = Path(mount_path_raw)
            if mount_path.exists():
                return mount_path, True

        return None, False

    def build_macos_smb_url(self) -> str:
        host = self.args.smb_host or self.args.host
        share = self.args.smb_share or ""

        smb_user = self.args.smb_user
        smb_pass = self.args.smb_pass

        if smb_user is None and smb_pass is None:
            smb_user = "guest"
            smb_pass = ""
        else:
            if smb_user is None:
                smb_user = self.args.ssh_user
            if smb_pass is None:
                smb_pass = self.args.ssh_pass

        user_enc = quote(smb_user, safe="")
        pass_enc = quote(smb_pass or "", safe="")
        return f"//{user_enc}:{pass_enc}@{host}/{share}"

    def phase_3_usb(self) -> dict[str, Any]:
        if self.shadow_enabled:
            raise SkipPhaseError("Tryb SHADOW aktywny - faza USB pominięta.")
        if not self.udc_name:
            raise SkipPhaseError("Brak UDC na RPi - faza USB pominięta.")

        usb_host_read: dict[str, Any] = {
            "enabled": bool(self.args.usb_host_mount),
            "reason": "usb_host_mount_not_set" if not self.args.usb_host_mount else "",
        }
        if self.args.usb_host_mount:
            usb_host_read = self.run_usb_host_read_probe()
            switched = usb_host_read["switch_to_usb"]
        else:
            switched = self.switch_mode("USB")

        mount_state = None
        listing_preview: list[str] = []
        if self.mount_point:
            mount_check = self.ssh_exec(
                f"mount | grep -F -- ' on {self.mount_point} ' >/dev/null",
                check=False,
            )
            mount_state = "mounted" if mount_check["exit_status"] == 0 else "unmounted"
            listing_cmd = (
                "python3 - <<'PY'\n"
                "import json\n"
                "from pathlib import Path\n"
                f"root = Path({self.mount_point!r})\n"
                "files = []\n"
                "if root.exists():\n"
                "    files = sorted([p.name for p in root.iterdir()][:10], key=str.casefold)\n"
                "print(json.dumps(files, ensure_ascii=True))\n"
                "PY"
            )
            listing_result = self.ssh_exec(listing_cmd, check=True)
            listing_preview = json.loads(listing_result["stdout"] or "[]")

        gadget_check = self.ssh_exec(
            "lsmod | grep -q '^g_mass_storage'",
            check=False,
        )
        if gadget_check["exit_status"] != 0:
            raise RuntimeError("g_mass_storage nie jest załadowany po przełączeniu na USB.")

        if mount_state == "mounted":
            raise RuntimeError("Konflikt: obraz nadal zamontowany lokalnie w trybie USB.")

        return {
            "switch": switched,
            "udc": self.udc_name,
            "mount_state": mount_state,
            "listing_preview": listing_preview,
            "usb_host_read": usb_host_read,
        }

    def run_usb_host_read_probe(self) -> dict[str, Any]:
        if not self.args.usb_host_mount:
            raise RuntimeError("Brak --usb-host-mount dla testu odczytu host USB.")

        host_mount = Path(self.args.usb_host_mount).expanduser()
        if not host_mount.exists() or not host_mount.is_dir():
            raise RuntimeError(
                f"Nieprawidłowy --usb-host-mount: {host_mount} (wymagany istniejący katalog)."
            )

        self.switch_mode("NET")

        file_name = f"{self.run_prefix}_usb_host_read_probe.nc"
        local_file = self.create_local_file(
            file_name,
            [
                "%",
                "(USB host read probe)",
                "G21",
                "G90",
                "G0 X5 Y5",
                "M30",
                "%",
            ],
        )
        self.upload_file_via_webui(local_file)
        expected_sha256 = sha256_file(local_file)

        switch_to_usb = self.switch_mode("USB")

        probe_path = host_mount / file_name
        started = time.monotonic()
        wait_deadline = started + self.args.usb_host_read_timeout
        while time.monotonic() < wait_deadline:
            if probe_path.is_file():
                break
            time.sleep(0.5)

        if not probe_path.is_file():
            preview_entries = sorted(
                [entry.name for entry in host_mount.iterdir() if not entry.name.startswith(".")],
                key=str.casefold,
            )[:20]
            raise RuntimeError(
                "Plik probe nie jest widoczny po stronie hosta USB "
                f"w czasie {self.args.usb_host_read_timeout}s: {probe_path}; "
                f"entries_preview={preview_entries}"
            )

        observed_sha256 = sha256_file(probe_path)
        if observed_sha256 != expected_sha256:
            raise RuntimeError(
                "Niezgodność SHA256 dla odczytu host USB: "
                f"expected={expected_sha256}, observed={observed_sha256}, file={probe_path}"
            )

        wait_seconds = round(time.monotonic() - started, 6)
        return {
            "enabled": True,
            "host_mount": str(host_mount),
            "file": file_name,
            "path": str(probe_path),
            "expected_sha256": expected_sha256,
            "observed_sha256": observed_sha256,
            "wait_seconds": wait_seconds,
            "switch_to_usb": switch_to_usb,
        }

    def phase_4_sync_net_to_usb(self) -> dict[str, Any]:
        if self.shadow_enabled:
            raise SkipPhaseError("Tryb SHADOW aktywny - faza sync NET→USB pominięta.")
        if not self.udc_name:
            raise SkipPhaseError("Brak UDC na RPi - faza sync NET→USB pominięta.")

        sync_details = self.run_sync_probe("sync", file_count=3, include_usb_roundtrip=True)
        self.measurements["sync_net_to_usb_seconds"] = sync_details["duration_seconds"]
        return sync_details

    def phase_5_performance(self) -> dict[str, Any]:
        if self.shadow_enabled:
            raise SkipPhaseError("Tryb SHADOW aktywny - faza performance pominięta.")
        details: dict[str, Any] = {}
        self.switch_mode("NET")

        file_name = f"{self.run_prefix}_perf_upload.nc"
        local_file = self.create_local_file(
            file_name,
            [
                "%",
                "(Performance upload probe)",
                "G21",
                "G90",
                "G0 X1 Y1",
                "M30",
                "%",
            ],
        )

        upload_started = time.perf_counter()
        self.upload_file_via_webui(local_file)
        upload_seconds = round(time.perf_counter() - upload_started, 6)
        self.delete_files_via_webui([file_name])
        details["upload_seconds"] = upload_seconds

        switch_metrics: dict[str, Any] = {}
        if self.udc_name:
            switch_to_usb_started = time.perf_counter()
            self.switch_mode("USB")
            switch_metrics["net_to_usb_seconds"] = round(
                time.perf_counter() - switch_to_usb_started,
                6,
            )

            switch_to_net_started = time.perf_counter()
            self.switch_mode("NET")
            switch_metrics["usb_to_net_seconds"] = round(
                time.perf_counter() - switch_to_net_started,
                6,
            )
        else:
            switch_metrics["status"] = "skipped_no_udc"
        details["switch_seconds"] = switch_metrics

        sync_perf = self.run_sync_probe(
            "perf_sync",
            file_count=2,
            include_usb_roundtrip=bool(self.udc_name),
        )
        details["sync_seconds"] = sync_perf["duration_seconds"]

        self.measurements.update(
            {
                "upload_seconds": upload_seconds,
                "sync_seconds": sync_perf["duration_seconds"],
            }
        )
        if "net_to_usb_seconds" in switch_metrics:
            self.measurements["switch_net_to_usb_seconds"] = switch_metrics[
                "net_to_usb_seconds"
            ]
        if "usb_to_net_seconds" in switch_metrics:
            self.measurements["switch_usb_to_net_seconds"] = switch_metrics[
                "usb_to_net_seconds"
            ]

        return details

    def phase_shadow_1_watcher(self) -> dict[str, Any]:
        if not self.shadow_enabled:
            raise SkipPhaseError("Tryb SHADOW nieaktywny - faza watchera SHADOW pominięta.")

        started = time.perf_counter()
        before_snapshot = self.fetch_shadow_snapshot()

        file_name = f"{self.run_prefix}_shadow_watch_probe.nc"
        local_file = self.create_local_file(
            file_name,
            [
                "%",
                "(SHADOW watcher probe)",
                "G21",
                "G90",
                "G0 X10 Y10",
                "M30",
                "%",
            ],
        )
        self.upload_file_via_webui(local_file)
        wait_result = self.wait_for_shadow_rebuild(
            previous_run_id=before_snapshot["run_id"],
            expected_trigger="watch",
            timeout_seconds=self.args.switch_timeout,
        )
        duration = round(time.perf_counter() - started, 6)
        self.measurements["shadow_watcher_seconds"] = duration

        return {
            "file": file_name,
            "before": before_snapshot,
            "after": wait_result["snapshot"],
            "history_entry": wait_result["history_entry"],
            "duration_seconds": duration,
        }

    def phase_shadow_2_sync_files(self) -> dict[str, Any]:
        if not self.shadow_enabled:
            raise SkipPhaseError("Tryb SHADOW nieaktywny - faza synchronizacji SHADOW pominięta.")
        if not self.shadow_master_dir:
            raise RuntimeError("Brak katalogu CNC_MASTER_DIR dla fazy synchronizacji SHADOW.")

        started = time.perf_counter()
        before_snapshot = self.fetch_shadow_snapshot()

        file_names: list[str] = []
        for index in range(1, 4):
            file_name = f"{self.run_prefix}_shadow_sync_probe_{index:02d}.nc"
            local_file = self.create_local_file(
                file_name,
                [
                    "%",
                    f"(SHADOW sync probe {index})",
                    "G21",
                    "G90",
                    f"G1 X{index * 3} Y{index * 5} F900",
                    "M30",
                    "%",
                ],
            )
            self.upload_file_via_webui(local_file)
            file_names.append(file_name)

        wait_result = self.wait_for_shadow_rebuild(
            previous_run_id=before_snapshot["run_id"],
            expected_trigger="watch",
            timeout_seconds=self.args.switch_timeout,
        )

        runtime_mapping = self.read_shadow_runtime_mapping()
        expected_image_path = runtime_mapping["expected_image_path"]
        runtime_lun_path = runtime_mapping["runtime_lun_path"]
        if runtime_lun_path != expected_image_path:
            raise RuntimeError(
                "Niezgodnosc runtime LUN i aktywnego slotu SHADOW: "
                f"runtime={runtime_lun_path}, expected={expected_image_path}"
            )

        master_checksums = self.remote_checksums_for_directory(
            self.shadow_master_dir,
            file_names,
        )
        if set(master_checksums) != set(file_names):
            raise RuntimeError(
                "Brak pelnych checksum dla katalogu SHADOW master: "
                f"expected={sorted(file_names)}, got={sorted(master_checksums)}"
            )

        image_payload = self.shadow_image_checksums(expected_image_path, file_names)
        image_checksums = image_payload["checksums"]
        if set(image_checksums) != set(file_names):
            raise RuntimeError(
                "Brak pelnych checksum dla obrazu SHADOW slotu aktywnego: "
                f"expected={sorted(file_names)}, got={sorted(image_checksums)}"
            )
        if image_checksums != master_checksums:
            raise RuntimeError(
                "Niezgodnosc synchronizacji SHADOW (master vs slot aktywny): "
                f"master={master_checksums}, image={image_checksums}, errors={image_payload['errors']}"
            )

        duration = round(time.perf_counter() - started, 6)
        self.measurements["shadow_sync_seconds"] = duration

        return {
            "files": file_names,
            "before": before_snapshot,
            "after": wait_result["snapshot"],
            "history_entry": wait_result["history_entry"],
            "runtime_mapping": runtime_mapping,
            "checksums_master": master_checksums,
            "checksums_active_slot": image_checksums,
            "duration_seconds": duration,
        }

    def phase_shadow_3_gcode_runtime(self) -> dict[str, Any]:
        if not self.shadow_enabled:
            raise SkipPhaseError("Tryb SHADOW nieaktywny - faza G-code SHADOW pominięta.")

        started = time.perf_counter()
        before_snapshot = self.fetch_shadow_snapshot()

        file_name = f"{self.run_prefix}_shadow_runtime_gcode.nc"
        local_file = self.create_local_file(
            file_name,
            [
                "%",
                "(SHADOW runtime G-code probe)",
                "G21",
                "G90",
                "G0 X0 Y0",
                "G1 X12.5 Y8.5 F1200",
                "M30",
                "%",
            ],
        )
        expected_sha256 = sha256_file(local_file)
        self.upload_file_via_webui(local_file)

        wait_result = self.wait_for_shadow_rebuild(
            previous_run_id=before_snapshot["run_id"],
            expected_trigger="watch",
            timeout_seconds=self.args.switch_timeout,
        )

        runtime_mapping = self.read_shadow_runtime_mapping()
        expected_image_path = runtime_mapping["expected_image_path"]
        runtime_lun_path = runtime_mapping["runtime_lun_path"]
        if runtime_lun_path != expected_image_path:
            raise RuntimeError(
                "Plik G-code nie jest eksponowany z aktywnego slotu SHADOW: "
                f"runtime={runtime_lun_path}, expected={expected_image_path}"
            )

        image_payload = self.shadow_image_checksums(runtime_lun_path, [file_name])
        image_checksums = image_payload["checksums"]
        observed_sha256 = image_checksums.get(file_name)
        if observed_sha256 != expected_sha256:
            raise RuntimeError(
                "Niezgodnosc G-code w runtime LUN SHADOW: "
                f"expected={expected_sha256}, observed={observed_sha256}, "
                f"errors={image_payload['errors']}"
            )

        host_read: dict[str, Any] = {
            "enabled": bool(self.args.usb_host_mount),
            "reason": "usb_host_mount_not_set" if not self.args.usb_host_mount else "",
        }
        if self.args.usb_host_mount:
            host_read = self.wait_for_usb_host_shadow_file(file_name, expected_sha256)

        duration = round(time.perf_counter() - started, 6)
        self.measurements["shadow_gcode_runtime_seconds"] = duration

        return {
            "file": file_name,
            "expected_sha256": expected_sha256,
            "observed_sha256": observed_sha256,
            "before": before_snapshot,
            "after": wait_result["snapshot"],
            "history_entry": wait_result["history_entry"],
            "runtime_mapping": runtime_mapping,
            "usb_host_read": host_read,
            "duration_seconds": duration,
        }

    def phase_6_cleanup(self) -> dict[str, Any]:
        errors: list[str] = []
        details: dict[str, Any] = {
            "leftover_webui_files_before": sorted(self.created_files),
            "leftover_smb_files_before": sorted(self.smb_created_files),
            "shadow_enabled": self.shadow_enabled,
        }

        if self.preflight_ok and not self.shadow_enabled:
            try:
                self.safe_switch_mode_net()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"switch_net: {exc}")

        if self.preflight_ok and self.created_files:
            names = sorted(self.created_files)
            try:
                self.delete_files_via_webui(names)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"delete_webui: {exc}")

        if self.preflight_ok and self.created_files and self.upload_dir:
            try:
                escaped_names = " ".join(shlex.quote(name) for name in self.created_files)
                self.ssh_exec(
                    f"cd {shlex.quote(self.upload_dir)} && rm -f -- {escaped_names}",
                    check=False,
                )
                self.created_files.clear()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"delete_ssh: {exc}")

        if self.preflight_ok and self.smb_created_files and self.args.smb_share:
            try:
                connection, _meta = self.open_smb_connection()
                try:
                    for file_name in list(self.smb_created_files):
                        try:
                            connection.deleteFiles(self.args.smb_share, file_name)
                        except Exception:  # noqa: BLE001
                            continue
                        self.smb_created_files.discard(file_name)
                finally:
                    connection.close()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"delete_smb: {exc}")

        details["leftover_webui_files_after"] = sorted(self.created_files)
        details["leftover_smb_files_after"] = sorted(self.smb_created_files)

        if errors:
            details["errors"] = errors
            raise RuntimeError("; ".join(errors))

        return details

    def ensure_requests_session(self) -> None:
        if self.session is not None:
            return
        try:
            import requests
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Missing dependency: requests. Install with: pip install requests"
            ) from exc
        self.session = requests.Session()

    def connect_ssh(self) -> None:
        if self.ssh_client is not None:
            return

        try:
            import paramiko
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency: paramiko. Install with: pip install paramiko"
            ) from exc

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict[str, Any] = {
            "hostname": self.args.host,
            "port": self.args.ssh_port,
            "username": self.args.ssh_user,
            "timeout": self.args.ssh_timeout,
            "banner_timeout": self.args.ssh_timeout,
            "auth_timeout": self.args.ssh_timeout,
            "look_for_keys": self.args.ssh_key is None and self.args.ssh_pass is None,
            "allow_agent": self.args.ssh_key is None and self.args.ssh_pass is None,
        }
        if self.args.ssh_key:
            connect_kwargs["key_filename"] = str(Path(self.args.ssh_key).expanduser())
        if self.args.ssh_pass:
            connect_kwargs["password"] = self.args.ssh_pass

        client.connect(**connect_kwargs)
        self.ssh_client = client

    def ssh_exec(
        self,
        command: str,
        *,
        timeout: float | None = None,
        check: bool,
    ) -> dict[str, Any]:
        if self.ssh_client is None:
            raise RuntimeError("SSH client is not connected.")

        wrapped = f"bash -lc {shlex.quote(command)}"
        stdin, stdout, stderr = self.ssh_client.exec_command(
            wrapped,
            timeout=timeout or self.args.ssh_timeout,
        )
        stdin.close()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_status = stdout.channel.recv_exit_status()

        result = {
            "command": command,
            "exit_status": exit_status,
            "stdout": out.strip(),
            "stderr": err.strip(),
        }

        if check and exit_status != 0:
            raise RuntimeError(
                f"SSH command failed (rc={exit_status}): {command}; stderr={result['stderr']}"
            )
        return result

    def read_remote_env(self) -> dict[str, str]:
        primary = self.ssh_exec("cat /etc/cnc-control/cnc-control.env", check=False)
        if primary["exit_status"] != 0:
            fallback = self.ssh_exec(
                "sudo -n cat /etc/cnc-control/cnc-control.env",
                check=False,
            )
            if fallback["exit_status"] != 0:
                raise RuntimeError(
                    "Nie można odczytać /etc/cnc-control/cnc-control.env przez SSH."
                )
            primary = fallback

        parsed = parse_env_text(primary["stdout"])
        if not parsed:
            raise RuntimeError("Plik /etc/cnc-control/cnc-control.env jest pusty lub niepoprawny.")
        return parsed

    def fetch_api_status(self) -> dict[str, Any]:
        self.ensure_requests_session()
        assert self.session is not None
        response = self.session.get(
            urljoin(self.webui_url + "/", "api/status"),
            timeout=self.args.http_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Nieprawidłowa odpowiedź JSON z /api/status.")
        return payload

    def fetch_shadow_history(self, limit: int = 20) -> list[dict[str, Any]]:
        self.ensure_requests_session()
        assert self.session is not None

        response = self.session.get(
            urljoin(self.webui_url + "/", "api/shadow/history"),
            params={"limit": str(limit)},
            timeout=self.args.http_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Nieprawidłowa odpowiedź JSON z /api/shadow/history.")
        history = payload.get("history")
        if not isinstance(history, list):
            raise RuntimeError("Brak listy history w odpowiedzi /api/shadow/history.")
        return [entry for entry in history if isinstance(entry, dict)]

    def fetch_shadow_snapshot(self) -> dict[str, Any]:
        payload = self.fetch_api_status()
        mode = str(payload.get("mode") or "").upper()
        if mode != "SHADOW":
            raise RuntimeError(f"Oczekiwano trybu SHADOW, otrzymano: {mode or 'UNKNOWN'}")
        shadow_state = payload.get("shadow_state")
        if not isinstance(shadow_state, dict):
            raise RuntimeError("Brak shadow_state w odpowiedzi /api/status.")
        try:
            run_id = int(shadow_state.get("run_id", 0))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Nieprawidłowy run_id w shadow_state: {shadow_state.get('run_id')}"
            ) from exc
        fsm_state = str(shadow_state.get("fsm_state") or "UNKNOWN").upper()
        return {
            "mode": mode,
            "run_id": run_id,
            "fsm_state": fsm_state,
            "shadow_state": shadow_state,
            "switching": bool(payload.get("switching")),
            "api_status": payload,
        }

    def wait_for_shadow_rebuild(
        self,
        *,
        previous_run_id: int,
        expected_trigger: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        poll_interval = 1.5
        expected_trigger_norm = expected_trigger.strip().casefold()
        last_snapshot: dict[str, Any] | None = None
        last_history: list[dict[str, Any]] = []

        while time.monotonic() < deadline:
            snapshot = self.fetch_shadow_snapshot()
            last_snapshot = snapshot
            try:
                history = self.fetch_shadow_history(limit=20)
            except Exception:
                history = []
            last_history = history

            candidate_entry: dict[str, Any] | None = None
            candidate_run_id = -1
            for entry in history:
                trigger = str(entry.get("trigger") or "").casefold()
                if trigger != expected_trigger_norm:
                    continue
                try:
                    run_id = int(entry.get("run_id", -1))
                except (TypeError, ValueError):
                    continue
                if run_id <= previous_run_id:
                    continue
                if run_id > candidate_run_id:
                    candidate_run_id = run_id
                    candidate_entry = entry

            if candidate_entry is not None:
                entry_result = str(candidate_entry.get("result") or "").casefold()
                if entry_result != "ok":
                    raise RuntimeError(
                        "SHADOW rebuild zakonczony bledem: "
                        f"trigger={expected_trigger}, entry={candidate_entry}"
                    )
                if (
                    snapshot["run_id"] >= candidate_run_id
                    and snapshot["fsm_state"] == "READY"
                ):
                    return {
                        "snapshot": snapshot,
                        "history_entry": candidate_entry,
                    }

            time.sleep(poll_interval)

        history_preview = [entry for entry in last_history[:3]]
        raise RuntimeError(
            "Timeout oczekiwania na rebuild SHADOW "
            f"(trigger={expected_trigger}, previous_run_id={previous_run_id}, "
            f"last_snapshot={last_snapshot}, history_preview={history_preview})"
        )

    def extract_redirect_message(self, response: Any) -> str:
        location = response.headers.get("Location", "")
        if not location:
            return ""
        query = parse_qs(urlparse(location).query)
        return (query.get("msg") or [""])[0]

    def wait_for_mode(self, expected_mode: str, timeout_seconds: float = 60.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        last_payload: dict[str, Any] | None = None
        last_error = ""

        while time.monotonic() < deadline:
            try:
                payload = self.fetch_api_status()
                last_payload = payload
                mode = str(payload.get("mode") or "").upper()
                if mode == expected_mode:
                    return payload
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
            time.sleep(1.5)

        if last_payload is not None:
            raise RuntimeError(
                f"Timeout oczekiwania na tryb {expected_mode}; ostatni status: {last_payload}"
            )
        raise RuntimeError(
            f"Timeout oczekiwania na tryb {expected_mode}; błąd: {last_error or 'unknown'}"
        )

    def switch_mode(self, target_mode: str) -> dict[str, Any]:
        self.ensure_requests_session()
        assert self.session is not None

        endpoint = "net" if target_mode == "NET" else "usb"
        self.log_console(f"MODE SWITCH: request {target_mode} via /{endpoint}")
        started = time.perf_counter()

        response = self.session.post(
            urljoin(self.webui_url + "/", endpoint),
            timeout=self.args.http_timeout,
            allow_redirects=False,
        )

        if response.status_code not in {302, 303}:
            raise RuntimeError(
                f"Przełączenie {target_mode} zwróciło HTTP {response.status_code}."
            )

        redirect_message = self.extract_redirect_message(response)
        api_status = self.wait_for_mode(target_mode, timeout_seconds=self.args.switch_timeout)
        duration = round(time.perf_counter() - started, 6)
        self.log_console(f"MODE SWITCH: {target_mode} ready in {duration:.3f}s")

        return {
            "target_mode": target_mode,
            "http_status": response.status_code,
            "redirect_message": redirect_message,
            "api_status": api_status,
            "duration_seconds": duration,
        }

    def safe_switch_mode_net(self) -> None:
        if self.shadow_enabled:
            return
        try:
            status = self.fetch_api_status()
            current_mode = str(status.get("mode") or "").upper()
            if current_mode == "NET":
                return
        except Exception:  # noqa: BLE001
            pass
        self.switch_mode("NET")

    def create_local_file(self, name: str, lines: list[str]) -> Path:
        path = self.local_temp_dir / name
        content = "\n".join(lines) + "\n"
        path.write_text(content, encoding="utf-8")
        return path

    def upload_file_via_webui(self, local_file: Path) -> dict[str, Any]:
        self.ensure_requests_session()
        assert self.session is not None

        with local_file.open("rb") as handle:
            response = self.session.post(
                urljoin(self.webui_url + "/", "upload"),
                files={"file": (local_file.name, handle)},
                timeout=self.args.http_timeout,
                allow_redirects=False,
            )

        if response.status_code not in {302, 303}:
            raise RuntimeError(
                f"Upload {local_file.name} zwrócił HTTP {response.status_code}."
            )

        message = self.extract_redirect_message(response)
        self.created_files.add(local_file.name)
        return {
            "file": local_file.name,
            "http_status": response.status_code,
            "redirect_message": message,
        }

    def upload_files_via_webui(self, count: int, label: str) -> list[str]:
        uploaded: list[str] = []
        for index in range(1, count + 1):
            file_name = f"{self.run_prefix}_{label}_{index:02d}.nc"
            local_file = self.create_local_file(
                file_name,
                [
                    "%",
                    f"({label} file {index})",
                    "G90",
                    f"G0 X{index} Y{index}",
                    "M30",
                    "%",
                ],
            )
            self.upload_file_via_webui(local_file)
            uploaded.append(file_name)
        return uploaded

    def delete_files_via_webui(self, file_names: list[str]) -> dict[str, Any]:
        if not file_names:
            return {"deleted": []}

        self.ensure_requests_session()
        assert self.session is not None

        payload: list[tuple[str, str]] = [("confirm_delete", "yes")]
        payload.extend(("files", name) for name in file_names)

        response = self.session.post(
            urljoin(self.webui_url + "/", "delete-files"),
            data=payload,
            timeout=self.args.http_timeout,
            allow_redirects=False,
        )
        if response.status_code not in {302, 303}:
            raise RuntimeError(
                f"Delete files zwrócił HTTP {response.status_code}."
            )

        message = self.extract_redirect_message(response)
        lowered = message.casefold()
        if "nie udalo" in lowered or "bled" in lowered:
            raise RuntimeError(f"WebUI delete zwrócił błąd: {message}")

        for name in file_names:
            self.created_files.discard(name)

        return {
            "deleted": sorted(file_names),
            "http_status": response.status_code,
            "redirect_message": message,
        }

    def remote_list_files(self, directory: str | None) -> list[str]:
        if not directory:
            return []
        script = (
            "python3 - <<'PY'\n"
            "import json\n"
            "from pathlib import Path\n"
            f"root = Path({directory!r})\n"
            "files = []\n"
            "if root.is_dir():\n"
            "    files = sorted(\n"
            "        [p.name for p in root.iterdir() if p.is_file() and not p.name.startswith('.')],\n"
            "        key=str.casefold,\n"
            "    )\n"
            "print(json.dumps(files, ensure_ascii=True))\n"
            "PY"
        )
        result = self.ssh_exec(script, check=True)
        parsed = json.loads(result["stdout"] or "[]")
        if not isinstance(parsed, list):
            raise RuntimeError("Nieprawidłowy JSON listy plików z RPi.")
        return [str(item) for item in parsed]

    def remote_checksums(self, names: list[str]) -> dict[str, str]:
        return self.remote_checksums_for_directory(self.upload_dir, names)

    def remote_checksums_for_directory(
        self,
        directory: str | None,
        names: list[str],
    ) -> dict[str, str]:
        if not directory:
            return {}
        wanted_literal = repr(sorted(names))
        script = (
            "python3 - <<'PY'\n"
            "import hashlib\n"
            "import json\n"
            "from pathlib import Path\n"
            f"root = Path({directory!r})\n"
            f"wanted = set({wanted_literal})\n"
            "payload = {}\n"
            "if root.is_dir():\n"
            "    for path in sorted(root.iterdir(), key=lambda p: p.name.casefold()):\n"
            "        if not path.is_file():\n"
            "            continue\n"
            "        if path.name not in wanted:\n"
            "            continue\n"
            "        digest = hashlib.sha256(path.read_bytes()).hexdigest()\n"
            "        payload[path.name] = digest\n"
            "print(json.dumps(payload, ensure_ascii=True, sort_keys=True))\n"
            "PY"
        )
        result = self.ssh_exec(script, check=True)
        parsed = json.loads(result["stdout"] or "{}")
        if not isinstance(parsed, dict):
            raise RuntimeError("Nieprawidłowy JSON checksum z RPi.")
        return {str(k): str(v) for k, v in parsed.items()}

    def read_shadow_runtime_mapping(self) -> dict[str, str]:
        env_payload = self.remote_env or self.read_remote_env()
        slot_file = env_payload.get("CNC_ACTIVE_SLOT_FILE") or "/var/lib/cnc-control/shadow_active_slot.state"
        image_a = env_payload.get("CNC_USB_IMG_A") or "/var/lib/cnc-control/cnc_usb_a.img"
        image_b = env_payload.get("CNC_USB_IMG_B") or "/var/lib/cnc-control/cnc_usb_b.img"

        script = (
            "python3 - <<'PY'\n"
            "import json\n"
            "from pathlib import Path\n"
            f"slot_file = Path({slot_file!r})\n"
            f"image_a = {image_a!r}\n"
            f"image_b = {image_b!r}\n"
            "runtime_file = Path('/sys/module/g_mass_storage/parameters/file')\n"
            "slot_raw = ''\n"
            "if slot_file.exists():\n"
            "    slot_raw = slot_file.read_text(encoding='utf-8', errors='replace').strip()\n"
            "slot = slot_raw.upper()\n"
            "if slot == 'A':\n"
            "    expected = image_a\n"
            "elif slot == 'B':\n"
            "    expected = image_b\n"
            "else:\n"
            "    expected = ''\n"
            "runtime = ''\n"
            "if runtime_file.exists():\n"
            "    runtime = runtime_file.read_text(encoding='utf-8', errors='replace').strip()\n"
            "print(json.dumps({\n"
            "    'slot_file': str(slot_file),\n"
            "    'active_slot': slot,\n"
            "    'image_a': image_a,\n"
            "    'image_b': image_b,\n"
            "    'expected_image_path': expected,\n"
            "    'runtime_lun_path': runtime,\n"
            "}, ensure_ascii=True))\n"
            "PY"
        )
        result = self.ssh_exec(script, check=True)
        payload = json.loads(result["stdout"] or "{}")
        if not isinstance(payload, dict):
            raise RuntimeError("Nieprawidlowy JSON mapowania runtime SHADOW.")
        active_slot = str(payload.get("active_slot") or "")
        expected_path = str(payload.get("expected_image_path") or "")
        runtime_path = str(payload.get("runtime_lun_path") or "")
        if active_slot not in {"A", "B"}:
            raise RuntimeError(f"Nieprawidlowa wartosc aktywnego slotu SHADOW: {active_slot!r}")
        if not expected_path:
            raise RuntimeError("Brak expected_image_path dla aktywnego slotu SHADOW.")
        if not runtime_path:
            raise RuntimeError("Brak runtime_lun_path dla SHADOW.")
        return {
            "slot_file": str(payload.get("slot_file") or slot_file),
            "active_slot": active_slot,
            "image_a": str(payload.get("image_a") or image_a),
            "image_b": str(payload.get("image_b") or image_b),
            "expected_image_path": expected_path,
            "runtime_lun_path": runtime_path,
        }

    def shadow_image_checksums(self, image_path: str, names: list[str]) -> dict[str, dict[str, str]]:
        files_literal = repr(sorted(names))
        script = (
            "python3 - <<'PY'\n"
            "import hashlib\n"
            "import json\n"
            "import os\n"
            "import subprocess\n"
            "import tempfile\n"
            f"image_path = {image_path!r}\n"
            f"names = {files_literal}\n"
            "checksums = {}\n"
            "errors = {}\n"
            "for name in names:\n"
            "    temp_path = ''\n"
            "    try:\n"
            "        with tempfile.NamedTemporaryFile(prefix='cnc-shadow-', delete=False) as tmp:\n"
            "            temp_path = tmp.name\n"
            "        result = subprocess.run(\n"
            "            ['mcopy', '-n', '-i', image_path, f'::{name}', temp_path],\n"
            "            capture_output=True,\n"
            "            text=True,\n"
            "            check=False,\n"
            "        )\n"
            "        if result.returncode != 0:\n"
            "            detail = (result.stderr or result.stdout or '').strip()\n"
            "            errors[name] = detail or f'mcopy rc={result.returncode}'\n"
            "            continue\n"
            "        digest = hashlib.sha256()\n"
            "        with open(temp_path, 'rb') as handle:\n"
            "            while True:\n"
            "                chunk = handle.read(1024 * 1024)\n"
            "                if not chunk:\n"
            "                    break\n"
            "                digest.update(chunk)\n"
            "        checksums[name] = digest.hexdigest()\n"
            "    finally:\n"
            "        if temp_path and os.path.exists(temp_path):\n"
            "            os.unlink(temp_path)\n"
            "print(json.dumps({'checksums': checksums, 'errors': errors}, ensure_ascii=True, sort_keys=True))\n"
            "PY"
        )
        result = self.ssh_exec(script, check=True)
        payload = json.loads(result["stdout"] or "{}")
        if not isinstance(payload, dict):
            raise RuntimeError("Nieprawidlowy JSON checksum obrazu SHADOW.")
        raw_checksums = payload.get("checksums")
        raw_errors = payload.get("errors")
        if not isinstance(raw_checksums, dict) or not isinstance(raw_errors, dict):
            raise RuntimeError("Brak map checksums/errors w odpowiedzi checksum obrazu SHADOW.")
        checksums = {str(name): str(value) for name, value in raw_checksums.items()}
        errors = {str(name): str(value) for name, value in raw_errors.items()}
        return {
            "checksums": checksums,
            "errors": errors,
        }

    def wait_for_usb_host_shadow_file(self, file_name: str, expected_sha256: str) -> dict[str, Any]:
        if not self.args.usb_host_mount:
            raise RuntimeError("Brak --usb-host-mount dla testu runtime SHADOW.")

        host_mount = Path(self.args.usb_host_mount).expanduser()
        if not host_mount.exists() or not host_mount.is_dir():
            raise RuntimeError(
                f"Nieprawidlowy --usb-host-mount: {host_mount} (wymagany istniejacy katalog)."
            )

        probe_path = host_mount / file_name
        started = time.monotonic()
        deadline = started + self.args.usb_host_read_timeout
        while time.monotonic() < deadline:
            if probe_path.is_file():
                break
            time.sleep(0.5)

        if not probe_path.is_file():
            preview_entries = sorted(
                [entry.name for entry in host_mount.iterdir() if not entry.name.startswith(".")],
                key=str.casefold,
            )[:20]
            raise RuntimeError(
                "Plik G-code SHADOW nie jest widoczny po stronie hosta USB "
                f"w czasie {self.args.usb_host_read_timeout}s: {probe_path}; "
                f"entries_preview={preview_entries}"
            )

        observed_sha256 = sha256_file(probe_path)
        if observed_sha256 != expected_sha256:
            raise RuntimeError(
                "Niezgodnosc SHA256 dla G-code SHADOW po stronie hosta USB: "
                f"expected={expected_sha256}, observed={observed_sha256}, file={probe_path}"
            )

        return {
            "enabled": True,
            "host_mount": str(host_mount),
            "file": file_name,
            "path": str(probe_path),
            "expected_sha256": expected_sha256,
            "observed_sha256": observed_sha256,
            "wait_seconds": round(time.monotonic() - started, 6),
        }

    def run_sync_probe(
        self,
        label: str,
        *,
        file_count: int,
        include_usb_roundtrip: bool,
    ) -> dict[str, Any]:
        self.switch_mode("NET")

        file_names = self.upload_files_via_webui(file_count, label)
        started = time.perf_counter()

        before = self.remote_checksums(file_names)
        if set(before) != set(file_names):
            raise RuntimeError("Nie udało się zebrać pełnych checksum przed sync.")

        switch_trace: dict[str, Any] = {}
        if include_usb_roundtrip:
            switch_trace["to_usb"] = self.switch_mode("USB")
            switch_trace["to_net"] = self.switch_mode("NET")

        after = self.remote_checksums(file_names)
        if before != after:
            raise RuntimeError(
                f"Niezgodność checksum po sync NET→USB: before={before}, after={after}"
            )

        self.delete_files_via_webui(file_names)
        duration = round(time.perf_counter() - started, 6)

        return {
            "files": file_names,
            "checksums_before": before,
            "checksums_after": after,
            "include_usb_roundtrip": include_usb_roundtrip,
            "switch_trace": switch_trace,
            "duration_seconds": duration,
        }

    def open_smb_connection(self) -> tuple[Any, dict[str, Any]]:
        try:
            from smb.SMBConnection import SMBConnection
            from smb import smb_structs
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency: pysmb. Install with: pip install pysmb"
            ) from exc

        smb_structs.SUPPORT_SMB2 = True

        host = self.args.smb_host or self.args.host
        user = self.args.smb_user or self.args.ssh_user
        password = self.args.smb_pass
        if password is None:
            password = self.args.ssh_pass or ""

        server_name = self.args.smb_server_name or host

        connection = SMBConnection(
            username=user,
            password=password,
            my_name=self.args.smb_client_name,
            remote_name=server_name,
            domain=self.args.smb_domain,
            use_ntlm_v2=True,
            is_direct_tcp=True,
        )

        connected = connection.connect(
            ip=host,
            port=self.args.smb_port,
            timeout=self.args.smb_timeout,
        )
        if not connected:
            raise RuntimeError("Połączenie SMB odrzucone.")

        return connection, {
            "host": host,
            "port": self.args.smb_port,
            "share": self.args.smb_share,
            "user": user,
            "server_name": server_name,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run staged integration checks against Raspberry Pi CNC Control "
            "(preflight, NET/WebUI, SMB, USB, USB host-read, sync, performance)."
        )
    )
    parser.add_argument(
        "--mode",
        choices=(
            "all",
            "preflight",
            "net",
            "smb",
            "usb",
            "sync",
            "perf",
            "shadow",
            "ssh",
        ),
        default="all",
        help="Run selected phase set.",
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

    # PL: Parametry SSH do sterowania i diagnostyki Raspberry Pi.
    # EN: SSH parameters for Raspberry Pi control and diagnostics.
    parser.add_argument("--host", "--ssh-host", required=True, help="Raspberry Pi host/IP.")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH port.")
    parser.add_argument("--ssh-user", required=True, help="SSH username.")
    auth_group = parser.add_mutually_exclusive_group(required=True)
    auth_group.add_argument("--ssh-key", "--ssh-key-file", help="Path to SSH private key.")
    auth_group.add_argument("--ssh-pass", "--ssh-password", help="SSH password.")
    parser.add_argument(
        "--ssh-timeout",
        type=float,
        default=15.0,
        help="SSH timeout in seconds.",
    )

    parser.add_argument(
        "--webui-url",
        help="WebUI base URL (default: http://<host>:8080).",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=20.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--switch-timeout",
        type=float,
        default=90.0,
        help="Timeout waiting for NET/USB switch completion.",
    )
    parser.add_argument(
        "--skip-remote-refresh",
        action="store_true",
        help=(
            "Skip remote CI refresh stage in preflight "
            "(git pull, pip install, setup_* services, selftest, systemd checks)."
        ),
    )
    parser.add_argument(
        "--remote-refresh-timeout",
        type=float,
        default=300.0,
        help="Timeout in seconds for remote refresh commands.",
    )
    parser.add_argument(
        "--remote-selftest-timeout",
        type=float,
        default=180.0,
        help="Timeout in seconds for remote cnc_selftest execution.",
    )
    parser.add_argument(
        "--disable-selftest-auto-repair",
        action="store_true",
        help=(
            "Disable automatic one-shot selftest repair for SHADOW runtime LUN mismatch "
            "(Runtime LUN image matches expected)."
        ),
    )

    # PL: Parametry SMB do testu zapisu/usuwania przez udział sieciowy.
    # EN: SMB parameters for write/delete checks over network share.
    parser.add_argument("--smb-share", help="SMB share name (e.g. cnc_usb).")
    parser.add_argument("--smb-host", help="SMB host/IP (default: --host).")
    parser.add_argument("--smb-port", type=int, default=445, help="SMB port.")
    parser.add_argument("--smb-user", help="SMB username (default: --ssh-user).")
    parser.add_argument("--smb-pass", help="SMB password (default: --ssh-pass).")
    parser.add_argument("--smb-domain", default="", help="SMB domain/workgroup.")
    parser.add_argument(
        "--smb-client-name",
        default=socket.gethostname(),
        help="Client name used by SMB negotiation.",
    )
    parser.add_argument(
        "--smb-server-name",
        help="Server NetBIOS name (default: SMB host).",
    )
    parser.add_argument(
        "--smb-timeout",
        type=float,
        default=15.0,
        help="SMB timeout in seconds.",
    )
    # PL: Parametry lokalnego odczytu host-side z emulowanej pamięci USB.
    # EN: Parameters for local host-side read checks from emulated USB storage.
    parser.add_argument(
        "--usb-host-mount",
        help=(
            "Local mount path of USB gadget storage on DEV machine "
            "(e.g. /Volumes/CNC_USB). Enables direct host read in phase_3_usb."
        ),
    )
    parser.add_argument(
        "--usb-host-read-timeout",
        type=float,
        default=25.0,
        help="Timeout in seconds waiting for probe file visibility on USB host mount.",
    )

    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> list[str]:
    errors: list[str] = []

    if args.mode in {"all", "smb"} and not args.smb_share:
        errors.append("Missing --smb-share for mode 'all' or 'smb'.")
    if args.usb_host_read_timeout <= 0:
        errors.append("--usb-host-read-timeout must be > 0.")
    if args.usb_host_mount:
        mount_path = Path(args.usb_host_mount).expanduser()
        if not mount_path.exists():
            errors.append(f"USB host mount path does not exist: {mount_path}")
        elif not mount_path.is_dir():
            errors.append(f"USB host mount path is not a directory: {mount_path}")

    return errors


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

    runner = Runner(args)
    try:
        runner.run()
    finally:
        runner.close()

    report = Report(
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        selected_mode=args.mode,
        target={
            "host": args.host,
            "ssh_user": args.ssh_user,
            "webui_url": runner.webui_url,
            "smb_share": args.smb_share,
            "usb_host_mount": args.usb_host_mount,
        },
        platform={
            "system": platform.system(),
            "release": platform.release(),
            "python_version": platform.python_version(),
        },
        results=runner.results,
        measurements=runner.measurements,
    )

    report_path = Path(args.report)
    write_report(report, report_path)

    payload = report.to_dict()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    failed_count = payload["summary"]["failed"]
    return 1 if failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
