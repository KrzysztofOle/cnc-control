from __future__ import annotations

from pathlib import Path

import pytest

from shadow.rebuild_engine import RebuildConfig, RebuildEngine, RebuildError


def test_from_environment_uses_default_usb_label() -> None:
    engine = RebuildEngine.from_environment({})
    assert engine._config.usb_label == "CNC_USB"


def test_from_environment_rejects_too_long_usb_label() -> None:
    with pytest.raises(RebuildError, match="maksymalnie 11 znakow"):
        RebuildEngine.from_environment({"CNC_USB_LABEL": "TOO_LONG_LABEL"})


def test_full_rebuild_passes_usb_label_to_mkfs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_run_command(command, error_message: str) -> None:
        del error_message
        commands.append(list(command))

    monkeypatch.setattr(RebuildEngine, "_run_command", staticmethod(fake_run_command))
    monkeypatch.setattr(RebuildEngine, "_cleanup_tmp", staticmethod(lambda _path: None))
    monkeypatch.setattr(RebuildEngine, "_fsync_path", staticmethod(lambda _path: None))
    monkeypatch.setattr(RebuildEngine, "_list_master_entries", lambda self: [])
    monkeypatch.setattr("shadow.rebuild_engine.os.replace", lambda _src, _dst: None)

    master_dir = tmp_path / "master"
    master_dir.mkdir()
    target_path = tmp_path / "slot_a.img"

    engine = RebuildEngine(
        RebuildConfig(
            master_dir=str(master_dir),
            slot_size_mb=256,
            tmp_suffix=".tmp",
            usb_label="CNC_A11",
        )
    )
    engine.full_rebuild(str(target_path))

    assert len(commands) >= 2
    assert commands[1][0].endswith("mkfs.vfat")
    assert "-n" in commands[1]
    label_index = commands[1].index("-n") + 1
    assert commands[1][label_index] == "CNC_A11"
