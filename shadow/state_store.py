import json
import os
import tempfile
from dataclasses import dataclass
from typing import Dict, Mapping, Optional


_ALLOWED_STATES = {
    "IDLE",
    "CHANGE_DETECTED",
    "BUILD_SLOT_A",
    "BUILD_SLOT_B",
    "EXPORT_STOP",
    "EXPORT_START",
    "READY",
    "ERROR",
}


@dataclass
class ShadowState:
    fsm_state: str = "IDLE"
    active_slot: str = "A"
    rebuild_slot: Optional[str] = None
    run_id: int = 0
    last_error: Optional[Dict[str, str]] = None
    rebuild_counter: int = 0

    def __post_init__(self) -> None:
        if self.fsm_state not in _ALLOWED_STATES:
            raise ValueError("Niepoprawny stan FSM.")
        if self.active_slot not in {"A", "B"}:
            raise ValueError("Niepoprawny active_slot.")
        if self.rebuild_slot not in {"A", "B", None}:
            raise ValueError("Niepoprawny rebuild_slot.")
        if self.rebuild_counter != self.run_id:
            raise ValueError("rebuild_counter musi byc rowny run_id.")

    def to_dict(self) -> Dict[str, object]:
        return {
            "fsm_state": self.fsm_state,
            "active_slot": self.active_slot,
            "rebuild_slot": self.rebuild_slot,
            "run_id": self.run_id,
            "last_error": self.last_error,
            "rebuild_counter": self.rebuild_counter,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "ShadowState":
        run_id = int(payload.get("run_id", 0))
        return cls(
            fsm_state=str(payload.get("fsm_state", "IDLE")),
            active_slot=str(payload.get("active_slot", "A")),
            rebuild_slot=payload.get("rebuild_slot"),
            run_id=run_id,
            last_error=payload.get("last_error"),
            rebuild_counter=int(payload.get("rebuild_counter", run_id)),
        )


class StateStore:
    def __init__(self, state_file: str) -> None:
        self._state_file = state_file

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "StateStore":
        state_file = environment.get(
            "CNC_SHADOW_STATE_FILE",
            "/var/lib/cnc-control/shadow_state.json",
        )
        return cls(state_file=state_file)

    def load(self) -> Optional[ShadowState]:
        if not os.path.isfile(self._state_file):
            return None
        with open(self._state_file, "r", encoding="utf-8") as state_handle:
            payload = json.load(state_handle)
        return ShadowState.from_dict(payload)

    def load_or_initialize(self) -> ShadowState:
        state = self.load()
        if state is not None:
            return state
        state = ShadowState()
        self.save(state)
        return state

    def save(self, state: ShadowState) -> None:
        directory = os.path.dirname(self._state_file) or "."
        os.makedirs(directory, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix="shadow-state-",
            suffix=".tmp",
            delete=False,
        ) as temp_handle:
            json.dump(state.to_dict(), temp_handle, ensure_ascii=False)
            temp_handle.write("\n")
            temp_handle.flush()
            os.fsync(temp_handle.fileno())
            temp_path = temp_handle.name

        os.replace(temp_path, self._state_file)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @property
    def path(self) -> str:
        return self._state_file
