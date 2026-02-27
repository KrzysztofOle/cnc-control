import logging
import os
import threading
import time
from typing import Mapping, Optional

from shadow.lock_manager import LockManager
from shadow.rebuild_engine import RebuildEngine, RebuildError
from shadow.slot_manager import SlotManager
from shadow.state_store import ShadowState, StateStore
from shadow.usb_manager import UsbManager
from shadow.watcher_service import WatcherService


class ShadowManager:
    def __init__(
        self,
        state_store: StateStore,
        rebuild_engine: RebuildEngine,
        usb_manager: UsbManager,
        slot_manager: SlotManager,
        lock_manager: LockManager,
        watcher_service: WatcherService,
        debounce_seconds: int,
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
        )

    def start(self) -> None:
        self._slot_manager.cleanup_tmp_files()
        self._ensure_master_directory()
        state = self._state_store.load_or_initialize()
        active_slot = self._slot_manager.read_active_slot()
        state = self._normalize_state(state, active_slot)
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
            self._run_rebuild_cycle()

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

    def _run_rebuild_cycle(self) -> None:
        with self._lock_manager.hold(blocking=False) as acquired:
            if not acquired:
                self._set_error(
                    code="ERR_LOCK_CONFLICT",
                    message="Nie udalo sie uzyskac locka SHADOW.",
                )
                return
            try:
                self._run_rebuild_cycle_unlocked()
            except Exception as exc:
                self._set_error(code=self._map_error_code(exc), message=str(exc))
                self._logger.exception("SHADOW rebuild zakonczony bledem.")

    def _run_rebuild_cycle_unlocked(self) -> None:
        state = self._state_store.load_or_initialize()
        active_slot = self._slot_manager.read_active_slot()
        rebuild_slot = self._slot_manager.get_rebuild_slot(active_slot)
        rebuild_path = self._slot_manager.get_slot_path(rebuild_slot)

        state.fsm_state = "CHANGE_DETECTED"
        state.active_slot = active_slot
        state.rebuild_slot = rebuild_slot
        state.last_error = None
        self._state_store.save(state)

        state.fsm_state = "BUILD_SLOT_A" if rebuild_slot == "A" else "BUILD_SLOT_B"
        state.run_id += 1
        state.rebuild_counter = state.run_id
        self._state_store.save(state)
        self._logger.info(
            "SHADOW rebuild start: run_id=%s active_slot=%s rebuild_slot=%s",
            state.run_id,
            active_slot,
            rebuild_slot,
        )

        self._rebuild_engine.full_rebuild(rebuild_path)

        state.fsm_state = "EXPORT_STOP"
        self._state_store.save(state)
        if not self._usb_manager.stop_export():
            raise RuntimeError("Nie udalo sie zatrzymac eksportu USB.")

        state.fsm_state = "EXPORT_START"
        self._state_store.save(state)
        if not self._usb_manager.start_export(rebuild_path):
            raise RuntimeError("Nie udalo sie uruchomic eksportu USB.")

        self._slot_manager.write_active_slot(rebuild_slot)
        state.active_slot = rebuild_slot
        state.rebuild_slot = None
        state.fsm_state = "READY"
        self._state_store.save(state)
        self._logger.info(
            "SHADOW rebuild koniec: run_id=%s active_slot=%s",
            state.run_id,
            rebuild_slot,
        )

    def _normalize_state(self, state: ShadowState, active_slot: str) -> ShadowState:
        if state.active_slot == active_slot and state.fsm_state in {"IDLE", "READY"}:
            return state
        state.active_slot = active_slot
        state.rebuild_slot = None
        state.fsm_state = "IDLE"
        self._state_store.save(state)
        return state

    def _set_error(self, code: str, message: str) -> None:
        state = self._state_store.load_or_initialize()
        state.fsm_state = "ERROR"
        state.rebuild_slot = None
        state.last_error = {"code": code, "message": message}
        self._state_store.save(state)

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
