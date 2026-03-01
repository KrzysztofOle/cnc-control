from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class SelfTestResult:
    critical: int = 0
    warnings: int = 0
    system_noise: int = 0
    status: Literal["OK", "FAILED"] = "OK"
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._refresh_status()

    def merge_counts(
        self,
        *,
        critical: int = 0,
        warnings: int = 0,
        system_noise: int = 0,
    ) -> None:
        self.critical += max(0, critical)
        self.warnings += max(0, warnings)
        self.system_noise += max(0, system_noise)
        self._refresh_status()

    def _refresh_status(self) -> None:
        self.status = "FAILED" if self.critical > 0 else "OK"

    def to_dict(self) -> dict[str, Any]:
        return {
            "critical": self.critical,
            "warnings": self.warnings,
            "system_noise": self.system_noise,
            "status": self.status,
            "details": self.details,
        }

