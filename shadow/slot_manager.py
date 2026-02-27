import os
import tempfile
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class SlotConfig:
    image_a: str
    image_b: str
    active_slot_file: str
    initial_active_slot: str
    tmp_suffix: str


class SlotManager:
    def __init__(self, config: SlotConfig) -> None:
        self._config = config

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "SlotManager":
        config = SlotConfig(
            image_a=environment.get("CNC_USB_IMG_A", "/var/lib/cnc-control/cnc_usb_a.img"),
            image_b=environment.get("CNC_USB_IMG_B", "/var/lib/cnc-control/cnc_usb_b.img"),
            active_slot_file=environment.get(
                "CNC_ACTIVE_SLOT_FILE",
                "/var/lib/cnc-control/shadow_active_slot.state",
            ),
            initial_active_slot=environment.get("CNC_ACTIVE_SLOT", "A").strip().upper(),
            tmp_suffix=environment.get("CNC_SHADOW_TMP_SUFFIX", ".tmp"),
        )
        return cls(config=config)

    def read_active_slot(self) -> str:
        if os.path.isfile(self._config.active_slot_file):
            with open(self._config.active_slot_file, "r", encoding="utf-8") as slot_handle:
                value = slot_handle.read().strip().upper()
            self._validate_slot(value)
            return value

        default_slot = self._config.initial_active_slot
        self._validate_slot(default_slot)
        self.write_active_slot(default_slot)
        return default_slot

    def write_active_slot(self, slot: str) -> None:
        normalized_slot = slot.strip().upper()
        self._validate_slot(normalized_slot)

        target_path = self._config.active_slot_file
        directory = os.path.dirname(target_path) or "."
        os.makedirs(directory, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix="shadow-active-slot-",
            suffix=".tmp",
            delete=False,
        ) as tmp_handle:
            tmp_handle.write(f"{normalized_slot}\n")
            tmp_handle.flush()
            os.fsync(tmp_handle.fileno())
            tmp_path = tmp_handle.name

        os.replace(tmp_path, target_path)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def get_slot_path(self, slot: str) -> str:
        normalized_slot = slot.strip().upper()
        self._validate_slot(normalized_slot)
        return self._config.image_a if normalized_slot == "A" else self._config.image_b

    def get_rebuild_slot(self, active_slot: str) -> str:
        normalized_active_slot = active_slot.strip().upper()
        self._validate_slot(normalized_active_slot)
        return "B" if normalized_active_slot == "A" else "A"

    def cleanup_tmp_files(self) -> None:
        for image_path in (self._config.image_a, self._config.image_b):
            tmp_path = f"{image_path}{self._config.tmp_suffix}"
            try:
                os.remove(tmp_path)
            except FileNotFoundError:
                continue

    @staticmethod
    def _validate_slot(slot: str) -> None:
        if slot not in {"A", "B"}:
            raise ValueError("Dozwolone sa tylko sloty A lub B.")

    @property
    def active_slot_file(self) -> str:
        return self._config.active_slot_file
