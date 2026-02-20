import os
import sys
import tempfile

from led_status import LedMode, MODE_FILE_PATH


def _usage() -> str:
    modes = ", ".join(mode.name for mode in LedMode)
    return f"Uzycie: python -m led_status_cli <MODE>\nDostepne tryby: {modes}"


def _write_mode_atomic(mode_name: str, path: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=".cnc-led-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{mode_name}\n")
            handle.flush()
            os.fsync(handle.fileno())

        replaced = False
        try:
            os.replace(tmp_path, path)
            replaced = True
        except PermissionError:
            if not os.path.exists(path):
                raise

        if not replaced:
            with open(path, "r+", encoding="utf-8") as handle:
                handle.seek(0)
                handle.write(f"{mode_name}\n")
                handle.truncate()
                handle.flush()
                os.fsync(handle.fileno())

        try:
            os.chmod(path, 0o666)
        except OSError:
            pass
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(_usage(), file=sys.stderr)
        return 2

    mode_name = args[0].strip().upper()
    if mode_name not in LedMode.__members__:
        print(f"Nieznany tryb: {mode_name}", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        return 2

    try:
        _write_mode_atomic(mode_name, MODE_FILE_PATH)
    except OSError as exc:
        print(f"Blad zapisu pliku IPC {MODE_FILE_PATH}: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
