import os
from dataclasses import dataclass


def _as_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _as_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class CommunityConfig:
    db_path: str = "community.db"
    timezone: str = "America/Los_Angeles"
    ai_population: int = 20
    scheduler_interval_seconds: int = 600
    human_daily_limit: int = 10
    ai_post_daily_limit: int = 1
    ai_comment_daily_limit: int = 2
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    candidate_drafts: int = 2
    quality_threshold_post: float = 0.55
    quality_threshold_comment: float = 0.5
    request_timeout_seconds: int = 30
    allow_model_fallback: bool = False

    @classmethod
    def from_env(cls) -> "CommunityConfig":
        return cls(
            db_path=os.getenv("DCLAW_COMMUNITY_DB_PATH", "community.db"),
            timezone=os.getenv("DCLAW_COMMUNITY_TZ", "America/Los_Angeles"),
            ai_population=max(1, _as_int(os.getenv("DCLAW_AI_POPULATION"), 20)),
            scheduler_interval_seconds=max(5, _as_int(os.getenv("DCLAW_AI_TICK_SECONDS"), 600)),
            human_daily_limit=max(1, _as_int(os.getenv("DCLAW_HUMAN_DAILY_LIMIT"), 10)),
            ai_post_daily_limit=max(1, _as_int(os.getenv("DCLAW_AI_POST_DAILY_LIMIT"), 1)),
            ai_comment_daily_limit=max(0, _as_int(os.getenv("DCLAW_AI_COMMENT_DAILY_LIMIT"), 2)),
            provider=os.getenv("DCLAW_COMMUNITY_PROVIDER", "openai"),
            model=os.getenv("DCLAW_COMMUNITY_MODEL", "gpt-4o-mini"),
            candidate_drafts=max(1, _as_int(os.getenv("DCLAW_AI_CANDIDATES"), 2)),
            quality_threshold_post=_as_float(os.getenv("DCLAW_POST_THRESHOLD"), 0.55),
            quality_threshold_comment=_as_float(os.getenv("DCLAW_COMMENT_THRESHOLD"), 0.5),
            request_timeout_seconds=max(5, _as_int(os.getenv("DCLAW_COMMUNITY_TIMEOUT_SECONDS"), 30)),
            allow_model_fallback=_as_bool(os.getenv("DCLAW_COMMUNITY_ALLOW_FALLBACK"), False),
        )
