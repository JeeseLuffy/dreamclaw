import os
from dataclasses import dataclass


def _as_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _as_int(value: str, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _as_float(value: str, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass
class AgentConfig:
    model_name: str = "gpt-4o-mini"
    use_llm_generation: bool = True
    use_prompt_critic: bool = True
    quality_threshold: float = 0.7
    max_posts_per_day: int = 1
    max_tokens_per_day: int = 600
    candidate_drafts: int = 3
    memory_top_k: int = 5
    use_real_mem0: bool = False
    vector_store_provider: str = "qdrant"
    checkpointer_path: str = "agent_state.db"
    agent_label: str = "🤖 AI Agent"

    @classmethod
    def from_env(cls) -> "AgentConfig":
        return cls(
            model_name=os.getenv("DCLAW_MODEL", "gpt-4o-mini"),
            use_llm_generation=_as_bool(os.getenv("DCLAW_USE_LLM_GENERATION"), True),
            use_prompt_critic=_as_bool(os.getenv("DCLAW_USE_PROMPT_CRITIC"), True),
            quality_threshold=_as_float(os.getenv("DCLAW_QUALITY_THRESHOLD"), 0.7),
            max_posts_per_day=_as_int(os.getenv("DCLAW_MAX_POSTS_PER_DAY"), 1),
            max_tokens_per_day=_as_int(os.getenv("DCLAW_MAX_TOKENS_PER_DAY"), 600),
            candidate_drafts=max(1, _as_int(os.getenv("DCLAW_CANDIDATE_DRAFTS"), 3)),
            memory_top_k=max(1, _as_int(os.getenv("DCLAW_MEMORY_TOP_K"), 5)),
            use_real_mem0=_as_bool(os.getenv("DCLAW_USE_REAL_MEM0"), False),
            vector_store_provider=os.getenv("DCLAW_VECTOR_STORE_PROVIDER", "qdrant"),
            checkpointer_path=os.getenv("DCLAW_CHECKPOINTER_PATH", "agent_state.db"),
            agent_label=os.getenv("DCLAW_AGENT_LABEL", "🤖 AI Agent"),
        )
