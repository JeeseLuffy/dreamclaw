#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def _normalize_body(text: str, max_chars: int) -> str:
    value = (text or "").replace("\x00", "")
    if max_chars and max_chars > 0:
        return value[:max_chars]
    return value


def _api_request(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url=url, headers={"User-Agent": "DreamClaw/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_recent_talk_pages(lang: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    rccontinue = None
    remaining = max(1, limit)
    while remaining > 0:
        batch = min(500, remaining)
        params = {
            "format": "json",
            "action": "query",
            "list": "recentchanges",
            "rcnamespace": "1",
            "rcprop": "title|ids|timestamp|user|comment",
            "rclimit": str(batch),
            "rcshow": "!bot",
            "rcdir": "older",
        }
        if rccontinue:
            params["rccontinue"] = rccontinue
        url = f"https://{lang}.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}"
        payload = _api_request(url)
        results.extend(payload.get("query", {}).get("recentchanges", []))
        rccontinue = payload.get("continue", {}).get("rccontinue")
        remaining = limit - len(results)
        if not rccontinue:
            break
    return results[:limit]


def _fetch_talk_content(lang: str, title: str) -> dict[str, Any] | None:
    params = {
        "format": "json",
        "action": "query",
        "prop": "revisions",
        "titles": title,
        "rvprop": "ids|timestamp|user|content",
        "rvslots": "main",
        "rvlimit": "1",
    }
    url = f"https://{lang}.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    payload = _api_request(url)
    pages = payload.get("query", {}).get("pages", {})
    for page in pages.values():
        revisions = page.get("revisions") or []
        if not revisions:
            continue
        revision = revisions[0]
        slots = revision.get("slots", {})
        main_slot = slots.get("main", {})
        content = (
            main_slot.get("*")
            or main_slot.get("content")
            or revision.get("*")
            or revision.get("content")
            or ""
        )
        return {
            "page_id": page.get("pageid"),
            "title": page.get("title", title),
            "revision_id": revision.get("revid"),
            "timestamp": revision.get("timestamp"),
            "user": revision.get("user"),
            "content": content,
        }
    return None


@dataclass
class SeedStats:
    users: int = 0
    posts: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "users": self.users,
            "posts": self.posts,
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


def _insert_post(
    db: CommunityDB,
    author_user_id: int,
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
        VALUES ('human', ?, NULL, NULL, 'post', ?, 0, 0, 0, ?, ?, ?)
        """,
        (author_user_id, body, day_key, created_at, json.dumps(metadata)),
    )
    row = db.fetchone("SELECT id FROM content ORDER BY id DESC LIMIT 1")
    if not row:
        stats.skipped += 1
        return None
    stats.posts += 1
    return int(row["id"])


def seed_wiki_talk(
    db_path: Path,
    pages: int,
    lang: str,
    max_chars: int,
    throttle_ms: int,
) -> dict[str, int]:
    config = CommunityConfig.from_env()
    tz = ZoneInfo(config.timezone)
    db = CommunityDB(str(db_path))
    stats = SeedStats()
    user_cache: dict[str, int] = {}

    def get_user(author: str) -> int | None:
        nickname = f"wiki_{_safe_nickname(author, 'anon')}"
        cached = user_cache.get(nickname)
        if cached is not None:
            return cached
        user_id = _ensure_user(db, nickname, datetime.now(tz).isoformat(), stats)
        if user_id is not None:
            user_cache[nickname] = user_id
        return user_id

    now = datetime.now(tz)
    day_key = _day_key(now, config)

    recent = _fetch_recent_talk_pages(lang=lang, limit=pages)
    seen_titles: set[str] = set()
    for entry in recent:
        title = entry.get("title") or ""
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        content_data = _fetch_talk_content(lang=lang, title=title)
        if not content_data:
            stats.skipped += 1
            continue
        content = _normalize_body(content_data.get("content", ""), max_chars)
        if not content:
            stats.skipped += 1
            continue
        author = content_data.get("user") or entry.get("user") or "anon"
        user_id = get_user(author)
        if user_id is None:
            stats.skipped += 1
            continue
        page_title = content_data.get("title") or title
        page_url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(page_title.replace(' ', '_'))}"
        metadata = {
            "source": "wikipedia_talk",
            "lang": lang,
            "title": page_title,
            "page_id": content_data.get("page_id"),
            "revision_id": content_data.get("revision_id"),
            "timestamp": content_data.get("timestamp"),
            "url": page_url,
            "namespace": 1,
        }
        _insert_post(
            db=db,
            author_user_id=user_id,
            body=content,
            day_key=day_key,
            created_at=datetime.now(tz).isoformat(),
            metadata=metadata,
            stats=stats,
        )
        if throttle_ms > 0:
            time.sleep(throttle_ms / 1000.0)

    db.close()
    return stats.as_dict()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed Wikipedia Talk pages into a community SQLite DB.")
    parser.add_argument("--db", required=True, help="SQLite DB path (will be created if missing)")
    parser.add_argument("--pages", type=int, default=50, help="Talk pages to fetch from recent changes")
    parser.add_argument("--lang", type=str, default="en", help="Wikipedia language code (default: en)")
    parser.add_argument("--max-chars", type=int, default=0, help="max chars to keep (0 = no trimming)")
    parser.add_argument("--throttle-ms", type=int, default=0, help="sleep per page fetch/write")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = seed_wiki_talk(
        db_path=Path(args.db),
        pages=max(1, args.pages),
        lang=args.lang.strip() or "en",
        max_chars=max(0, args.max_chars),
        throttle_ms=max(0, args.throttle_ms),
    )
    print(json.dumps({"source": "wikipedia_talk", "stats": stats}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
