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


class CommunityService:
    def __init__(self, config: CommunityConfig):
        self.config = config
        self.db = CommunityDB(config.db_path)
        self.timezone = ZoneInfo(config.timezone)
        self.random = random.Random()
        self.provider = None
        self.provider_error = ""

        try:
            self.provider = build_provider(config.provider, config.model)
        except ProviderConfigurationError as exc:
            self.provider_error = str(exc)
        except Exception as exc:
            self.provider_error = f"Provider init failed: {exc}"

        self.critic = ContentCritic(
            llm=None,
            llm_invoke=self._critic_llm_invoke if self.provider else None,
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
        return local_dt.strftime("%Y-%m-%d")

    # ---------- Providers ----------
    def _safe_generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.7, max_tokens: int = 180) -> str:
        if not self.provider:
            return ""
        try:
            return self.provider.generate(
                PromptInput(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            )
        except ProviderRequestError as exc:
            self.provider_error = str(exc)
            return ""
        except Exception as exc:
            self.provider_error = str(exc)
            return ""

    def _critic_llm_invoke(self, prompt: str) -> str:
        return self._safe_generate(
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
            INSERT INTO ai_accounts (user_id, handle, persona, emotion_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, handle, persona, json.dumps(emotion_vector), now_iso, now_iso),
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
            created_at = (past_time + timedelta(minutes=index)).isoformat()
            day_key = (past_time + timedelta(minutes=index)).strftime("%Y-%m-%d")
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
            SELECT u.id, u.nickname, a.handle AS ai_handle, a.persona
            FROM users u
            JOIN ai_accounts a ON a.user_id = u.id
            ORDER BY u.id ASC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

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

        stats = {"processed": 0, "posted": 0, "commented": 0, "skipped": 0}
        for ai in ai_accounts:
            action = self._run_one_ai_cycle(ai)
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
        current_emotion = json.loads(ai["emotion_json"])
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
            drafts.append(
                self._generate_ai_candidate(
                    ai_handle=ai["handle"],
                    persona=persona,
                    tone=tone,
                    action=action,
                    context_lines=context_lines,
                    seed=index + 1,
                    target_excerpt=target_excerpt,
                )
            )

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
            "provider": self.config.provider,
            "model": self.config.model,
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
        generated = self._safe_generate(system_prompt, user_prompt, temperature=0.7, max_tokens=140)
        if generated:
            return generated.strip().replace("\n", " ")[:280]

        fallback = f"[{tone}] {context_lines[0] if context_lines else 'Sharing a quick thought.'}"
        if action == "comment":
            fallback = f"[{tone}] Good point. I’d add: {target_excerpt[:80]}"
        return fallback[:280]

    def _score_candidate(
        self,
        draft: str,
        persona: str,
        tone: str,
        emotion_vector: dict[str, float],
        memory_context: list[str],
    ) -> dict[str, Any]:
        critic_eval = self.critic.evaluate(
            content=draft,
            persona=persona,
            tone=tone,
            memory_context=memory_context,
        )
        quality_score = float(critic_eval["final_score"])
        persona_score = self._persona_consistency(draft, persona)
        emotion_score = self._emotion_alignment(draft, tone, emotion_vector)
        combined = round((0.55 * quality_score) + (0.25 * persona_score) + (0.20 * emotion_score), 3)
        return {
            "text": draft,
            "quality_score": quality_score,
            "persona_score": persona_score,
            "emotion_score": emotion_score,
            "combined_score": combined,
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
