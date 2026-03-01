from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBUI_APP_PATH = REPO_ROOT / "webui" / "app.py"


def parse_webui_ast() -> ast.Module:
    source = WEBUI_APP_PATH.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(WEBUI_APP_PATH))


def find_function_node(module: ast.Module, name: str) -> ast.FunctionDef:
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Missing function: {name}")


def iter_call_names(node: ast.AST):
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        called = child.func
        if isinstance(called, ast.Name):
            yield called.id
        elif isinstance(called, ast.Attribute):
            yield called.attr


def iter_name_ids(node: ast.AST):
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            yield child.id

def test_main_bootstrap_uses_only_shadow_mode() -> None:
    module = parse_webui_ast()
    joined_source = WEBUI_APP_PATH.read_text(encoding="utf-8")

    assert "def start_net_usb" not in joined_source
    assert "ModeSelector" not in joined_source
    assert "mode_selector" not in joined_source

    main_if_nodes = []
    for node in module.body:
        if not isinstance(node, ast.If):
            continue
        condition = node.test
        if not isinstance(condition, ast.Compare):
            continue
        if not isinstance(condition.left, ast.Name) or condition.left.id != "__name__":
            continue
        if not condition.comparators:
            continue
        comparator = condition.comparators[0]
        if not isinstance(comparator, ast.Constant) or comparator.value != "__main__":
            continue
        main_if_nodes.append(node)

    assert len(main_if_nodes) == 1
    main_calls = set(iter_call_names(main_if_nodes[0]))
    assert "start_shadow_mode" in main_calls
    assert "start_net_usb" not in main_calls


def test_start_shadow_mode_does_not_depend_on_env_flag() -> None:
    module = parse_webui_ast()
    start_shadow_mode = find_function_node(module, "start_shadow_mode")
    used_names = set(iter_name_ids(start_shadow_mode))
    called_names = set(iter_call_names(start_shadow_mode))

    assert "CNC_SHADOW_ENABLED" not in used_names
    assert "set_shadow_manager" in called_names
    assert "start_webui" in called_names
    assert "from_environment" in called_names
