#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dclaw.community_config import CommunityConfig
from dclaw.community_db import CommunityDB


def _clean_text(text: str, max_chars: int) -> str:
    value = html.unescape(text or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_chars]


def _rewrite_body(text: str, mode: str, max_chars: int) -> str:
    if mode == "emotional":
        rewritten = f"在人际与朋友相处上，我想到：{text}"
        return _clean_text(rewritten, max_chars)
    return _clean_text(text, max_chars)


def _matches_topic(text: str, topic_regex: re.Pattern[str] | None) -> bool:
    if topic_regex is None:
        return True
    return bool(topic_regex.search(text or ""))


def _safe_nickname(raw: str, fallback: str = "user") -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", (raw or "").strip())
    name = name.strip("_").lower()
    if not name:
        name = fallback
    if not re.fullmatch(r"[a-zA-Z0-9_]{2,32}", name):
        name = f"{fallback}_{name}"[:32]
    return name[:32]


def _day_key(now: datetime, config: CommunityConfig) -> str:
    if config.virtual_day_seconds > 0:
        bucket = int(now.timestamp()) // config.virtual_day_seconds
        return f"vd-{bucket}"
    return now.strftime("%Y-%m-%d")


def _fetch_hn_hits(tag: str, hits_per_page: int) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"tags": tag, "hitsPerPage": hits_per_page})
    url = f"https://hn.algolia.com/api/v1/search_by_date?{query}"
    request = urllib.request.Request(url=url, headers={"User-Agent": "DreamClaw/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("hits", [])


def _fetch_hn_item(item_id: str) -> dict[str, Any] | None:
    url = f"https://hn.algolia.com/api/v1/items/{urllib.parse.quote(str(item_id))}"
    request = urllib.request.Request(url=url, headers={"User-Agent": "DreamClaw/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


@dataclass
class SeedStats:
    users: int = 0
    posts: int = 0
    comments: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "users": self.users,
            "posts": self.posts,
            "comments": self.comments,
            "skipped": self.skipped,
        }


def _ensure_user(db: CommunityDB, nickname: str, created_at: str, stats: SeedStats) -> int | None:
    row = db.fetchone("SELECT id FROM users WHERE nickname = ?", (nickname,))
    if row:
        return int(row["id"])
    try:
        db.execute("INSERT INTO users (nickname, created_at) VALUES (?, ?)", (nickname, created_at))
    except Exception:
        row = db.fetchone("SELECT id FROM users WHERE nickname = ?", (nickname,))
        if row:
            return int(row["id"])
        return None
    stats.users += 1
    row = db.fetchone("SELECT id FROM users WHERE nickname = ?", (nickname,))
    return int(row["id"]) if row else None


def _insert_content(
    db: CommunityDB,
    author_user_id: int,
    parent_id: int | None,
    content_type: str,
    body: str,
    day_key: str,
    created_at: str,
    metadata: dict[str, Any],
    stats: SeedStats,
) -> int | None:
    db.execute(
        """
        INSERT INTO content (
            author_type, author_user_id, ai_account_id, parent_id, content_type,
            body, quality_score, persona_score, emotion_score, day_key, created_at, metadata_json
        )
        VALUES ('human', ?, NULL, ?, ?, ?, 0, 0, 0, ?, ?, ?)
        """,
        (author_user_id, parent_id, content_type, body, day_key, created_at, json.dumps(metadata)),
    )
    row = db.fetchone("SELECT id FROM content ORDER BY id DESC LIMIT 1")
    if not row:
        stats.skipped += 1
        return None
    if content_type == "post":
        stats.posts += 1
    else:
        stats.comments += 1
    return int(row["id"])


def seed_hn(
    db_path: Path,
    stories: int,
    comments: int,
    max_chars: int,
    throttle_ms: int,
    topic_regex: re.Pattern[str] | None,
    rewrite_mode: str,
) -> dict[str, int]:
    config = CommunityConfig.from_env()
    tz = ZoneInfo(config.timezone)
    db = CommunityDB(str(db_path))

    stats = SeedStats()
    user_cache: dict[str, int] = {}
    story_map: dict[str, int] = {}
    story_item_cache: dict[str, dict[str, Any] | None] = {}

    def get_user(author: str) -> int | None:
        nickname = f"hn_{_safe_nickname(author, 'anon')}"
        cached = user_cache.get(nickname)
        if cached is not None:
            return cached
        user_id = _ensure_user(db, nickname, datetime.now(tz).isoformat(), stats)
        if user_id is not None:
            user_cache[nickname] = user_id
        return user_id

    now = datetime.now(tz)
    day_key = _day_key(now, config)

    story_hits = _fetch_hn_hits("story", stories)
    story_hits.reverse()
    for hit in story_hits:
        title_raw = (hit.get("title") or "").strip()
        story_text_raw = (hit.get("story_text") or "").strip()
        topic_source = f"{title_raw}\n{story_text_raw}".strip()
        if not _matches_topic(topic_source, topic_regex):
            stats.skipped += 1
            continue
        author = hit.get("author") or "anon"
        user_id = get_user(author)
        if user_id is None:
            stats.skipped += 1
            continue
        title = _clean_text(title_raw, 220)
        story_text = _clean_text(story_text_raw, max_chars)
        body = title if title else "HN story"
        if story_text:
            body = _clean_text(f"{title}\n{story_text}", max_chars)
        body = _rewrite_body(body, rewrite_mode, max_chars)
        object_id = str(hit.get("objectID") or "")
        local_id = _insert_content(
            db=db,
            author_user_id=user_id,
            parent_id=None,
            content_type="post",
            body=body,
            day_key=day_key,
            created_at=datetime.now(tz).isoformat(),
            metadata={"source": "hn", "hn_object_id": object_id, "kind": "story"},
            stats=stats,
        )
        if local_id is None:
            continue
        if object_id:
            story_map[object_id] = local_id
        if throttle_ms > 0:
            time.sleep(throttle_ms / 1000.0)

    comment_hits = _fetch_hn_hits("comment", comments)
    comment_hits.reverse()
    for hit in comment_hits:
        comment_raw = (hit.get("comment_text") or "").strip()
        if not _matches_topic(comment_raw, topic_regex):
            stats.skipped += 1
            continue
        author = hit.get("author") or "anon"
        user_id = get_user(author)
        if user_id is None:
            stats.skipped += 1
            continue
        story_id = str(hit.get("story_id") or "")
        parent_local_id = story_map.get(story_id)
        if not parent_local_id and story_id:
            story_item = story_item_cache.get(story_id)
            if story_item is None and story_id not in story_item_cache:
                story_item = _fetch_hn_item(story_id)
                story_item_cache[story_id] = story_item
            if story_item:
                story_title_raw = (story_item.get("title") or "").strip()
                story_text_raw = (story_item.get("text") or "").strip()
                story_topic_source = f"{story_title_raw}\n{story_text_raw}".strip()
                if not _matches_topic(story_topic_source, topic_regex):
                    stats.skipped += 1
                    continue
                story_author = story_item.get("author") or "anon"
                story_user_id = get_user(story_author)
                if story_user_id:
                    story_title = _clean_text(story_title_raw, 220)
                    story_text = _clean_text(story_text_raw, max_chars)
                    story_body = story_title if story_title else "HN story"
                    if story_text:
                        story_body = _clean_text(f"{story_title}\n{story_text}", max_chars)
                    story_body = _rewrite_body(story_body, rewrite_mode, max_chars)
                    created_story_id = _insert_content(
                        db=db,
                        author_user_id=story_user_id,
                        parent_id=None,
                        content_type="post",
                        body=story_body,
                        day_key=day_key,
                        created_at=datetime.now(tz).isoformat(),
                        metadata={"source": "hn", "hn_object_id": story_id, "kind": "story"},
                        stats=stats,
                    )
                    if created_story_id:
                        story_map[story_id] = created_story_id
                        parent_local_id = created_story_id

        if not parent_local_id:
            stats.skipped += 1
            continue
        text = _rewrite_body(_clean_text(comment_raw, max_chars), rewrite_mode, max_chars)
        if not text:
            stats.skipped += 1
            continue

        object_id = str(hit.get("objectID") or "")
        _insert_content(
            db=db,
            author_user_id=user_id,
            parent_id=parent_local_id,
            content_type="comment",
            body=text,
            day_key=day_key,
            created_at=datetime.now(tz).isoformat(),
            metadata={"source": "hn", "hn_object_id": object_id, "kind": "comment", "hn_story_id": story_id},
            stats=stats,
        )

        if throttle_ms > 0:
            time.sleep(throttle_ms / 1000.0)

    db.close()
    return stats.as_dict()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed Hacker News threads directly into a community SQLite DB.")
    parser.add_argument("--db", required=True, help="SQLite DB path (will be created if missing)")
    parser.add_argument("--stories", type=int, default=60, help="HN story hits to fetch")
    parser.add_argument("--comments", type=int, default=200, help="HN comment hits to fetch")
    parser.add_argument("--max-chars", type=int, default=500, help="max content chars to keep")
    parser.add_argument("--throttle-ms", type=int, default=0, help="sleep per write request")
    parser.add_argument(
        "--topic-regex",
        type=str,
        default="",
        help="Only keep items matching this regex (case-insensitive).",
    )
    parser.add_argument(
        "--rewrite-mode",
        type=str,
        choices=["none", "emotional"],
        default="none",
        help="Rewrite mode for content bodies.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    topic_regex = re.compile(args.topic_regex, re.IGNORECASE) if args.topic_regex else None
    stats = seed_hn(
        db_path=Path(args.db),
        stories=max(1, args.stories),
        comments=max(1, args.comments),
        max_chars=max(50, args.max_chars),
        throttle_ms=max(0, args.throttle_ms),
        topic_regex=topic_regex,
        rewrite_mode=args.rewrite_mode,
    )
    print(json.dumps({"source": "hn", "stats": stats}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
