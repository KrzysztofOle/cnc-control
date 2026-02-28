from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bootstrap_env = load_module(
    REPO_ROOT / "tools" / "bootstrap_env.py",
    "bootstrap_env",
)
test_runner = load_module(
    REPO_ROOT / "integration_tests" / "test_runner.py",
    "test_runner",
)


def test_validate_target_rejects_rpi_on_non_rpi_host() -> None:
    with pytest.raises(RuntimeError):
        bootstrap_env.validate_target("rpi", is_rpi_host=False, force=False)


def test_validate_target_allows_dev_on_non_rpi_host() -> None:
    bootstrap_env.validate_target("dev", is_rpi_host=False, force=False)


def test_runner_accepts_integration_target_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker_path = tmp_path / ".cnc_target"
    marker_path.write_text("integration\n", encoding="utf-8")

    monkeypatch.setattr(test_runner.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(test_runner.sys, "base_prefix", "/base-python")

    args = argparse.Namespace(skip_target_check=False)
    assert test_runner.validate_environment_target(args) == []


def test_runner_rejects_missing_target_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(test_runner.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(test_runner.sys, "base_prefix", "/base-python")

    args = argparse.Namespace(skip_target_check=False)
    errors = test_runner.validate_environment_target(args)
    assert len(errors) == 1
    assert "Missing environment marker" in errors[0]


def test_runner_validate_args_rejects_nonpositive_usb_host_timeout() -> None:
    args = argparse.Namespace(
        mode="usb",
        smb_share="cnc_usb",
        usb_host_mount=None,
        usb_host_read_timeout=0,
    )
    errors = test_runner.validate_args(args)
    assert "--usb-host-read-timeout must be > 0." in errors


def test_runner_validate_args_rejects_missing_usb_host_mount_path() -> None:
    args = argparse.Namespace(
        mode="usb",
        smb_share="cnc_usb",
        usb_host_mount="/tmp/this-path-should-not-exist-cnc-control",
        usb_host_read_timeout=25,
    )
    errors = test_runner.validate_args(args)
    assert any(error.startswith("USB host mount path does not exist:") for error in errors)


def test_runner_validate_args_shadow_mode_does_not_require_smb_share() -> None:
    args = argparse.Namespace(
        mode="shadow",
        smb_share=None,
        usb_host_mount=None,
        usb_host_read_timeout=25,
    )
    errors = test_runner.validate_args(args)
    assert errors == []
