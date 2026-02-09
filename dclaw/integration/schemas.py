from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


ActionType = Literal[
    "POST",
    "COMMENT",
    "LIKE",
    "INTERNAL_THOUGHT",
    "SLEEP",
    "NO_OP",
]


class Observation(BaseModel):
    """Normalized inbound event from the host (OpenClaw or other)."""

    timestamp: str = Field(..., description="ISO-8601 timestamp with timezone.")
    agent_id: str = Field(..., description="Logical DreamClaw agent identifier.")
    channel: str = Field(..., description="Inbound channel or surface name.")
    text: str = Field(..., description="Normalized content text.")
    thread_id: Optional[str] = Field(None, description="Thread/conversation identifier.")
    author_id: Optional[str] = Field(None, description="External author/user identifier.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Host-provided metadata.")
    world_state: Dict[str, Any] = Field(default_factory=dict, description="Host-provided global context.")


class Action(BaseModel):
    """Action returned by DreamClaw for the host to execute."""

    type: ActionType = Field(..., description="Action category.")
    text: Optional[str] = Field(None, description="Content to post/comment if applicable.")
    target_id: Optional[str] = Field(None, description="Target post/message id for comment/like.")
    channel: Optional[str] = Field(None, description="Destination channel override.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional action data.")


class TelemetrySnapshot(BaseModel):
    """Minimal telemetry snapshot for host logging/storage."""

    timestamp: str
    agent_id: str
    emotion: Dict[str, float]
    pad: List[float]
    action: ActionType
    notes: Optional[str] = None

