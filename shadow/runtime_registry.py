import threading
from typing import Optional


_LOCK = threading.Lock()
_SHADOW_MANAGER = None


def set_shadow_manager(manager) -> None:
    global _SHADOW_MANAGER
    with _LOCK:
        _SHADOW_MANAGER = manager


def get_shadow_manager() -> Optional[object]:
    with _LOCK:
        return _SHADOW_MANAGER
