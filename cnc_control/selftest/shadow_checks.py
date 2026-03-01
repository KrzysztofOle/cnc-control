from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .utils import run_root_command

DEFAULT_ENV_FILE = "/etc/cnc-control/cnc-control.env"
DEFAULT_VALIDATE_ROOT = "/run/cnc-shadow-validate"
ERR_MISSING_SUDO = "ERR_MISSING_SUDO"
ERR_FAT_INVALID = "ERR_FAT_INVALID"
ERR_REBUILD_TIMEOUT = "ERR_REBUILD_TIMEOUT"
ERR_LOCK_CONFLICT = "ERR_LOCK_CONFLICT"

SUDO_ERROR_MARKERS = (
    "a password is required",
    "permission denied",
    "sudo:",
)


@dataclass
class ShadowChecksResult:
    critical: int = 0
    warnings: int = 0
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
            "checks": self.checks,
        }


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
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
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _env_value(env: dict[str, str], key: str, default: str) -> str:
    value = env.get(key, default).strip()
    return value or default


def _is_missing_sudo(stderr: str) -> bool:
    haystack = stderr.casefold()
    return any(marker in haystack for marker in SUDO_ERROR_MARKERS)


def _error_detail(error_code: str, rc: int, stdout: str, stderr: str) -> str:
    output = (stderr or stdout or "").strip()
    if not output:
        output = "no output"
    return f"{error_code}; rc={rc}; {output}"


def _add_critical(result: ShadowChecksResult, *, name: str, status: str, detail: str) -> None:
    if status == "FAIL":
        result.critical += 1
    result.add_check(
        name=name,
        status=status,
        severity="CRITICAL",
        detail=detail,
    )


def _classify_mount_error(rc: int, stderr: str) -> str:
    if rc == 124:
        return ERR_REBUILD_TIMEOUT
    if _is_missing_sudo(stderr):
        return ERR_MISSING_SUDO
    return ERR_FAT_INVALID


def _classify_umount_error(rc: int, stderr: str) -> str:
    if rc == 124:
        return ERR_REBUILD_TIMEOUT
    if _is_missing_sudo(stderr):
        return ERR_MISSING_SUDO
    return ERR_LOCK_CONFLICT


def _check_mount_ro(
    *,
    result: ShadowChecksResult,
    image_path: Path,
    validate_root: Path,
) -> bool:
    mount_rc, mount_out, mount_err = run_root_command(
        [
            "mount",
            "-o",
            "ro,loop",
            str(image_path),
            str(validate_root),
        ]
    )
    if mount_rc != 0:
        error_code = _classify_mount_error(mount_rc, mount_err)
        _add_critical(
            result,
            name=f"Mount RO validation {image_path.name}",
            status="FAIL",
            detail=_error_detail(error_code, mount_rc, mount_out, mount_err),
        )
        return error_code == ERR_MISSING_SUDO

    umount_rc, umount_out, umount_err = run_root_command(["umount", str(validate_root)])
    if umount_rc != 0:
        error_code = _classify_umount_error(umount_rc, umount_err)
        _add_critical(
            result,
            name=f"Mount RO validation {image_path.name}",
            status="FAIL",
            detail=_error_detail(error_code, umount_rc, umount_out, umount_err),
        )
        return error_code == ERR_MISSING_SUDO

    _add_critical(
        result,
        name=f"Mount RO validation {image_path.name}",
        status="PASS",
        detail=f"Validated via {validate_root}",
    )
    return False


def run_shadow_checks(
    *,
    env_file: str = DEFAULT_ENV_FILE,
    validate_root: str = DEFAULT_VALIDATE_ROOT,
) -> ShadowChecksResult:
    result = ShadowChecksResult()

    env_path = Path(env_file)
    env = _parse_env_file(env_path)
    if not env:
        _add_critical(
            result,
            name="Environment file",
            status="FAIL",
            detail=f"Missing or empty env file: {env_file}",
        )
        return result

    master_dir = Path(_env_value(env, "CNC_MASTER_DIR", "/var/lib/cnc-control/master"))
    image_a = Path(_env_value(env, "CNC_USB_IMG_A", "/var/lib/cnc-control/cnc_usb_a.img"))
    image_b = Path(_env_value(env, "CNC_USB_IMG_B", "/var/lib/cnc-control/cnc_usb_b.img"))
    active_slot_file = Path(
        _env_value(
            env,
            "CNC_ACTIVE_SLOT_FILE",
            "/var/lib/cnc-control/shadow_active_slot.state",
        )
    )
    tmp_suffix = _env_value(env, "CNC_SHADOW_TMP_SUFFIX", ".tmp")
    validate_dir = Path(validate_root)

    if master_dir.is_dir():
        _add_critical(
            result,
            name="CNC_MASTER_DIR exists",
            status="PASS",
            detail=str(master_dir),
        )
    else:
        _add_critical(
            result,
            name="CNC_MASTER_DIR exists",
            status="FAIL",
            detail=f"Missing directory: {master_dir}",
        )

    slot_paths = {
        "A": image_a,
        "B": image_b,
    }
    for slot_name, slot_path in slot_paths.items():
        if slot_path.is_file():
            _add_critical(
                result,
                name=f"SHADOW slot {slot_name} exists",
                status="PASS",
                detail=str(slot_path),
            )
        else:
            _add_critical(
                result,
                name=f"SHADOW slot {slot_name} exists",
                status="FAIL",
                detail=f"Missing file: {slot_path}",
            )

    tmp_files = [Path(f"{image_a}{tmp_suffix}"), Path(f"{image_b}{tmp_suffix}")]
    found_tmp = [str(path) for path in tmp_files if path.exists()]
    if found_tmp:
        _add_critical(
            result,
            name="No stale .tmp files",
            status="FAIL",
            detail=", ".join(found_tmp),
        )
    else:
        _add_critical(
            result,
            name="No stale .tmp files",
            status="PASS",
            detail="No temporary slot artifacts",
        )

    root_blocked = False
    for slot_name, slot_path in slot_paths.items():
        if slot_path.is_file():
            missing_sudo = _check_mount_ro(
                result=result,
                image_path=slot_path,
                validate_root=validate_dir,
            )
            if missing_sudo:
                root_blocked = True
                break

    if active_slot_file.is_file():
        slot_value = active_slot_file.read_text(encoding="utf-8").strip().upper()
        if slot_value in {"A", "B"}:
            _add_critical(
                result,
                name="CNC_ACTIVE_SLOT_FILE valid",
                status="PASS",
                detail=f"{active_slot_file}: {slot_value}",
            )
        else:
            _add_critical(
                result,
                name="CNC_ACTIVE_SLOT_FILE valid",
                status="FAIL",
                detail=f"{active_slot_file}: invalid value '{slot_value}'",
            )
    else:
        _add_critical(
            result,
            name="CNC_ACTIVE_SLOT_FILE valid",
            status="FAIL",
            detail=f"Missing file: {active_slot_file}",
        )

    if root_blocked:
        result.add_check(
            name="Root command access",
            status="WARN",
            severity="WARN",
            detail="Skipped remaining root operations after ERR_MISSING_SUDO",
        )
        return result

    lsmod_rc, lsmod_out, lsmod_err = run_root_command(["lsmod"])
    if lsmod_rc != 0:
        error_code = ERR_MISSING_SUDO if _is_missing_sudo(lsmod_err) else ERR_LOCK_CONFLICT
        _add_critical(
            result,
            name="g_mass_storage loaded",
            status="FAIL",
            detail=_error_detail(error_code, lsmod_rc, lsmod_out, lsmod_err),
        )
    else:
        modules = {line.split()[0] for line in lsmod_out.splitlines() if line.split()}
        if "g_mass_storage" in modules:
            _add_critical(
                result,
                name="g_mass_storage loaded",
                status="PASS",
                detail="g_mass_storage",
            )
        else:
            _add_critical(
                result,
                name="g_mass_storage loaded",
                status="FAIL",
                detail="Module not present in lsmod",
            )

    return result
