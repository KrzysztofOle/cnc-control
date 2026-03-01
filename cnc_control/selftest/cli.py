from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .core import run_selftest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cnc-selftest")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--verbose", action="store_true", help="Print detailed report.")
    return parser


def _print_text_report(payload: dict[str, object], *, verbose: bool) -> None:
    critical = int(payload.get("critical") or 0)
    warnings = int(payload.get("warnings") or 0)
    system_noise = int(payload.get("system_noise") or 0)
    status = str(payload.get("status") or "OK")

    print("==============================")
    print(" CNC SELFTEST V2 (SHADOW)")
    print("==============================")
    print(f"CRITICAL: {critical}")
    print(f"WARNINGS: {warnings}")
    print(f"SYSTEM_NOISE: {system_noise}")
    print(f"RESULT: {status}")

    if not verbose:
        return

    details = payload.get("details")
    if not isinstance(details, dict):
        return

    for section_name in ("journal", "shadow"):
        section = details.get(section_name)
        if not isinstance(section, dict):
            continue
        checks = section.get("checks")
        if not isinstance(checks, list):
            continue
        print("")
        print(f"[{section_name}]")
        for check in checks:
            if not isinstance(check, dict):
                continue
            status_value = str(check.get("status") or "PASS")
            name = str(check.get("name") or "check")
            detail = str(check.get("detail") or "")
            print(f"- [{status_value}] {name}")
            if detail:
                print(f"  {detail}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    result = run_selftest()
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
    else:
        _print_text_report(payload, verbose=args.verbose)

    return 1 if result.critical > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

