#!/usr/bin/env python3
"""Bootstrap project virtual environment by target profile."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

DEV_TARGETS = {"dev", "integration"}
MARKER_FILENAME = ".cnc_target"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create/update virtual environment for selected target profile "
            "(dev, integration, rpi)."
        )
    )
    parser.add_argument(
        "--target",
        choices=("dev", "integration", "rpi"),
        required=True,
        help="Target profile to install.",
    )
    parser.add_argument(
        "--venv-dir",
        default=".venv",
        help="Virtual environment directory path.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass host-target safety checks.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate virtual environment from scratch.",
    )
    return parser.parse_args()


def is_raspberry_pi_host() -> bool:
    if platform.system() != "Linux":
        return False

    for candidate in (
        Path("/proc/device-tree/model"),
        Path("/sys/firmware/devicetree/base/model"),
    ):
        if not candidate.exists():
            continue
        model = candidate.read_text(encoding="utf-8", errors="ignore")
        if "Raspberry Pi" in model:
            return True

    return False


def validate_target(target: str, is_rpi_host: bool, force: bool) -> None:
    if force:
        return

    if target == "rpi" and not is_rpi_host:
        raise RuntimeError(
            "Target 'rpi' is allowed only on Raspberry Pi host. "
            "Use --force to override."
        )

    if target in DEV_TARGETS and is_rpi_host:
        raise RuntimeError(
            f"Target '{target}' is intended for developer machine, "
            "not Raspberry Pi. Use --force to override."
        )


def run_command(command: list[str], cwd: Path) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def resolve_venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def recreate_venv_if_requested(venv_dir: Path, recreate: bool) -> None:
    if recreate and venv_dir.exists():
        print(f"Removing virtual environment: {venv_dir}")
        shutil.rmtree(venv_dir)


def ensure_venv_exists(venv_dir: Path, repo_root: Path) -> Path:
    if not venv_dir.exists():
        run_command([sys.executable, "-m", "venv", str(venv_dir)], cwd=repo_root)

    venv_python = resolve_venv_python(venv_dir)
    if not venv_python.exists():
        raise RuntimeError(f"Virtual environment Python not found: {venv_python}")

    return venv_python


def install_profile(venv_python: Path, target: str, repo_root: Path) -> None:
    run_command([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], cwd=repo_root)

    if target == "dev":
        run_command(
            [str(venv_python), "-m", "pip", "install", "-r", "requirements_dev.txt"],
            cwd=repo_root,
        )
        return

    if target == "integration":
        run_command(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "-r",
                "requirements_integration.txt",
            ],
            cwd=repo_root,
        )
        return

    run_command(
        [str(venv_python), "-m", "pip", "install", "--editable", ".[rpi]"],
        cwd=repo_root,
    )


def write_target_marker(venv_dir: Path, target: str) -> None:
    marker_path = venv_dir / MARKER_FILENAME
    marker_path.write_text(f"{target}\n", encoding="utf-8")
    print(f"Wrote environment marker: {marker_path} -> {target}")


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    venv_dir = (repo_root / args.venv_dir).resolve()

    try:
        validate_target(args.target, is_raspberry_pi_host(), args.force)
        recreate_venv_if_requested(venv_dir, args.recreate)
        venv_python = ensure_venv_exists(venv_dir, repo_root)
        install_profile(venv_python, args.target, repo_root)
        write_target_marker(venv_dir, args.target)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
