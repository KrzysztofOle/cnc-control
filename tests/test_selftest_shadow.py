from __future__ import annotations

from pathlib import Path

from cnc_control.selftest.core import run_selftest
from cnc_control.selftest.journal import JournalCheckResult
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

    def fake_root_command(command: list[str], timeout: int = 10) -> tuple[int, str, str]:
        del timeout
        if command and command[0] == "lsmod":
            return 0, "g_mass_storage 0 0\n", ""
        return 0, "", ""

    monkeypatch.setattr("cnc_control.selftest.shadow_checks.run_root_command", fake_root_command)

    result = run_shadow_checks(
        env_file=str(env_file),
        validate_root=str(tmp_path / "validate"),
    )

    assert result.critical >= 1
    assert any(
        check["name"] == "SHADOW slot A exists" and check["status"] == "FAIL"
        for check in result.checks
    )


def test_missing_sudo_returns_critical(monkeypatch, tmp_path: Path) -> None:
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

    def fake_root_command(_command: list[str], timeout: int = 10) -> tuple[int, str, str]:
        del timeout
        return 1, "", "sudo: a password is required"

    monkeypatch.setattr("cnc_control.selftest.shadow_checks.run_root_command", fake_root_command)
    monkeypatch.setattr(
        "cnc_control.selftest.core.run_journal_checks",
        lambda: JournalCheckResult(critical=0, warnings=0, system_noise=0, checks=[]),
    )

    result = run_selftest(env_file=str(env_file))

    assert result.critical == 1
    assert result.status == "FAILED"
    shadow_checks = result.details["shadow"]["checks"]
    assert any("ERR_MISSING_SUDO" in check["detail"] for check in shadow_checks)
