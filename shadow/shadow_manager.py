import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Mapping, Optional

from shadow.lock_manager import LockManager
from shadow.rebuild_engine import RebuildEngine, RebuildError
from shadow.slot_manager import SlotManager
from shadow.state_store import ShadowState, StateStore
from shadow.usb_manager import UsbManager
from shadow.watcher_service import WatcherService


class ShadowManager:
    _LED_MODE_BY_STATE = {
        "IDLE": "UPLOAD",
        "READY": "UPLOAD",
        "CHANGE_DETECTED": "SHADOW_PENDING",
        "BUILD_SLOT_A": "USB",
        "BUILD_SLOT_B": "USB",
        "EXPORT_STOP": "USB",
        "EXPORT_START": "USB",
        "ERROR": "ERROR",
    }

    def __init__(
        self,
        state_store: StateStore,
        rebuild_engine: RebuildEngine,
        usb_manager: UsbManager,
        slot_manager: SlotManager,
        lock_manager: LockManager,
        watcher_service: WatcherService,
        debounce_seconds: int,
        history_file: str,
        history_limit: int,
    ) -> None:
        self._state_store = state_store
        self._rebuild_engine = rebuild_engine
        self._usb_manager = usb_manager
        self._slot_manager = slot_manager
        self._lock_manager = lock_manager
        self._watcher_service = watcher_service
        self._debounce_seconds = max(0, debounce_seconds)
        self._logger = logging.getLogger(__name__)
        self._worker: Optional[threading.Thread] = None
        self._manual_thread: Optional[threading.Thread] = None
        self._manual_lock = threading.Lock()
        self._last_led_mode: Optional[str] = None
        self._history_file = history_file
        self._history_limit = max(1, history_limit)
        self._history_lock = threading.Lock()
        self._history_entries = self._load_history()

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "ShadowManager":
        return cls(
            state_store=StateStore.from_environment(environment),
            rebuild_engine=RebuildEngine.from_environment(environment),
            usb_manager=UsbManager.from_environment(environment),
            slot_manager=SlotManager.from_environment(environment),
            lock_manager=LockManager.from_environment(environment),
            watcher_service=WatcherService.from_environment(environment),
            debounce_seconds=int(environment.get("CNC_SHADOW_DEBOUNCE_SECONDS", "4")),
            history_file=environment.get(
                "CNC_SHADOW_HISTORY_FILE",
                "/var/lib/cnc-control/shadow_history.json",
            ),
            history_limit=int(environment.get("CNC_SHADOW_HISTORY_LIMIT", "50")),
        )

    def start(self) -> None:
        self._slot_manager.cleanup_tmp_files()
        self._ensure_master_directory()
        state = self._state_store.load_or_initialize()
        active_slot = self._slot_manager.read_active_slot()
        state = self._normalize_state(state, active_slot)
        self._apply_led_for_state(state.fsm_state)
        try:
            self._watcher_service.start()
        except Exception as exc:
            self._set_error(code="ERR_MISSING_DEPENDENCY", message=str(exc))
            self._logger.exception("SHADOW nie uruchomil watchera.")
            return
        self._start_worker()
        self._logger.info(
            "SHADOW bootstrap gotowy: state=%s active_slot=%s state_file=%s lock_file=%s watch_dir=%s",
            state.fsm_state,
            active_slot,
            self._state_store.path,
            self._lock_manager.path,
            self._watcher_service.watched_dir,
        )

    def trigger_manual_rebuild(self):
        with self._manual_lock:
            if self._manual_thread is not None and self._manual_thread.is_alive():
                return False, "Manual rebuild juz jest uruchomiony."
            self._manual_thread = threading.Thread(
                target=self._manual_rebuild_worker,
                name="cnc-shadow-manual-rebuild",
                daemon=True,
            )
            self._manual_thread.start()
        return True, "Manual rebuild uruchomiony."

    def get_rebuild_history(self, limit: int = 20):
        resolved_limit = max(1, min(limit, self._history_limit))
        with self._history_lock:
            return list(reversed(self._history_entries))[:resolved_limit]

    def get_manual_status(self):
        with self._manual_lock:
            running = self._manual_thread is not None and self._manual_thread.is_alive()

        last_manual = None
        with self._history_lock:
            for entry in reversed(self._history_entries):
                if entry.get("trigger") == "manual":
                    last_manual = dict(entry)
                    break

        return {"running": running, "last_manual": last_manual}

    def _manual_rebuild_worker(self) -> None:
        self._run_rebuild_cycle(trigger="manual", mark_lock_conflict_error=False)

    def _start_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._watch_loop,
            name="cnc-shadow-watch-loop",
            daemon=True,
        )
        self._worker.start()

    def _watch_loop(self) -> None:
        while True:
            event = self._watcher_service.poll_event(timeout_seconds=1.0)
            if event is None:
                continue
            self._logger.info("SHADOW wykryto zmiane: %s", event)
            self._wait_for_debounce()
            self._run_rebuild_cycle(trigger="watch", mark_lock_conflict_error=True)

    def _wait_for_debounce(self) -> None:
        if self._debounce_seconds <= 0:
            return
        deadline = time.monotonic() + self._debounce_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            event = self._watcher_service.poll_event(timeout_seconds=remaining)
            if event is None:
                return
            self._logger.info("SHADOW debounce scala zdarzenie: %s", event)
            deadline = time.monotonic() + self._debounce_seconds

    def _run_rebuild_cycle(self, trigger: str, mark_lock_conflict_error: bool) -> bool:
        started_at = self._utc_now()
        start_monotonic = time.monotonic()
        cycle_meta = None
        with self._lock_manager.hold(blocking=False) as acquired:
            if not acquired:
                message = "Nie udalo sie uzyskac locka SHADOW."
                if mark_lock_conflict_error:
                    self._set_error(code="ERR_LOCK_CONFLICT", message=message)
                self._append_history_entry(
                    {
                        "trigger": trigger,
                        "result": "lock_conflict",
                        "run_id": self._current_run_id(),
                        "active_slot_before": None,
                        "rebuild_slot": None,
                        "active_slot_after": None,
                        "started_at": started_at,
                        "finished_at": self._utc_now(),
                        "duration_ms": int((time.monotonic() - start_monotonic) * 1000),
                        "error": {
                            "code": "ERR_LOCK_CONFLICT",
                            "message": message,
                        },
                    }
                )
                return False
            try:
                cycle_meta = self._run_rebuild_cycle_unlocked()
            except Exception as exc:
                error_code = self._map_error_code(exc)
                self._set_error(code=error_code, message=str(exc))
                self._logger.exception("SHADOW rebuild zakonczony bledem.")
                current_state = self._state_store.load_or_initialize()
                self._append_history_entry(
                    {
                        "trigger": trigger,
                        "result": "error",
                        "run_id": self._resolve_run_id(cycle_meta),
                        "active_slot_before": self._resolve_meta_value(cycle_meta, "active_slot_before"),
                        "rebuild_slot": self._resolve_meta_value(cycle_meta, "rebuild_slot"),
                        "active_slot_after": current_state.active_slot,
                        "started_at": started_at,
                        "finished_at": self._utc_now(),
                        "duration_ms": int((time.monotonic() - start_monotonic) * 1000),
                        "error": {"code": error_code, "message": str(exc)},
                    }
                )
                return False

        final_state = self._state_store.load_or_initialize()
        self._append_history_entry(
            {
                "trigger": trigger,
                "result": "ok",
                "run_id": self._resolve_run_id(cycle_meta),
                "active_slot_before": self._resolve_meta_value(cycle_meta, "active_slot_before"),
                "rebuild_slot": self._resolve_meta_value(cycle_meta, "rebuild_slot"),
                "active_slot_after": final_state.active_slot,
                "started_at": started_at,
                "finished_at": self._utc_now(),
                "duration_ms": int((time.monotonic() - start_monotonic) * 1000),
                "error": None,
            }
        )
        return True

    def _run_rebuild_cycle_unlocked(self):
        state = self._state_store.load_or_initialize()
        active_slot = self._slot_manager.read_active_slot()
        rebuild_slot = self._slot_manager.get_rebuild_slot(active_slot)
        rebuild_path = self._slot_manager.get_slot_path(rebuild_slot)

        state.fsm_state = "CHANGE_DETECTED"
        state.active_slot = active_slot
        state.rebuild_slot = rebuild_slot
        state.last_error = None
        self._save_state(state)

        state.fsm_state = "BUILD_SLOT_A" if rebuild_slot == "A" else "BUILD_SLOT_B"
        state.run_id += 1
        state.rebuild_counter = state.run_id
        self._save_state(state)
        self._logger.info(
            "SHADOW rebuild start: run_id=%s active_slot=%s rebuild_slot=%s",
            state.run_id,
            active_slot,
            rebuild_slot,
        )

        cycle_meta = {
            "run_id": state.run_id,
            "active_slot_before": active_slot,
            "rebuild_slot": rebuild_slot,
        }

        self._rebuild_engine.full_rebuild(rebuild_path)

        state.fsm_state = "EXPORT_STOP"
        self._save_state(state)
        if not self._usb_manager.stop_export():
            raise RuntimeError("Nie udalo sie zatrzymac eksportu USB.")

        state.fsm_state = "EXPORT_START"
        self._save_state(state)
        if not self._usb_manager.start_export(rebuild_path):
            raise RuntimeError("Nie udalo sie uruchomic eksportu USB.")

        self._slot_manager.write_active_slot(rebuild_slot)
        state.active_slot = rebuild_slot
        state.rebuild_slot = None
        state.fsm_state = "READY"
        self._save_state(state)
        self._logger.info(
            "SHADOW rebuild koniec: run_id=%s active_slot=%s",
            state.run_id,
            rebuild_slot,
        )
        cycle_meta["active_slot_after"] = rebuild_slot
        return cycle_meta

    def _normalize_state(self, state: ShadowState, active_slot: str) -> ShadowState:
        if state.active_slot == active_slot and state.fsm_state in {"IDLE", "READY"}:
            return state
        state.active_slot = active_slot
        state.rebuild_slot = None
        state.fsm_state = "IDLE"
        self._save_state(state)
        return state

    def _set_error(self, code: str, message: str) -> None:
        state = self._state_store.load_or_initialize()
        state.fsm_state = "ERROR"
        state.rebuild_slot = None
        state.last_error = {"code": code, "message": message}
        self._save_state(state)

    def _ensure_master_directory(self) -> None:
        os.makedirs(self._rebuild_engine.master_dir, exist_ok=True)

    @staticmethod
    def _map_error_code(error: Exception) -> str:
        if isinstance(error, RebuildError):
            return "ERR_REBUILD_TIMEOUT"
        message = str(error).lower()
        if "lock" in message:
            return "ERR_LOCK_CONFLICT"
        if "zatrzymac eksportu usb" in message:
            return "ERR_USB_STOP_TIMEOUT"
        if "uruchomic eksportu usb" in message:
            return "ERR_USB_START_TIMEOUT"
        return "ERR_REBUILD_TIMEOUT"

    def _save_state(self, state: ShadowState) -> None:
        self._state_store.save(state)
        self._apply_led_for_state(state.fsm_state)

    def _apply_led_for_state(self, fsm_state: str) -> None:
        led_mode = self._LED_MODE_BY_STATE.get(fsm_state)
        if not led_mode or led_mode == self._last_led_mode:
            return
        if self._set_led_mode(led_mode):
            self._last_led_mode = led_mode

    def _set_led_mode(self, mode_name: str) -> bool:
        commands = []
        if sys.executable:
            commands.append([sys.executable, "-m", "led_status_cli", mode_name])
        commands.extend(
            [
                ["python3", "-m", "led_status_cli", mode_name],
                ["python", "-m", "led_status_cli", mode_name],
            ]
        )

        seen = set()
        for command in commands:
            key = tuple(command)
            if key in seen:
                continue
            seen.add(key)
            try:
                result = subprocess.run(
                    command,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
            except FileNotFoundError:
                continue
            except Exception as exc:
                self._logger.warning("SHADOW LED set failed (%s): %s", mode_name, exc)
                continue
            if result.returncode == 0:
                return True
        self._logger.warning("SHADOW LED mode not applied: %s", mode_name)
        return False

    def _append_history_entry(self, entry) -> None:
        with self._history_lock:
            self._history_entries.append(entry)
            if len(self._history_entries) > self._history_limit:
                self._history_entries = self._history_entries[-self._history_limit :]
            snapshot = list(self._history_entries)
        self._save_history(snapshot)

    def _load_history(self):
        if not os.path.isfile(self._history_file):
            return []
        try:
            with open(self._history_file, "r", encoding="utf-8") as history_handle:
                payload = json.load(history_handle)
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        entries = [entry for entry in payload if isinstance(entry, dict)]
        if len(entries) > self._history_limit:
            entries = entries[-self._history_limit :]
        return entries

    def _save_history(self, entries) -> None:
        directory = os.path.dirname(self._history_file) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=directory,
                prefix="shadow-history-",
                suffix=".tmp",
                delete=False,
            ) as temp_handle:
                json.dump(entries, temp_handle, ensure_ascii=False)
                temp_handle.write("\n")
                temp_handle.flush()
                os.fsync(temp_handle.fileno())
                temp_path = temp_handle.name
            os.replace(temp_path, self._history_file)
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            self._logger.warning("SHADOW history save failed: %s", exc)

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _current_run_id(self) -> int:
        try:
            state = self._state_store.load_or_initialize()
            return int(state.run_id)
        except Exception:
            return 0

    def _resolve_run_id(self, cycle_meta) -> int:
        if isinstance(cycle_meta, dict) and "run_id" in cycle_meta:
            try:
                return int(cycle_meta.get("run_id"))
            except (TypeError, ValueError):
                pass
        return self._current_run_id()

    @staticmethod
    def _resolve_meta_value(cycle_meta, key: str):
        if not isinstance(cycle_meta, dict):
            return None
        return cycle_meta.get(key)
