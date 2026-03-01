from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hostname_utils = load_module(
    REPO_ROOT / "webui" / "hostname_utils.py",
    "hostname_utils",
)


def test_normalize_static_hostname_converts_label_style_name() -> None:
    assert hostname_utils.normalize_static_hostname("CNC_USB") == "cnc-usb"


def test_normalize_static_hostname_removes_invalid_chars() -> None:
    assert hostname_utils.normalize_static_hostname("  CNC USB! #A11E  ") == "cnc-usb-a11e"


def test_normalize_static_hostname_rejects_empty_after_cleanup() -> None:
    assert hostname_utils.normalize_static_hostname("___---***") == ""


def test_normalize_static_hostname_rejects_too_long_value() -> None:
    assert hostname_utils.normalize_static_hostname("a" * 64) == ""


def test_normalize_pretty_hostname_keeps_user_facing_format() -> None:
    assert hostname_utils.normalize_pretty_hostname("  CNC_USB   TEST  ") == "CNC_USB TEST"
