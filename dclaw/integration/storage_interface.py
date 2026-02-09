from __future__ import annotations

from typing import Dict, List, Protocol


class DreamClawStorage(Protocol):
    """Storage interface owned by DreamClaw; host provides implementation."""

    def store_memory(self, fragment: Dict[str, str]) -> None:
        """Persist a memory fragment (schema defined by DreamClaw)."""

    def retrieve_relevant(self, query: str, limit: int = 20) -> List[Dict[str, str]]:
        """Retrieve relevant memory fragments by semantic query."""

    def log_emotion(self, vector: Dict[str, float]) -> None:
        """Persist an emotion vector snapshot."""
