import logging
from typing import Mapping

from shadow.lock_manager import LockManager
from shadow.rebuild_engine import RebuildEngine
from shadow.slot_manager import SlotManager
from shadow.state_store import StateStore
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
    ) -> None:
        self._state_store = state_store
        self._rebuild_engine = rebuild_engine
        self._usb_manager = usb_manager
        self._slot_manager = slot_manager
        self._lock_manager = lock_manager
        self._watcher_service = watcher_service
        self._logger = logging.getLogger(__name__)

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "ShadowManager":
        return cls(
            state_store=StateStore.from_environment(environment),
            rebuild_engine=RebuildEngine.from_environment(environment),
            usb_manager=UsbManager.from_environment(environment),
            slot_manager=SlotManager.from_environment(environment),
            lock_manager=LockManager.from_environment(environment),
            watcher_service=WatcherService.from_environment(environment),
        )

    def start(self) -> None:
        self._slot_manager.cleanup_tmp_files()
        state = self._state_store.load_or_initialize()
        active_slot = self._slot_manager.read_active_slot()
        self._logger.info(
            "SHADOW bootstrap gotowy: state=%s active_slot=%s state_file=%s lock_file=%s",
            state.fsm_state,
            active_slot,
            self._state_store.path,
            self._lock_manager.path,
        )
