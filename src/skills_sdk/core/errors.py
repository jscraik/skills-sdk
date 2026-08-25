"""Typed public contract failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ContractError(ValueError):
    """A stable, machine-readable contract error."""

    code: str
    message: str
    details: tuple[Any, ...] = ()

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
