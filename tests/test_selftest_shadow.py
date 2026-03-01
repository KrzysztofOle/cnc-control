from __future__ import annotations

import subprocess
from pathlib import Path

from cnc_control.selftest.shadow_checks import run_shadow_checks


def test_shadow_missing_slot_a_is_critical(monkeypatch, tmp_path: Path) -> None:
    master_dir = tmp_path / "master"
    master_dir.mkdir()

    slot_a = tmp_path / "cnc_usb_a.img"
    slot_b = tmp_path / "cnc_usb_b.img"
    slot_b.write_bytes(b"slot-b")

    active_slot_file = tmp_path / "shadow_active_slot.state"
    active_slot_file.write_text("B\n", encoding="utf-8")

    env_file = tmp_path / "cnc-control.env"
    env_file.write_text(
        "\n".join(
            [
                f"CNC_MASTER_DIR={master_dir}",
                f"CNC_USB_IMG_A={slot_a}",
                f"CNC_USB_IMG_B={slot_b}",
                f"CNC_ACTIVE_SLOT_FILE={active_slot_file}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_run(command, **_kwargs):
        if command and command[0] == "lsmod":
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="g_mass_storage 0 0\n",
                stderr="",
            )
        if command and command[0] == "sudo":
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr("cnc_control.selftest.shadow_checks.subprocess.run", fake_run)

    result = run_shadow_checks(
        env_file=str(env_file),
        validate_root=str(tmp_path / "validate"),
    )

    assert result.critical >= 1
    assert any(
        check["name"] == "SHADOW slot A exists" and check["status"] == "FAIL"
        for check in result.checks
    )


def test_shadow_mount_path_permission_error_is_critical(monkeypatch, tmp_path: Path) -> None:
    master_dir = tmp_path / "master"
    master_dir.mkdir()
    slot_a = tmp_path / "cnc_usb_a.img"
    slot_b = tmp_path / "cnc_usb_b.img"
    slot_a.write_bytes(b"slot-a")
    slot_b.write_bytes(b"slot-b")
    active_slot_file = tmp_path / "shadow_active_slot.state"
    active_slot_file.write_text("A\n", encoding="utf-8")

    env_file = tmp_path / "cnc-control.env"
    env_file.write_text(
        "\n".join(
            [
                f"CNC_MASTER_DIR={master_dir}",
                f"CNC_USB_IMG_A={slot_a}",
                f"CNC_USB_IMG_B={slot_b}",
                f"CNC_ACTIVE_SLOT_FILE={active_slot_file}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    original_mkdir = Path.mkdir

    def fake_mkdir(self: Path, *args, **kwargs):
        if "slot_a" in self.as_posix():
            raise PermissionError("permission denied")
        return original_mkdir(self, *args, **kwargs)

    def fake_run(command, **_kwargs):
        if command and command[0] == "lsmod":
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="g_mass_storage 0 0\n",
                stderr="",
            )
        if command and command[0] == "sudo":
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr("cnc_control.selftest.shadow_checks.Path.mkdir", fake_mkdir)
    monkeypatch.setattr("cnc_control.selftest.shadow_checks.subprocess.run", fake_run)

    result = run_shadow_checks(
        env_file=str(env_file),
        validate_root=str(tmp_path / "validate"),
    )

    assert any(
        check["name"] == "Mount RO validation cnc_usb_a.img" and check["status"] == "FAIL"
        for check in result.checks
    )
