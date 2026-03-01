import fcntl
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Optional, Tuple

LED_PIN = 18
LED_COUNT = 3
BRIGHTNESS = 0.3
MODE_FILE_PATH = os.environ.get("CNC_LED_MODE_FILE", "/tmp/cnc_led_mode")
LOCK_FILE_PATH = os.environ.get("CNC_LED_LOCK_FILE", "/tmp/cnc_led.lock")
LOG_FILE_PATH = os.environ.get("CNC_LED_LOG", "/var/log/cnc-control/led.log")


class LedMode(Enum):
    BOOT = auto()
    SHADOW_READY = auto()
    SHADOW_SYNC = auto()
    AP = auto()
    ERROR = auto()
    IDLE = auto()


@dataclass(frozen=True)
class _LedPattern:
    color: Tuple[int, int, int]
    blink_hz: float


MODE_PATTERNS: Dict[LedMode, _LedPattern] = {
    LedMode.BOOT: _LedPattern((255, 180, 0), 0.0),
    LedMode.SHADOW_READY: _LedPattern((0, 255, 0), 0.0),
    LedMode.SHADOW_SYNC: _LedPattern((0, 0, 255), 0.0),
    LedMode.AP: _LedPattern((0, 0, 255), 1.0),
    LedMode.ERROR: _LedPattern((255, 0, 0), 3.0),
    LedMode.IDLE: _LedPattern((76, 76, 76), 0.0),
}


_LOGGER = logging.getLogger("cnc_led")


def _configure_logging() -> None:
    _LOGGER.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    try:
        os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
        file_handler = logging.FileHandler(LOG_FILE_PATH)
        file_handler.setFormatter(formatter)
        _LOGGER.addHandler(file_handler)
    except OSError:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        _LOGGER.addHandler(stream_handler)
        _LOGGER.warning("Brak dostepu do pliku logu %s, przejscie na stderr.", LOG_FILE_PATH)


class _NoopLedBackend:
    def __init__(self) -> None:
        self._last_state: Optional[Tuple[bool, Tuple[int, int, int]]] = None

    def show(self, enabled: bool, rgb: Tuple[int, int, int]) -> None:
        state = (enabled, rgb)
        if state != self._last_state:
            if enabled:
                _LOGGER.info("Tryb symulowany LED ON rgb=%s", rgb)
            else:
                _LOGGER.info("Tryb symulowany LED OFF")
            self._last_state = state

    def clear(self) -> None:
        self.show(False, (0, 0, 0))


class _Ws281xBackend:
    def __init__(self) -> None:
        try:
            from rpi_ws281x import Color, PixelStrip
        except Exception as exc:
            raise RuntimeError("Brak biblioteki rpi_ws281x") from exc

        self._color = Color
        brightness_value = max(0, min(255, int(round(BRIGHTNESS * 255))))
        self._strip = PixelStrip(
            LED_COUNT,
            LED_PIN,
            800000,
            10,
            False,
            brightness_value,
            0,
        )
        self._strip.begin()

    def show(self, enabled: bool, rgb: Tuple[int, int, int]) -> None:
        if enabled:
            red, green, blue = rgb
            color = self._color(red, green, blue)
        else:
            color = self._color(0, 0, 0)
        for index in range(LED_COUNT):
            self._strip.setPixelColor(index, color)
        self._strip.show()

    def clear(self) -> None:
        self.show(False, (0, 0, 0))


class LedStatusController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._mode = LedMode.BOOT
        self._backend = self._create_backend()

    def _create_backend(self):
        try:
            backend = _Ws281xBackend()
            _LOGGER.info(
                "Uruchomiono backend WS2812: pin=%s count=%s brightness=%.2f",
                LED_PIN,
                LED_COUNT,
                BRIGHTNESS,
            )
            return backend
        except Exception as exc:
            _LOGGER.warning("Nie mozna uruchomic GPIO/WS2812 (%s). Uzywam fallback.", exc)
            return _NoopLedBackend()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._worker_loop, name="led-status", daemon=True)
            self._thread.start()

    def set_mode(self, mode: LedMode):
        with self._lock:
            if self._mode != mode:
                self._mode = mode
                _LOGGER.info("Zmiana trybu LED: %s", mode.name)

    def stop(self):
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._backend.clear()
        _LOGGER.info("Kontroler LED zatrzymany.")

    def _worker_loop(self) -> None:
        last_output: Optional[Tuple[bool, Tuple[int, int, int]]] = None
        while not self._stop_event.is_set():
            with self._lock:
                mode = self._mode
            pattern = MODE_PATTERNS.get(mode, MODE_PATTERNS[LedMode.ERROR])

            if pattern.blink_hz <= 0:
                enabled = True
            else:
                period = 1.0 / pattern.blink_hz
                enabled = (time.monotonic() % period) < (period / 2.0)

            output = (enabled, pattern.color)
            if output != last_output:
                self._backend.show(enabled, pattern.color)
                last_output = output

            self._stop_event.wait(0.05)


class _SingleInstanceLock:
    def __init__(self, lock_path: str) -> None:
        self._lock_path = lock_path
        self._handle = None

    def acquire(self) -> bool:
        self._handle = open(self._lock_path, "w", encoding="utf-8")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self._handle.write(str(os.getpid()))
        self._handle.flush()
        return True

    def release(self) -> None:
        if not self._handle:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self._handle.close()
        self._handle = None


def _read_mode_file(path: str) -> Optional[LedMode]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw_value = handle.read().strip().upper()
    except FileNotFoundError:
        return None
    except OSError as exc:
        _LOGGER.warning("Nie mozna odczytac pliku trybu LED (%s): %s", path, exc)
        return None

    if not raw_value:
        return None

    # PL: Mapa kompatybilnosci dla historycznych nazw trybow LED.
    # EN: Backward-compatibility map for historical LED mode names.
    legacy_aliases = {
        "USB": "SHADOW_READY",
        "UPLOAD": "SHADOW_READY",
        "SHADOW_PENDING": "SHADOW_SYNC",
    }
    normalized_value = legacy_aliases.get(raw_value, raw_value)

    try:
        return LedMode[normalized_value]
    except KeyError:
        _LOGGER.warning("Nieznany tryb LED w pliku IPC: %s", raw_value)
        return None


def _prepare_mode_file(path: str) -> None:
    directory = os.path.dirname(path) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o666)
        os.close(fd)
        os.chmod(path, 0o666)
    except OSError as exc:
        _LOGGER.warning("Nie mozna przygotowac pliku IPC LED (%s): %s", path, exc)


def _run_daemon() -> int:
    _configure_logging()
    _prepare_mode_file(MODE_FILE_PATH)

    lock = _SingleInstanceLock(LOCK_FILE_PATH)
    if not lock.acquire():
        _LOGGER.error("Inna instancja demona LED juz dziala.")
        return 1

    controller = LedStatusController()
    controller.set_mode(LedMode.BOOT)
    controller.start()

    exit_event = threading.Event()

    def _signal_handler(signum, _frame):
        _LOGGER.info("Odebrano sygnal %s. Zatrzymywanie...", signum)
        exit_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    _LOGGER.info("Demon LED uruchomiony. Monitor IPC: %s", MODE_FILE_PATH)
    last_mtime_ns = None
    try:
        while not exit_event.is_set():
            try:
                stat_result = os.stat(MODE_FILE_PATH)
                current_mtime_ns = stat_result.st_mtime_ns
                if current_mtime_ns != last_mtime_ns:
                    last_mtime_ns = current_mtime_ns
                    mode = _read_mode_file(MODE_FILE_PATH)
                    if mode:
                        controller.set_mode(mode)
            except FileNotFoundError:
                pass
            except OSError as exc:
                _LOGGER.warning("Blad monitorowania pliku IPC: %s", exc)

            exit_event.wait(0.2)
        return 0
    finally:
        controller.stop()
        lock.release()


if __name__ == "__main__":
    raise SystemExit(_run_daemon())
