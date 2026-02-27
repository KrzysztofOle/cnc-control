import importlib
import os
from dataclasses import dataclass
from typing import Callable, Mapping, Optional


def parse_env_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().casefold() == "true"


def resolve_start_entrypoint() -> Callable[[], None]:
    import __main__

    start_function = getattr(__main__, "start_net_usb", None)
    if not callable(start_function):
        raise RuntimeError("Brak funkcji start_net_usb() w entrypoincie aplikacji.")
    return start_function


@dataclass(frozen=True)
class NetUsbMode:
    start_callback: Callable[[], None]

    def start(self) -> None:
        self.start_callback()


@dataclass(frozen=True)
class ShadowMode:
    start_callback: Callable[[], None]
    environment: Mapping[str, str]

    def start(self) -> None:
        shadow_module = importlib.import_module("shadow.shadow_manager")
        shadow_manager_class = getattr(shadow_module, "ShadowManager")
        shadow_manager = shadow_manager_class.from_environment(self.environment)
        shadow_manager.start()
        self.start_callback()


class ModeSelector:
    SHADOW_ENV_KEY = "CNC_SHADOW_ENABLED"

    def __init__(self, environment: Mapping[str, str] = None) -> None:
        self._environment = os.environ if environment is None else environment

    def _shadow_enabled(self) -> bool:
        return parse_env_bool(self._environment.get(self.SHADOW_ENV_KEY), default=False)

    def _build_mode(self):
        start_callback = resolve_start_entrypoint()
        if self._shadow_enabled():
            return ShadowMode(start_callback=start_callback, environment=self._environment)
        return NetUsbMode(start_callback=start_callback)

    def start(self) -> None:
        mode = self._build_mode()
        mode.start()
