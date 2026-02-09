from __future__ import annotations

from typing import Any, Dict, Protocol

from .schemas import Action, Observation


class DreamClawKernel(Protocol):
    """Kernel interface implemented by DreamClaw for host integration."""

    def tick(self, obs: Observation) -> Action:
        """Process one observation and return one action."""

    def get_telemetry(self) -> Dict[str, Any]:
        """Return a host-serializable telemetry snapshot."""

    def save_state(self) -> None:
        """Persist internal state (memory, emotion, persona, etc.)."""
