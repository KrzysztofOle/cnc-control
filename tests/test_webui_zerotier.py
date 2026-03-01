from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBUI_DIR = REPO_ROOT / "webui"

if str(WEBUI_DIR) not in sys.path:
    sys.path.insert(0, str(WEBUI_DIR))


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


webui_app = load_module(WEBUI_DIR / "app.py", "webui_app_for_zerotier_tests")


def make_result(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_read_zerotier_state_handles_alias_enabled_state(monkeypatch) -> None:
    responses = iter(
        [
            (make_result(0, "active\n"), None),
            (make_result(0, "alias\n"), None),
        ]
    )

    monkeypatch.setattr(
        webui_app,
        "run_systemctl_command",
        lambda args, timeout=10: next(responses),
    )

    active, enabled, error = webui_app.read_zerotier_state()

    assert active is True
    assert enabled is True
    assert error is None


def test_read_zerotier_state_returns_missing_service_error(monkeypatch) -> None:
    responses = iter(
        [
            (make_result(3, "inactive\n"), None),
            (
                make_result(
                    1,
                    "",
                    "Failed to get unit file state for zerotier-one.service: "
                    "No such file or directory",
                ),
                None,
            ),
        ]
    )

    monkeypatch.setattr(
        webui_app,
        "run_systemctl_command",
        lambda args, timeout=10: next(responses),
    )

    active, enabled, error = webui_app.read_zerotier_state()

    assert active is None
    assert enabled is None
    assert error == "Brak usługi ZeroTier"


def test_api_zerotier_status_returns_200_when_service_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        webui_app,
        "read_zerotier_state",
        lambda: (None, None, "Brak usługi ZeroTier"),
    )
    client = webui_app.app.test_client()

    response = client.get("/api/zerotier")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["active"] is False
    assert payload["enabled"] is False
    assert payload["available"] is False
    assert payload["error"] == "Brak usługi ZeroTier"
