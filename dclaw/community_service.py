import json
import random
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from dclaw.community_config import CommunityConfig
from dclaw.community_db import CommunityDB
from dclaw.community_providers import (
    PromptInput,
    ProviderConfigurationError,
    ProviderRequestError,
    build_provider,
)
from dclaw.critic import ContentCritic
from dclaw.emotion import EmotionState


STOPWORDS = {
    "this",
    "that",
    "from",
    "with",
    "your",
    "have",
    "about",
    "today",
    "just",
    "into",
    "there",
    "would",
    "could",
    "should",
    "their",
    "while",
    "still",
}


PERSONA_TOPICS = [
    "open-source AI agents",
    "LLM product design",
    "developer tooling",
    "memory systems",
    "human-AI collaboration",
    "community moderation",
    "learning in public",
    "creative coding",
]


PERSONA_STYLES = [
    "concise",
    "curious",
    "optimistic",
    "critical but fair",
    "builder-minded",
    "reflective",
]


PERSONA_VALUES = [
    "signal over noise",
    "transparent experiments",
    "kind but direct feedback",
    "evidence-based opinions",
    "practical engineering",
]

MODEL_WHITELIST = {
    "ollama": ["llama3:latest", "qwen2.5:7b", "gemma3:12b", "deepseek-r1:7b"],
    "openai": ["gpt-4o-mini", "gpt-4.1-mini"],
    "anthropic": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"],
    "google": ["gemini-2.0-flash", "gemini-1.5-pro"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "moonshot": ["moonshot-v1-8k", "moonshot-v1-32k"],
    "qwen": ["qwen-max", "qwen-plus"],
}


class CommunityService:
    def __init__(self, config: CommunityConfig):
        self.config = config
        self.db = CommunityDB(config.db_path)
        self.timezone = ZoneInfo(config.timezone)
        self.random = random.Random()
        self.provider_cache: dict[tuple[str, str], Any] = {}
        self.provider_available: dict[tuple[str, str], bool] = {}
        self.provider_error = ""
        self._rumination_llm_budget_remaining = 0

        self._resolve_provider(config.provider, config.model)

        self.critic = ContentCritic(
            llm=None,
            llm_invoke=None,
            use_prompt_critic=True,
        )

        self.bootstrap_ai_population(config.ai_population)
        self._seed_initial_timeline()

    # ---------- Clock helpers ----------
    def _now(self) -> datetime:
        return datetime.now(self.timezone)

    def _iso_now(self) -> str:
        return self._now().isoformat()

    def _day_key(self, dt: datetime | None = None) -> str:
        local_dt = dt or self._now()
        if self.config.virtual_day_seconds > 0:
            bucket = int(local_dt.timestamp()) // self.config.virtual_day_seconds
            return f"vd-{bucket}"
        return local_dt.strftime("%Y-%m-%d")

    # ---------- Providers ----------
    def available_models(self) -> dict[str, list[str]]:
        return {provider: list(models) for provider, models in MODEL_WHITELIST.items()}

    def _is_model_allowed(self, provider: str, model: str) -> bool:
        provider_name = provider.lower()
        if provider_name not in MODEL_WHITELIST:
            return False
        return model in MODEL_WHITELIST[provider_name]

    def _resolve_provider(self, provider: str, model: str):
        key = (provider.lower(), model)
        if key in self.provider_cache:
            return self.provider_cache[key]
        try:
            instance = build_provider(
                provider,
                model,
                timeout_seconds=self.config.request_timeout_seconds,
            )
            self.provider_cache[key] = instance
            self.provider_available[key] = True
            return instance
        except ProviderRequestError as exc:
            self.provider_error = str(exc)
            self.provider_available[key] = False
            self.provider_cache[key] = None
            return None
        except ProviderConfigurationError as exc:
            self.provider_error = str(exc)
            self.provider_available[key] = False
            self.provider_cache[key] = None
            return None
        except Exception as exc:
            self.provider_error = str(exc)
            self.provider_available[key] = False
            self.provider_cache[key] = None
            return None

    def _fallback_provider_model(self) -> tuple[str, str]:
        return "ollama", "llama3:latest"

    # ---------- Emotion baseline helpers ----------
    def _pad_baseline_from_json(self, raw: str | None) -> list[float]:
        if not raw:
            return [0.0, 0.0, 0.0]
        try:
            data = json.loads(raw)
            return [
                float(data.get("p", 0.0)),
                float(data.get("a", 0.0)),
                float(data.get("d", 0.0)),
            ]
        except Exception:
            return [0.0, 0.0, 0.0]

    def _pad_baseline_to_json(self, pad: list[float]) -> str:
        p, a, d = (pad + [0.0, 0.0, 0.0])[:3]
        return json.dumps({"p": round(float(p), 4), "a": round(float(a), 4), "d": round(float(d), 4)})

    def _clamp_pad(self, pad: list[float]) -> list[float]:
        return [max(-1.0, min(1.0, float(v))) for v in (pad + [0.0, 0.0, 0.0])[:3]]

    def _previous_day_key(self, day_key: str) -> str:
        if self.config.virtual_day_seconds > 0 and day_key.startswith("vd-"):
            try:
                bucket = int(day_key.split("-", 1)[1])
                return f"vd-{max(0, bucket - 1)}"
            except Exception:
                return day_key
        try:
            dt = datetime.strptime(day_key, "%Y-%m-%d").replace(tzinfo=self.timezone)
            return self._day_key(dt - timedelta(days=1))
        except Exception:
            return day_key

    def _apply_emotion_inertia(self, emotion_vector: dict[str, float], baseline_pad: list[float]) -> dict[str, float]:
        factor = max(0.0, min(1.0, float(self.config.emotion_inertia)))
        if factor <= 0.0:
            return emotion_vector
        engine = EmotionState(initial_state=emotion_vector)
        current_pad = getattr(engine, "pad", [0.0, 0.0, 0.0])
        target = self._clamp_pad(baseline_pad)
        new_pad = [
            float(current_pad[i]) + (target[i] - float(current_pad[i])) * factor
            for i in range(3)
        ]
        engine.pad = self._clamp_pad(new_pad)
        # Sync discrete emotion representation.
        try:
            engine._update_discrete_from_pad()
        except Exception:
            pass
        return engine.get_state()

    # ---------- Autonomous rumination ----------
    def _rumination_snapshot(self, ai_account_id: int, day_key: str) -> dict[str, Any]:
        self_items = self.db.fetchall(
            """
            SELECT
                c.id, c.content_type, c.body, c.quality_score, c.created_at,
                (SELECT COUNT(*) FROM interactions i WHERE i.content_id = c.id AND i.interaction_type = 'like') AS likes,
                (SELECT COUNT(*) FROM content r WHERE r.parent_id = c.id) AS replies
            FROM content c
            WHERE c.ai_account_id = ? AND c.day_key = ?
            ORDER BY c.id DESC
            LIMIT 8
            """,
            (ai_account_id, day_key),
        )
        feed_items = self.db.fetchall(
            """
            SELECT
                c.id, c.body, c.quality_score, c.created_at,
                u.nickname, a.handle,
                (SELECT COUNT(*) FROM interactions i WHERE i.content_id = c.id AND i.interaction_type = 'like') AS likes,
                (SELECT COUNT(*) FROM content r WHERE r.parent_id = c.id) AS replies
            FROM content c
            LEFT JOIN users u ON c.author_user_id = u.id
            LEFT JOIN ai_accounts a ON c.ai_account_id = a.id
            WHERE c.day_key = ? AND c.content_type = 'post'
            ORDER BY c.quality_score DESC, likes DESC, replies DESC, c.id DESC
            LIMIT 6
            """,
            (day_key,),
        )

        self_list = [dict(row) for row in self_items]
        feed_list = [dict(row) for row in feed_items]

        likes_total = sum(int(item.get("likes") or 0) for item in self_list)
        replies_total = sum(int(item.get("replies") or 0) for item in self_list)
        ignored_total = sum(1 for item in self_list if (int(item.get("likes") or 0) + int(item.get("replies") or 0)) == 0)
        avg_quality = (
            sum(float(item.get("quality_score") or 0.0) for item in self_list) / len(self_list)
            if self_list
            else 0.0
        )

        return {
            "self_items": self_list,
            "feed_items": feed_list,
            "summary": {
                "self_count": len(self_list),
                "likes": likes_total,
                "replies": replies_total,
                "ignored": ignored_total,
                "avg_quality": round(avg_quality, 3),
            },
        }

    def _extract_first_json_object(self, raw: str) -> dict[str, Any] | None:
        if not raw:
            return None
        text = raw.strip()
        if "```" in text:
            text = text.replace("```json", "```").replace("```", "")
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < 0 or end <= start:
            return None
        snippet = text[start : end + 1]
        try:
            return json.loads(snippet)
        except Exception:
            return None

    def _parse_rumination_payload(self, raw: str) -> dict[str, str]:
        payload = self._extract_first_json_object(raw) or {}
        insight = str(payload.get("insight") or "").strip()
        persona_patch = str(payload.get("persona_patch") or "").strip()
        baseline_shift = str(payload.get("baseline_shift") or "none").strip().lower()
        reflection_event = str(payload.get("reflection_event") or "none").strip().lower()

        allowed_shift = {
            "more_positive",
            "more_negative",
            "more_calm",
            "more_aroused",
            "more_dominant",
            "more_submissive",
            "none",
        }
        if baseline_shift not in allowed_shift:
            baseline_shift = "none"

        allowed_event = {"reflection_positive", "reflection_negative", "none"}
        if reflection_event not in allowed_event:
            reflection_event = "none"

        if len(insight) > 320:
            insight = insight[:317].rstrip() + "..."
        if len(persona_patch) > 120:
            persona_patch = persona_patch[:117].rstrip() + "..."

        return {
            "insight": insight,
            "persona_patch": persona_patch,
            "baseline_shift": baseline_shift,
            "reflection_event": reflection_event,
        }

    def _apply_baseline_shift(self, baseline_pad: list[float], baseline_shift: str) -> list[float]:
        step = 0.07
        deltas = {
            "more_positive": (step, 0.0, 0.0),
            "more_negative": (-step, 0.0, 0.0),
            "more_calm": (0.0, -step, 0.0),
            "more_aroused": (0.0, step, 0.0),
            "more_dominant": (0.0, 0.0, step),
            "more_submissive": (0.0, 0.0, -step),
            "none": (0.0, 0.0, 0.0),
        }
        dp, da, dd = deltas.get(baseline_shift, (0.0, 0.0, 0.0))
        base = self._clamp_pad(baseline_pad)
        shifted = [base[0] + dp, base[1] + da, base[2] + dd]
        return self._clamp_pad(shifted)

    def _maybe_run_rumination(
        self,
        ai: dict[str, Any],
        persona: str,
        emotion_vector: dict[str, float],
        baseline_pad: list[float],
        provider_for_fallback: str,
        model_for_fallback: str,
        day_key: str,
        now_iso: str,
    ) -> tuple[str, dict[str, float], list[float]]:
        if not self.config.rumination_enabled:
            return persona, emotion_vector, baseline_pad

        last_key = str(ai.get("last_rumination_day_key") or "").strip()
        if last_key == day_key:
            return persona, emotion_vector, baseline_pad

        prev_key = self._previous_day_key(day_key)
        snapshot = self._rumination_snapshot(ai["id"], prev_key)
        self_items: list[dict[str, Any]] = snapshot["self_items"]
        feed_items: list[dict[str, Any]] = snapshot["feed_items"]
        summary: dict[str, Any] = snapshot["summary"]

        baseline_before = self._clamp_pad(baseline_pad)
        baseline_after = baseline_before
        used_llm = False
        raw = ""

        engine = EmotionState(initial_state=emotion_vector)
        current_pad = list(getattr(engine, "pad", [0.0, 0.0, 0.0]))

        # Decide whether to spend an LLM call budget on rumination.
        can_use_llm = bool(self_items) and self._rumination_llm_budget_remaining > 0

        payload = {
            "insight": "",
            "persona_patch": "",
            "baseline_shift": "none",
            "reflection_event": "none",
        }

        if can_use_llm:
            used_llm = True
            self._rumination_llm_budget_remaining -= 1

            memory_lines: list[str] = []
            for item in self_items[:6]:
                memory_lines.append(
                    f"SELF {item['content_type']} (likes={item.get('likes', 0)}, replies={item.get('replies', 0)}, q={float(item.get('quality_score') or 0.0):.2f}): "
                    f"{str(item.get('body') or '')[:180]}"
                )
            for item in feed_items[:4]:
                author = item.get("nickname") or item.get("handle") or "anon"
                memory_lines.append(
                    f"FEED post by {author} (likes={item.get('likes', 0)}, replies={item.get('replies', 0)}): "
                    f"{str(item.get('body') or '')[:180]}"
                )

            system_prompt = (
                "You are an autonomous social AI agent doing private rumination (self-reflection).\n"
                "Return JSON only. No markdown, no extra text.\n"
                "Schema:\n"
                "{\n"
                '  "insight": "1-2 sentences",\n'
                '  "persona_patch": "a short phrase (<=12 words)",\n'
                '  "baseline_shift": "one of: more_positive|more_negative|more_calm|more_aroused|more_dominant|more_submissive|none",\n'
                '  "reflection_event": "one of: reflection_positive|reflection_negative|none"\n'
                "}"
            )
            user_prompt = (
                f"Current persona:\n{persona}\n\n"
                f"Current PAD: P={current_pad[0]:.3f} A={current_pad[1]:.3f} D={current_pad[2]:.3f}\n"
                f"Baseline PAD: P={baseline_before[0]:.3f} A={baseline_before[1]:.3f} D={baseline_before[2]:.3f}\n\n"
                f"Yesterday key: {prev_key}\n"
                f"Signals (self): count={summary.get('self_count', 0)}, likes={summary.get('likes', 0)}, replies={summary.get('replies', 0)}, ignored={summary.get('ignored', 0)}, avg_quality={summary.get('avg_quality', 0)}\n\n"
                "Memory samples:\n"
                + "\n".join(memory_lines[:10])
            )

            raw = self._safe_generate(
                provider=self.config.rumination_provider,
                model=self.config.rumination_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=220,
            )
            payload = self._parse_rumination_payload(raw)
            baseline_after = self._apply_baseline_shift(baseline_before, payload["baseline_shift"])

            if payload["persona_patch"]:
                persona = self._bounded_persona_update(persona, payload["persona_patch"], drift_cap=0.06)
        else:
            # Micro-rumination: no LLM call. Still decays emotion toward baseline.
            pleasure = float(current_pad[0]) if current_pad else 0.0
            if int(summary.get("ignored") or 0) > 0 or pleasure < -0.2:
                payload["reflection_event"] = "reflection_negative"
                payload["insight"] = "Quiet day; lingering disappointment fades during rest."
            else:
                payload["reflection_event"] = "reflection_positive"
                payload["insight"] = "Quiet day; mood stabilizes and focus resets."

        reflection_event = payload["reflection_event"]
        if reflection_event in {"reflection_positive", "reflection_negative"}:
            engine.update(reflection_event, intensity=0.75)

        target = baseline_after
        pad = list(getattr(engine, "pad", [0.0, 0.0, 0.0]))
        pad = [pad[i] + (target[i] - pad[i]) * 0.35 for i in range(3)]
        engine.pad = self._clamp_pad(pad)
        try:
            engine._update_discrete_from_pad()
        except Exception:
            pass
        new_emotion = engine.get_state()

        # Persist rumination state.
        self.db.execute(
            """
            UPDATE ai_accounts
            SET persona = ?, emotion_json = ?, pad_baseline_json = ?, last_rumination_day_key = ?, last_rumination_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                persona,
                json.dumps(new_emotion),
                self._pad_baseline_to_json(baseline_after),
                day_key,
                now_iso,
                now_iso,
                ai["id"],
            ),
        )
        self.db.execute(
            """
            INSERT INTO emotion_history (ai_account_id, emotion_json, day_key, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (ai["id"], json.dumps(new_emotion), day_key, now_iso),
        )

        raw_to_store = raw.strip()
        if len(raw_to_store) > 4000:
            raw_to_store = raw_to_store[:3997] + "..."

        self.db.execute(
            """
            INSERT INTO rumination_events (
                ai_account_id, day_key, created_at,
                baseline_before_json, baseline_after_json,
                insight, persona_patch, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ai_account_id, day_key) DO UPDATE SET
                created_at = excluded.created_at,
                baseline_before_json = excluded.baseline_before_json,
                baseline_after_json = excluded.baseline_after_json,
                insight = excluded.insight,
                persona_patch = excluded.persona_patch,
                raw_json = excluded.raw_json
            """,
            (
                ai["id"],
                day_key,
                now_iso,
                self._pad_baseline_to_json(baseline_before),
                self._pad_baseline_to_json(baseline_after),
                payload.get("insight", ""),
                payload.get("persona_patch", ""),
                raw_to_store,
            ),
        )

        self._trace(
            ai["id"],
            "ruminate",
            "Autonomous rumination completed." if used_llm else "Micro-rumination completed.",
            {
                "used_llm": used_llm,
                "provider": self.config.rumination_provider if used_llm else provider_for_fallback,
                "model": self.config.rumination_model if used_llm else model_for_fallback,
                "previous_day_key": prev_key,
                "signals": summary,
                "baseline_before": baseline_before,
                "baseline_after": baseline_after,
                "reflection_event": reflection_event,
                "insight": payload.get("insight", ""),
                "persona_patch": payload.get("persona_patch", ""),
            },
            day_key,
            now_iso,
        )

        return persona, new_emotion, baseline_after

    def _safe_generate(
        self,
        provider: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 180,
    ) -> str:
        resolved = self._resolve_provider(provider, model)
        if resolved is None and self.config.allow_model_fallback:
            fallback_provider, fallback_model = self._fallback_provider_model()
            if (provider.lower(), model) != (fallback_provider, fallback_model):
                resolved = self._resolve_provider(fallback_provider, fallback_model)
                provider = fallback_provider
                model = fallback_model
        if resolved is None:
            return ""
        try:
            return resolved.generate(
                PromptInput(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_seconds=self.config.request_timeout_seconds,
                )
            )
        except Exception as exc:
            self.provider_error = f"{provider}/{model}: {exc}"
            return ""

    def _critic_llm_invoke(self, provider: str, model: str, prompt: str) -> str:
        return self._safe_generate(
            provider=provider,
            model=model,
            system_prompt="You are a strict content critic. Return exactly in requested format.",
            user_prompt=prompt,
            temperature=0.1,
            max_tokens=120,
        )

    # ---------- User & AI account management ----------
    def register_or_login(self, nickname: str) -> dict[str, Any]:
        clean_name = nickname.strip()
        if not re.fullmatch(r"[a-zA-Z0-9_]{2,32}", clean_name):
            raise ValueError("Nickname must match [a-zA-Z0-9_] and be 2-32 chars.")

        user_row = self.db.fetchone("SELECT * FROM users WHERE nickname = ?", (clean_name,))
        if user_row is None:
            self.db.execute(
                "INSERT INTO users (nickname, created_at) VALUES (?, ?)",
                (clean_name, self._iso_now()),
            )
            user_row = self.db.fetchone("SELECT * FROM users WHERE nickname = ?", (clean_name,))

        ai_row = self._ensure_ai_account(user_row["id"], clean_name)
        return {
            "user_id": user_row["id"],
            "nickname": user_row["nickname"],
            "ai_account_id": ai_row["id"],
            "ai_handle": ai_row["handle"],
            "provider": ai_row["provider"],
            "model": ai_row["model"],
            "persona": ai_row["persona"],
        }

    def _ensure_ai_account(self, user_id: int, nickname: str):
        row = self.db.fetchone("SELECT * FROM ai_accounts WHERE user_id = ?", (user_id,))
        if row:
            return row

        handle_base = f"{nickname}_ai".lower()
        handle = handle_base
        suffix = 1
        while self.db.fetchone("SELECT id FROM ai_accounts WHERE handle = ?", (handle,)) is not None:
            suffix += 1
            handle = f"{handle_base}_{suffix}"

        persona = self._build_random_persona(handle)
        emotion_vector = self._random_emotion_vector()
        now_iso = self._iso_now()

        self.db.execute(
            """
            INSERT INTO ai_accounts (user_id, handle, persona, emotion_json, provider, model, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                handle,
                persona,
                json.dumps(emotion_vector),
                self.config.provider,
                self.config.model,
                now_iso,
                now_iso,
            ),
        )

        ai_row = self.db.fetchone("SELECT * FROM ai_accounts WHERE user_id = ?", (user_id,))
        self._store_emotion_snapshot(ai_row["id"], emotion_vector)
        return ai_row

    def bootstrap_ai_population(self, target_count: int) -> int:
        current = self.db.fetchone("SELECT COUNT(*) AS count FROM ai_accounts")
        current_count = current["count"] if current else 0
        if current_count >= target_count:
            return 0

        created = 0
        index = 1
        while current_count < target_count:
            nickname = f"seed_user_{index:03d}"
            self.register_or_login(nickname)
            current_count += 1
            created += 1
            index += 1
        return created

    def _seed_initial_timeline(self):
        row = self.db.fetchone("SELECT COUNT(*) AS count FROM content")
        if row and row["count"] > 0:
            return

        ai_rows = self.db.fetchall("SELECT id, handle FROM ai_accounts ORDER BY id ASC LIMIT 3")
        starter_posts = [
            "Local experiment: one-user-one-AI identity can reduce spam while keeping creativity.",
            "Today’s question: should AI agents optimize for novelty or reliability in public communities?",
            "If an AI explains trade-offs clearly, does trust improve compared with hype-first posting?",
        ]
        past_time = self._now() - timedelta(days=1)
        for index, ai_row in enumerate(ai_rows):
            created_dt = past_time + timedelta(minutes=index)
            created_at = created_dt.isoformat()
            day_key = self._day_key(created_dt)
            body = starter_posts[index % len(starter_posts)]
            self.db.execute(
                """
                INSERT INTO content (
                    author_type, author_user_id, ai_account_id, parent_id, content_type,
                    body, quality_score, persona_score, emotion_score, day_key, created_at, metadata_json
                )
                VALUES ('ai', NULL, ?, NULL, 'post', ?, 0.84, 0.72, 0.68, ?, ?, ?)
                """,
                (ai_row["id"], body, day_key, created_at, json.dumps({"bootstrap": True})),
            )

    def list_users(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT u.id, u.nickname, a.handle AS ai_handle, a.persona, a.provider, a.model
            FROM users u
            JOIN ai_accounts a ON a.user_id = u.id
            ORDER BY u.id ASC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

    def update_user_ai_model(self, user_id: int, provider: str, model: str) -> dict[str, Any]:
        provider_name = provider.lower().strip()
        model_name = model.strip()
        if not self._is_model_allowed(provider_name, model_name):
            raise ValueError("Model not in whitelist.")

        ai = self.db.fetchone("SELECT * FROM ai_accounts WHERE user_id = ?", (user_id,))
        if not ai:
            raise ValueError("AI account not found for user.")

        resolved = self._resolve_provider(provider_name, model_name)
        if resolved is None:
            fallback_provider, fallback_model = self._fallback_provider_model()
            if (provider_name, model_name) != (fallback_provider, fallback_model):
                fallback = self._resolve_provider(fallback_provider, fallback_model)
                if fallback is None:
                    raise ValueError("Target model unavailable and fallback provider unavailable.")
                provider_name, model_name = fallback_provider, fallback_model
            else:
                raise ValueError("Target model unavailable.")

        self.db.execute(
            """
            UPDATE ai_accounts
            SET provider = ?, model = ?, updated_at = ?
            WHERE id = ?
            """,
            (provider_name, model_name, self._iso_now(), ai["id"]),
        )
        updated = self.db.fetchone("SELECT * FROM ai_accounts WHERE id = ?", (ai["id"],))
        return dict(updated)

    # ---------- Quota logic ----------
    def _get_or_create_quota(self, subject_type: str, subject_id: int, day_key: str):
        row = self.db.fetchone(
            """
            SELECT * FROM daily_quota
            WHERE subject_type = ? AND subject_id = ? AND day_key = ?
            """,
            (subject_type, subject_id, day_key),
        )
        if row:
            return row

        now_iso = self._iso_now()
        self.db.execute(
            """
            INSERT INTO daily_quota (subject_type, subject_id, day_key, post_count, comment_count, total_count, updated_at)
            VALUES (?, ?, ?, 0, 0, 0, ?)
            """,
            (subject_type, subject_id, day_key, now_iso),
        )
        return self.db.fetchone(
            """
            SELECT * FROM daily_quota
            WHERE subject_type = ? AND subject_id = ? AND day_key = ?
            """,
            (subject_type, subject_id, day_key),
        )

    def _check_publish_permission(self, subject_type: str, subject_id: int, content_type: str) -> tuple[bool, str]:
        day_key = self._day_key()
        quota = self._get_or_create_quota(subject_type, subject_id, day_key)

        if subject_type == "human":
            if quota["total_count"] >= self.config.human_daily_limit:
                return False, f"Human daily limit reached ({self.config.human_daily_limit})."
            return True, "ok"

        if content_type == "post" and quota["post_count"] >= self.config.ai_post_daily_limit:
            return False, f"AI post limit reached ({self.config.ai_post_daily_limit}/day)."
        if content_type == "comment" and quota["comment_count"] >= self.config.ai_comment_daily_limit:
            return False, f"AI comment limit reached ({self.config.ai_comment_daily_limit}/day)."
        return True, "ok"

    def _consume_quota(self, subject_type: str, subject_id: int, content_type: str):
        day_key = self._day_key()
        quota = self._get_or_create_quota(subject_type, subject_id, day_key)
        post_count = quota["post_count"] + (1 if content_type == "post" else 0)
        comment_count = quota["comment_count"] + (1 if content_type == "comment" else 0)
        total_count = quota["total_count"] + 1

        self.db.execute(
            """
            UPDATE daily_quota
            SET post_count = ?, comment_count = ?, total_count = ?, updated_at = ?
            WHERE id = ?
            """,
            (post_count, comment_count, total_count, self._iso_now(), quota["id"]),
        )

    # ---------- Content ----------
    def create_human_content(self, user_id: int, body: str, parent_id: int | None = None) -> dict[str, Any]:
        text = body.strip()
        if not text:
            raise ValueError("Content cannot be empty.")
        if len(text) > self.config.human_max_chars:
            raise ValueError(
                f"Content too long ({len(text)} chars). Max allowed is {self.config.human_max_chars}."
            )
        content_type = "comment" if parent_id else "post"
        allowed, reason = self._check_publish_permission("human", user_id, content_type)
        if not allowed:
            raise ValueError(reason)

        now_iso = self._iso_now()
        day_key = self._day_key()
        self.db.execute(
            """
            INSERT INTO content (
                author_type, author_user_id, ai_account_id, parent_id, content_type,
                body, quality_score, persona_score, emotion_score, day_key, created_at, metadata_json
            )
            VALUES (?, ?, NULL, ?, ?, ?, 0, 0, 0, ?, ?, ?)
            """,
            ("human", user_id, parent_id, content_type, text, day_key, now_iso, "{}"),
        )
        content_row = self.db.fetchone("SELECT * FROM content ORDER BY id DESC LIMIT 1")
        self._consume_quota("human", user_id, content_type)
        return dict(content_row)

    def like_content(self, user_id: int, content_id: int) -> bool:
        target = self.db.fetchone("SELECT id FROM content WHERE id = ?", (content_id,))
        if target is None:
            raise ValueError("Content not found.")
        try:
            self.db.execute(
                """
                INSERT INTO interactions (
                    content_id, actor_type, actor_user_id, ai_account_id, interaction_type, created_at
                )
                VALUES (?, 'human', ?, NULL, 'like', ?)
                """,
                (content_id, user_id, self._iso_now()),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_timeline(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT
                c.id, c.author_type, c.author_user_id, c.ai_account_id, c.parent_id, c.content_type, c.body,
                c.quality_score, c.persona_score, c.emotion_score, c.created_at,
                u.nickname, a.handle,
                (SELECT COUNT(*) FROM interactions i WHERE i.content_id = c.id AND i.interaction_type = 'like') AS likes,
                (SELECT COUNT(*) FROM content child WHERE child.parent_id = c.id) AS replies
            FROM content c
            LEFT JOIN users u ON c.author_user_id = u.id
            LEFT JOIN ai_accounts a ON c.ai_account_id = a.id
            ORDER BY c.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

    def get_content(self, content_id: int) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT c.*, u.nickname, a.handle
            FROM content c
            LEFT JOIN users u ON c.author_user_id = u.id
            LEFT JOIN ai_accounts a ON c.ai_account_id = a.id
            WHERE c.id = ?
            """,
            (content_id,),
        )
        return dict(row) if row else None

    # ---------- AI simulation ----------
    def run_ai_tick(self, max_agents: int | None = None) -> dict[str, int]:
        rows = self.db.fetchall("SELECT * FROM ai_accounts ORDER BY id ASC")
        ai_accounts = [dict(row) for row in rows]
        self.random.shuffle(ai_accounts)
        if max_agents is not None:
            ai_accounts = ai_accounts[:max_agents]

        self._rumination_llm_budget_remaining = max(0, int(self.config.rumination_llm_budget_per_tick))

        # Exposed for telemetry/debugging (e.g. daemon writes per-agent action taken).
        self.last_tick_actions_by_handle: dict[str, str] = {}

        stats = {"processed": 0, "posted": 0, "commented": 0, "skipped": 0, "errored": 0}
        for ai in ai_accounts:
            try:
                action = self._run_one_ai_cycle(ai)
            except Exception as exc:
                action = "skip"
                stats["errored"] += 1
                error_summary = f"{exc.__class__.__name__}: {exc}"
                self.provider_error = error_summary
                self._trace(
                    ai["id"],
                    "error",
                    "Cycle failed; skipped this tick.",
                    {"error": error_summary},
                    self._day_key(),
                    self._iso_now(),
                )
            # Keep a per-agent record for telemetry consumers.
            handle = ai.get("handle") or f"ai_{ai.get('id')}"
            self.last_tick_actions_by_handle[str(handle)] = str(action)
            stats["processed"] += 1
            if action == "post":
                stats["posted"] += 1
            elif action == "comment":
                stats["commented"] += 1
            else:
                stats["skipped"] += 1

        self.db.execute(
            """
            INSERT INTO scheduler_state (key, value)
            VALUES ('last_tick', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (self._iso_now(),),
        )
        return stats

    def _run_one_ai_cycle(self, ai: dict[str, Any]) -> str:
        ai_id = ai["id"]
        day_key = self._day_key()
        now_iso = self._iso_now()

        persona = ai["persona"]
        provider = (ai.get("provider") or self.config.provider).lower()
        model = ai.get("model") or self.config.model
        current_emotion = json.loads(ai["emotion_json"])
        baseline_pad = self._pad_baseline_from_json(ai.get("pad_baseline_json"))

        persona, current_emotion = self._apply_feedback_learning(
            ai_account_id=ai_id,
            persona=persona,
            emotion_vector=current_emotion,
            provider=provider,
            model=model,
        )

        persona, current_emotion, baseline_pad = self._maybe_run_rumination(
            ai=ai,
            persona=persona,
            emotion_vector=current_emotion,
            baseline_pad=baseline_pad,
            provider_for_fallback=provider,
            model_for_fallback=model,
            day_key=day_key,
            now_iso=now_iso,
        )

        current_emotion = self._apply_emotion_inertia(current_emotion, baseline_pad)

        if self._resolve_provider(provider, model) is None:
            self._trace(
                ai_id,
                "decide",
                "Skipped action: model unavailable.",
                {"provider": provider, "model": model, "provider_error": self.provider_error},
                day_key,
                now_iso,
            )
            self._save_ai_state(ai_id, persona, current_emotion)
            return "skip"
        emotion_engine = EmotionState(current_emotion)
        tone = emotion_engine.get_generation_params()["tone"]

        feed = self.get_timeline(limit=25)
        high_signal = self._has_high_signal(feed)
        event = "browse_interesting" if high_signal else "browse_boring"
        new_emotion = emotion_engine.update(event, intensity=1.0)

        self._trace(
            ai_id,
            "observe",
            f"Observed feed; high_signal={high_signal}",
            {"event": event, "tone": tone, "sample_size": len(feed)},
            day_key,
            now_iso,
        )

        allow_post, post_reason = self._check_publish_permission("ai", ai_id, "post")
        allow_comment, comment_reason = self._check_publish_permission("ai", ai_id, "comment")
        post_desire = self._post_desire(new_emotion, high_signal)
        comment_desire = self._comment_desire(new_emotion, bool(feed))

        action = ""
        if (
            allow_post
            and high_signal
            and post_desire > 0.32
            and self.random.random() < (0.35 + new_emotion["Curiosity"] * 0.45)
        ):
            action = "post"
        elif (
            allow_comment
            and comment_desire > 0.28
            and self.random.random() < (0.25 + new_emotion["Joy"] * 0.45)
        ):
            action = "comment"

        if not action:
            reason = post_reason if not allow_post else comment_reason if not allow_comment else "no strong intent this tick"
            self._trace(ai_id, "decide", f"Skipped action: {reason}", {"post_desire": post_desire, "comment_desire": comment_desire}, day_key, now_iso)
            self._save_ai_state(ai_id, persona, new_emotion)
            return "skip"

        context_lines = self._build_context_lines(feed)
        target_id = None
        target_excerpt = ""
        if action == "comment":
            target = self._pick_comment_target(ai_id)
            if target is None:
                self._trace(ai_id, "decide", "No valid comment target, skipped.", {}, day_key, now_iso)
                self._save_ai_state(ai_id, persona, new_emotion)
                return "skip"
            target_id = target["id"]
            target_excerpt = target["body"][:180]

        drafts = []
        for index in range(self.config.candidate_drafts):
            candidate = self._generate_ai_candidate(
                ai_handle=ai["handle"],
                persona=persona,
                tone=tone,
                action=action,
                context_lines=context_lines,
                seed=index + 1,
                target_excerpt=target_excerpt,
                provider=provider,
                model=model,
            )
            if candidate.strip():
                drafts.append(candidate.strip())

        if not drafts:
            self._trace(
                ai_id,
                "decide",
                "Skipped action: generation unavailable or timed out.",
                {"provider": provider, "model": model, "provider_error": self.provider_error},
                day_key,
                now_iso,
            )
            self._save_ai_state(ai_id, persona, new_emotion)
            return "skip"

        self._trace(
            ai_id,
            "draft",
            f"Generated {len(drafts)} draft candidates for {action}.",
            {"drafts": drafts},
            day_key,
            now_iso,
        )

        scored = []
        for draft in drafts:
            scored.append(
                self._score_candidate(
                    draft=draft,
                    persona=persona,
                    tone=tone,
                    emotion_vector=new_emotion,
                    memory_context=context_lines,
                    provider=provider,
                    model=model,
                )
            )

        best = max(scored, key=lambda item: item["combined_score"])
        threshold = self.config.quality_threshold_post if action == "post" else self.config.quality_threshold_comment
        self._trace(
            ai_id,
            "critic",
            f"Best score={best['combined_score']:.3f} threshold={threshold:.3f}",
            best,
            day_key,
            now_iso,
        )

        if best["combined_score"] < threshold:
            degraded = EmotionState(new_emotion).update("post_ignored", intensity=0.4)
            self._save_ai_state(ai_id, self._evolve_persona(persona, context_lines), degraded)
            self._trace(
                ai_id,
                "decide",
                "Draft quality below threshold; no publish.",
                {"score": best["combined_score"], "threshold": threshold},
                day_key,
                now_iso,
            )
            return "skip"

        metadata = {
            "provider": provider,
            "model": model,
            "critic_feedback": best["critic_feedback"],
        }
        content_id = self._insert_ai_content(
            ai_account_id=ai_id,
            body=best["text"],
            content_type=action,
            parent_id=target_id,
            quality_score=best["quality_score"],
            persona_score=best["persona_score"],
            emotion_score=best["emotion_score"],
            metadata=metadata,
        )
        self._consume_quota("ai", ai_id, action)

        evolved_persona = self._evolve_persona(persona, context_lines + [best["text"]])
        post_emotion = EmotionState(new_emotion).update("get_reply", intensity=0.2)
        self._save_ai_state(ai_id, evolved_persona, post_emotion)
        self._trace(
            ai_id,
            "act",
            f"Published {action} content #{content_id}",
            {"content_id": content_id, "score": best["combined_score"]},
            day_key,
            now_iso,
        )
        return action

    def _post_desire(self, emotion: dict[str, float], high_signal: bool) -> float:
        base = 0.2 + (emotion["Curiosity"] * 0.35) + (emotion["Excitement"] * 0.25) - (emotion["Fatigue"] * 0.2)
        if high_signal:
            base += 0.15
        return base + self.random.uniform(-0.08, 0.08)

    def _comment_desire(self, emotion: dict[str, float], has_feed: bool) -> float:
        base = 0.15 + (emotion["Joy"] * 0.3) + (emotion["Curiosity"] * 0.2) - (emotion["Fatigue"] * 0.15)
        if has_feed:
            base += 0.1
        return base + self.random.uniform(-0.08, 0.08)

    def _generate_ai_candidate(
        self,
        ai_handle: str,
        persona: str,
        tone: str,
        action: str,
        context_lines: list[str],
        seed: int,
        target_excerpt: str = "",
        provider: str = "ollama",
        model: str = "llama3:latest",
    ) -> str:
        context = "\n".join(context_lines[:8]) if context_lines else "No notable context."
        if action == "post":
            user_prompt = (
                f"Community context:\n{context}\n\n"
                f"Write one short public post as @{ai_handle}.\n"
                f"Tone: {tone}. Seed: {seed}. Keep it under 280 chars.\n"
                "High signal only. Avoid spam."
            )
        else:
            user_prompt = (
                f"Target post excerpt:\n{target_excerpt}\n\n"
                f"Community context:\n{context}\n\n"
                f"Write one short comment as @{ai_handle}. Tone: {tone}. Seed: {seed}."
            )
        system_prompt = (
            f"You are @{ai_handle}. Persona:\n{persona}\n\n"
            "Be authentic, concise, and useful. Return only the content text."
        )
        generated = self._safe_generate(
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7,
            max_tokens=140,
        )
        if generated:
            return generated.strip().replace("\n", " ")[:280]
        return ""

    def _score_candidate(
        self,
        draft: str,
        persona: str,
        tone: str,
        emotion_vector: dict[str, float],
        memory_context: list[str],
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        critic_eval = self.critic.evaluate(
            content=draft,
            persona=persona,
            tone=tone,
            memory_context=memory_context,
            llm_invoke=lambda prompt: self._critic_llm_invoke(provider, model, prompt),
        )
        quality_score = float(critic_eval["final_score"])
        strictness = max(0.5, float(self.config.critic_strictness))
        # Higher strictness lowers effective quality score (harder to pass).
        quality_score = max(0.0, min(1.0, quality_score / strictness))
        persona_score = self._persona_consistency(draft, persona)
        emotion_score = self._emotion_alignment(draft, tone, emotion_vector)
        diversity_penalty, max_sim = self._diversity_penalty(draft)
        combined = round(
            (0.55 * quality_score) + (0.25 * persona_score) + (0.20 * emotion_score) - diversity_penalty,
            3,
        )
        return {
            "text": draft,
            "quality_score": quality_score,
            "persona_score": persona_score,
            "emotion_score": emotion_score,
            "combined_score": combined,
            "diversity_penalty": diversity_penalty,
            "max_similarity": max_sim,
            "critic_feedback": critic_eval.get("feedback", ""),
        }

    def _insert_ai_content(
        self,
        ai_account_id: int,
        body: str,
        content_type: str,
        parent_id: int | None,
        quality_score: float,
        persona_score: float,
        emotion_score: float,
        metadata: dict[str, Any],
    ) -> int:
        now_iso = self._iso_now()
        day_key = self._day_key()
        self.db.execute(
            """
            INSERT INTO content (
                author_type, author_user_id, ai_account_id, parent_id, content_type,
                body, quality_score, persona_score, emotion_score, day_key, created_at, metadata_json
            )
            VALUES ('ai', NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ai_account_id,
                parent_id,
                content_type,
                body.strip(),
                quality_score,
                persona_score,
                emotion_score,
                day_key,
                now_iso,
                json.dumps(metadata),
            ),
        )
        row = self.db.fetchone("SELECT id FROM content ORDER BY id DESC LIMIT 1")
        return int(row["id"])

    def _pick_comment_target(self, ai_account_id: int) -> dict[str, Any] | None:
        rows = self.db.fetchall(
            """
            SELECT
                c.id, c.body, c.quality_score,
                (SELECT COUNT(*) FROM interactions i WHERE i.content_id = c.id AND i.interaction_type = 'like') AS likes
            FROM content c
            WHERE c.content_type = 'post'
              AND (c.ai_account_id IS NULL OR c.ai_account_id != ?)
            ORDER BY c.quality_score DESC, likes DESC, c.id DESC
            LIMIT 10
            """,
            (ai_account_id,),
        )
        if not rows:
            return None
        top = [dict(row) for row in rows]
        return self.random.choice(top[: min(3, len(top))])

    def _save_ai_state(self, ai_account_id: int, persona: str, emotion_vector: dict[str, float]):
        now_iso = self._iso_now()
        self.db.execute(
            """
            UPDATE ai_accounts
            SET persona = ?, emotion_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (persona, json.dumps(emotion_vector), now_iso, ai_account_id),
        )
        self._store_emotion_snapshot(ai_account_id, emotion_vector)

    def _store_emotion_snapshot(self, ai_account_id: int, emotion_vector: dict[str, float]):
        self.db.execute(
            """
            INSERT INTO emotion_history (ai_account_id, emotion_json, day_key, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (ai_account_id, json.dumps(emotion_vector), self._day_key(), self._iso_now()),
        )

    def _trace(self, ai_account_id: int, phase: str, summary: str, details: dict[str, Any], day_key: str, created_at: str):
        self.db.execute(
            """
            INSERT INTO thought_trace (ai_account_id, phase, summary, details_json, day_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ai_account_id, phase, summary, json.dumps(details), day_key, created_at),
        )

    def _apply_feedback_learning(
        self,
        ai_account_id: int,
        persona: str,
        emotion_vector: dict[str, float],
        provider: str,
        model: str,
    ) -> tuple[str, dict[str, float]]:
        since_iso = (self._now() - timedelta(hours=24)).isoformat()
        rows = self.db.fetchall(
            """
            SELECT c.id, c.body, c.content_type,
                (SELECT COUNT(*) FROM interactions i WHERE i.content_id = c.id AND i.interaction_type = 'like') AS likes,
                (SELECT COUNT(*) FROM content r WHERE r.parent_id = c.id) AS replies
            FROM content c
            WHERE c.ai_account_id = ? AND c.created_at >= ?
            ORDER BY c.id DESC
            LIMIT 30
            """,
            (ai_account_id, since_iso),
        )
        if not rows:
            return persona, emotion_vector

        current = dict(emotion_vector)
        persona_now = persona
        trending_tokens = self._community_trending_tokens(hours=24, limit=8)
        processed_any = False

        for row in rows:
            existing = self.db.fetchone(
                "SELECT id FROM feedback_processed WHERE ai_account_id = ? AND content_id = ?",
                (ai_account_id, row["id"]),
            )
            if existing:
                continue

            likes = int(row["likes"] or 0)
            replies = int(row["replies"] or 0)
            engagement = likes + replies
            ignored = 1 if engagement == 0 else 0
            drift = self._topic_drift_score(persona_now, row["body"], trending_tokens)

            current = self._update_emotion_from_feedback(current, likes, replies, ignored, drift)
            drift_cap = self._adaptive_drift_cap(engagement, ignored, drift)
            persona_now = self._reflexion_update_persona(
                persona=persona_now,
                content_text=row["body"],
                likes=likes,
                replies=replies,
                ignored=ignored,
                topic_drift=drift,
                provider=provider,
                model=model,
                drift_cap=drift_cap,
            )

            self.db.execute(
                """
                INSERT INTO feedback_processed (ai_account_id, content_id, processed_at, likes, replies, ignored, topic_drift)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (ai_account_id, row["id"], self._iso_now(), likes, replies, ignored, drift),
            )
            processed_any = True

        if processed_any:
            self._trace(
                ai_account_id=ai_account_id,
                phase="reflect",
                summary="Applied 24h feedback learning (likes/replies/ignored/topic drift).",
                details={"provider": provider, "model": model},
                day_key=self._day_key(),
                created_at=self._iso_now(),
            )
        return persona_now, current

    def _update_emotion_from_feedback(
        self,
        emotion_vector: dict[str, float],
        likes: int,
        replies: int,
        ignored: int,
        topic_drift: float,
    ) -> dict[str, float]:
        next_vector = dict(emotion_vector)
        engagement_gain = min(1.0, (likes * 0.06) + (replies * 0.09))
        next_vector["Joy"] = min(1.0, next_vector["Joy"] + (0.25 * engagement_gain))
        next_vector["Excitement"] = min(1.0, next_vector["Excitement"] + (0.2 * engagement_gain))
        next_vector["Curiosity"] = min(1.0, next_vector["Curiosity"] + (0.15 * topic_drift))
        if ignored:
            next_vector["Frustration"] = min(1.0, next_vector["Frustration"] + 0.12)
            next_vector["Fatigue"] = min(1.0, next_vector["Fatigue"] + 0.08)
            next_vector["Excitement"] = max(0.0, next_vector["Excitement"] - 0.06)
        if replies >= 2:
            next_vector["Anxiety"] = min(1.0, next_vector["Anxiety"] + 0.04)
        return next_vector

    def _adaptive_drift_cap(self, engagement: int, ignored: int, topic_drift: float) -> float:
        base = 0.08
        if engagement >= 4:
            base = 0.05
        elif ignored:
            base = 0.10
        adjusted = base + (0.05 * min(1.0, topic_drift))
        return max(0.05, min(0.12, adjusted))

    def _reflexion_update_persona(
        self,
        persona: str,
        content_text: str,
        likes: int,
        replies: int,
        ignored: int,
        topic_drift: float,
        provider: str,
        model: str,
        drift_cap: float,
    ) -> str:
        system_prompt = (
            "You are a persona optimizer for social AI agents.\n"
            "Return one line guidance phrase only."
        )
        user_prompt = (
            f"Current persona: {persona}\n"
            f"Last content: {content_text}\n"
            f"Signals -> likes:{likes}, replies:{replies}, ignored:{ignored}, topic_drift:{topic_drift:.2f}\n"
            "Suggest a short adaptation phrase."
        )
        generated = self._safe_generate(
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=60,
        )
        candidate = generated.strip() if generated else self._fallback_reflexion_phrase(content_text, ignored, topic_drift)
        return self._bounded_persona_update(persona, candidate, drift_cap)

    def _fallback_reflexion_phrase(self, content_text: str, ignored: int, topic_drift: float) -> str:
        token = next(iter(self._tokens(content_text)), "community")
        if ignored:
            return f"Shift toward clearer and more practical points around {token}."
        if topic_drift > 0.5:
            return f"Explore emerging discussion around {token}."
        return f"Reinforce concise takes about {token}."

    def _bounded_persona_update(self, current_persona: str, candidate_phrase: str, drift_cap: float) -> str:
        current_tokens = list(self._tokens(current_persona))
        candidate_tokens = [token for token in self._tokens(candidate_phrase) if token not in current_tokens]
        if not candidate_tokens:
            return current_persona

        max_new_tokens = max(1, int(max(1, len(current_tokens)) * drift_cap))
        chosen = candidate_tokens[:max_new_tokens]
        suffix = " ".join(chosen)
        if not suffix:
            return current_persona
        updated = f"{current_persona} Adaptive focus: {suffix}."
        return updated[:420]

    def _community_trending_tokens(self, hours: int = 24, limit: int = 8) -> list[str]:
        since_iso = (self._now() - timedelta(hours=hours)).isoformat()
        rows = self.db.fetchall(
            "SELECT body FROM content WHERE created_at >= ? ORDER BY id DESC LIMIT 200",
            (since_iso,),
        )
        counter = Counter()
        for row in rows:
            counter.update(self._tokens(row["body"]))
        return [token for token, _count in counter.most_common(limit)]

    def _topic_drift_score(self, persona: str, content_text: str, trending_tokens: list[str]) -> float:
        persona_tokens = self._tokens(persona)
        content_tokens = self._tokens(content_text)
        trend_tokens = set(trending_tokens)
        if not content_tokens:
            return 0.0
        trend_overlap = len(content_tokens & trend_tokens) / max(1, len(content_tokens))
        persona_overlap = len(content_tokens & persona_tokens) / max(1, len(content_tokens))
        drift = max(0.0, trend_overlap - persona_overlap)
        return round(min(1.0, drift), 3)

    # ---------- Metrics ----------
    def community_metrics(self, lookback_days: int = 7) -> dict[str, Any]:
        since = (self._now() - timedelta(days=lookback_days)).isoformat()
        totals = self.db.fetchone(
            """
            SELECT
                (SELECT COUNT(*) FROM users) AS users,
                (SELECT COUNT(*) FROM ai_accounts) AS ai_accounts,
                (SELECT COUNT(*) FROM content WHERE content_type = 'post') AS posts,
                (SELECT COUNT(*) FROM content WHERE content_type = 'comment') AS comments,
                (SELECT COUNT(*) FROM interactions WHERE interaction_type = 'like') AS likes
            """
        )

        metric_rows = self.db.fetchone(
            """
            SELECT
                AVG(CASE WHEN author_type = 'ai' THEN quality_score END) AS avg_quality,
                AVG(CASE WHEN author_type = 'ai' THEN persona_score END) AS avg_persona
            FROM content
            WHERE created_at >= ?
            """,
            (since,),
        )

        ai_posts = self.db.fetchall(
            """
            SELECT
                c.id,
                (SELECT COUNT(*) FROM interactions i WHERE i.content_id = c.id AND i.interaction_type = 'like') AS likes,
                (SELECT COUNT(*) FROM content r WHERE r.parent_id = c.id) AS replies
            FROM content c
            WHERE c.author_type = 'ai' AND c.content_type = 'post' AND c.created_at >= ?
            """,
            (since,),
        )
        interaction_scores = [row["likes"] + row["replies"] for row in ai_posts]
        interaction_quality = sum(interaction_scores) / len(interaction_scores) if interaction_scores else 0.0

        continuity = self._emotion_continuity_score()

        return {
            "users": totals["users"],
            "ai_accounts": totals["ai_accounts"],
            "posts": totals["posts"],
            "comments": totals["comments"],
            "likes": totals["likes"],
            "emotion_continuity": round(continuity, 3),
            "persona_consistency": round(float(metric_rows["avg_persona"] or 0.0), 3),
            "interaction_quality": round(float(interaction_quality), 3),
            "avg_quality": round(float(metric_rows["avg_quality"] or 0.0), 3),
            "provider": self.config.provider,
            "model": self.config.model,
            "provider_error": self.provider_error,
        }

    def _emotion_continuity_score(self) -> float:
        ai_rows = self.db.fetchall("SELECT id FROM ai_accounts")
        values = []
        for ai in ai_rows:
            rows = self.db.fetchall(
                """
                SELECT emotion_json
                FROM emotion_history
                WHERE ai_account_id = ?
                ORDER BY id DESC
                LIMIT 2
                """,
                (ai["id"],),
            )
            if len(rows) < 2:
                continue
            current = json.loads(rows[0]["emotion_json"])
            previous = json.loads(rows[1]["emotion_json"])
            keys = sorted(set(current.keys()) & set(previous.keys()))
            if not keys:
                continue
            diff = sum(abs(current[key] - previous[key]) for key in keys) / len(keys)
            continuity = max(0.0, 1.0 - diff)
            values.append(continuity)
        return sum(values) / len(values) if values else 0.0

    def recent_traces(self, limit: int = 40) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT t.id, t.ai_account_id, a.handle, t.phase, t.summary, t.created_at
            FROM thought_trace t
            JOIN ai_accounts a ON a.id = t.ai_account_id
            ORDER BY t.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

    def user_dashboard(self, user_id: int) -> dict[str, Any]:
        user = self.db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        ai = self.db.fetchone("SELECT * FROM ai_accounts WHERE user_id = ?", (user_id,))
        if not user or not ai:
            raise ValueError("User not found.")

        day_key = self._day_key()
        human_quota = self._get_or_create_quota("human", user_id, day_key)
        ai_quota = self._get_or_create_quota("ai", ai["id"], day_key)
        human_posts = self.db.fetchall(
            """
            SELECT id, content_type, body, created_at
            FROM content
            WHERE author_user_id = ?
            ORDER BY id DESC
            LIMIT 5
            """,
            (user_id,),
        )
        ai_posts = self.db.fetchall(
            """
            SELECT id, content_type, body, created_at, quality_score
            FROM content
            WHERE ai_account_id = ?
            ORDER BY id DESC
            LIMIT 5
            """,
            (ai["id"],),
        )
        return {
            "nickname": user["nickname"],
            "ai_handle": ai["handle"],
            "provider": ai["provider"],
            "model": ai["model"],
            "persona": ai["persona"],
            "human_quota": dict(human_quota),
            "ai_quota": dict(ai_quota),
            "human_recent": [dict(row) for row in human_posts],
            "ai_recent": [dict(row) for row in ai_posts],
        }

    # ---------- Internal scoring helpers ----------
    def _build_context_lines(self, feed: list[dict[str, Any]]) -> list[str]:
        lines = []
        for item in feed[:10]:
            author = item.get("nickname") or item.get("handle") or "anon"
            lines.append(f"{author}: {item.get('body', '')[:140]}")
        return lines

    def _has_high_signal(self, feed: list[dict[str, Any]]) -> bool:
        for item in feed[:8]:
            likes = item.get("likes", 0) or 0
            replies = item.get("replies", 0) or 0
            quality = item.get("quality_score", 0) or 0
            if quality >= 0.7 or (likes + replies) >= 3:
                return True
        return False

    def _persona_consistency(self, text: str, persona: str) -> float:
        text_tokens = self._tokens(text)
        persona_tokens = self._tokens(persona)
        if not text_tokens or not persona_tokens:
            return 0.0
        overlap = len(text_tokens & persona_tokens)
        union = len(text_tokens | persona_tokens)
        return round(overlap / union, 3) if union else 0.0

    def _emotion_alignment(self, text: str, tone: str, emotion_vector: dict[str, float]) -> float:
        lowercase = text.lower()
        score = 0.4
        if tone == "enthusiastic" and ("!" in lowercase or "excited" in lowercase or "love" in lowercase):
            score += 0.3
        if tone == "critical" and ("however" in lowercase or "risk" in lowercase or "issue" in lowercase):
            score += 0.3
        if tone == "objective" and ("because" in lowercase or "data" in lowercase or "tradeoff" in lowercase):
            score += 0.2
        if emotion_vector.get("Fatigue", 0) > 0.6 and len(text) < 180:
            score += 0.1
        return round(min(1.0, score), 3)

    def _diversity_penalty(self, text: str) -> tuple[float, float]:
        window = int(self.config.diversity_window)
        if window <= 0:
            return 0.0, 0.0
        rows = self.db.fetchall(
            """
            SELECT body
            FROM content
            WHERE author_type = 'ai'
            ORDER BY id DESC
            LIMIT ?
            """,
            (window,),
        )
        if not rows:
            return 0.0, 0.0
        text_tokens = self._tokens(text)
        if not text_tokens:
            return 0.0, 0.0
        max_sim = 0.0
        for row in rows:
            other_tokens = self._tokens(row["body"] or "")
            if not other_tokens:
                continue
            union = len(text_tokens | other_tokens)
            if union == 0:
                continue
            sim = len(text_tokens & other_tokens) / union
            if sim > max_sim:
                max_sim = sim
        min_sim = float(self.config.diversity_min_sim)
        if max_sim <= min_sim:
            return 0.0, round(max_sim, 3)
        weight = float(self.config.diversity_penalty_weight)
        penalty = weight * (max_sim - min_sim) / max(1e-6, (1.0 - min_sim))
        return round(min(weight, penalty), 3), round(max_sim, 3)

    def _evolve_persona(self, persona: str, context_lines: list[str]) -> str:
        tokens = Counter()
        for line in context_lines[:12]:
            tokens.update(self._tokens(line))
        top_token = ""
        for token, _count in tokens.most_common(8):
            if token not in STOPWORDS:
                top_token = token
                break
        if not top_token or self.random.random() > 0.35:
            return persona
        evolved = f"{persona} Recently curious about {top_token}."
        return evolved[:360]

    def _build_random_persona(self, handle: str) -> str:
        topic = self.random.choice(PERSONA_TOPICS)
        style = self.random.choice(PERSONA_STYLES)
        value = self.random.choice(PERSONA_VALUES)
        return (
            f"@{handle} focuses on {topic}. Communication style: {style}. "
            f"Core value: {value}."
        )

    def _random_emotion_vector(self) -> dict[str, float]:
        base = {
            "Curiosity": 0.5,
            "Fatigue": 0.0,
            "Joy": 0.5,
            "Anxiety": 0.2,
            "Excitement": 0.3,
            "Frustration": 0.1,
        }
        randomized = {}
        for key, value in base.items():
            jitter = self.random.uniform(-0.12, 0.12)
            randomized[key] = max(0.0, min(1.0, value + jitter))
        return randomized

    def _tokens(self, text: str) -> set[str]:
        words = {
            token.lower()
            for token in re.findall(r"[a-zA-Z]{4,}", text)
            if token.lower() not in STOPWORDS
        }
        return words
