#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _clean_text(text: str, max_chars: int) -> str:
    value = html.unescape(text or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_chars]


def _safe_nickname(raw: str, fallback: str = "user") -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", (raw or "").strip())
    name = name.strip("_").lower()
    if not name:
        name = fallback
    return name[:30]


@dataclass
class ApiClient:
    base_url: str
    timeout: float = 15.0

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        url = f"{self.base_url.rstrip('/')}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        data = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url=url, data=data, method=method.upper(), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                if not body:
                    return response.status, {}
                return response.status, json.loads(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8") if exc.fp else ""
            if body:
                try:
                    return exc.code, json.loads(body)
                except Exception:
                    return exc.code, {"detail": body}
            return exc.code, {"detail": str(exc)}
        except Exception as exc:
            return 0, {"detail": str(exc)}

    def login(self, nickname: str) -> int | None:
        status, data = self.request("POST", "/auth/login", payload={"nickname": nickname})
        if status != 200:
            return None
        user_id = data.get("user_id") or data.get("id")
        return int(user_id) if user_id else None

    def create_post(self, user_id: int, body: str) -> int | None:
        status, data = self.request(
            "POST",
            "/content",
            payload={"user_id": user_id, "body": body, "parent_id": None},
        )
        if status != 200:
            return None
        item_id = data.get("id")
        return int(item_id) if item_id else None

    def create_comment(self, user_id: int, body: str, parent_id: int) -> int | None:
        status, data = self.request(
            "POST",
            "/content",
            payload={"user_id": user_id, "body": body, "parent_id": parent_id},
        )
        if status != 200:
            return None
        item_id = data.get("id")
        return int(item_id) if item_id else None


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


def ingest_hn(
    client: ApiClient,
    stories: int,
    comments: int,
    max_chars: int,
    throttle_ms: int,
) -> dict[str, int]:
    stats = {"users": 0, "posts": 0, "comments": 0, "skipped": 0}
    user_cache: dict[str, int] = {}
    story_map: dict[str, int] = {}
    story_item_cache: dict[str, dict[str, Any] | None] = {}

    def get_user_id(author: str) -> int | None:
        nickname = f"hn_{_safe_nickname(author, 'anon')}"
        if nickname in user_cache:
            return user_cache[nickname]
        user_id = client.login(nickname)
        if user_id is None:
            return None
        user_cache[nickname] = user_id
        stats["users"] += 1
        return user_id

    story_hits = _fetch_hn_hits("story", stories)
    story_hits.reverse()
    for hit in story_hits:
        author = hit.get("author") or "anon"
        user_id = get_user_id(author)
        if user_id is None:
            stats["skipped"] += 1
            continue
        title = _clean_text(hit.get("title") or "", 220)
        story_text = _clean_text(hit.get("story_text") or "", max_chars)
        body = title if title else "HN story"
        if story_text:
            body = _clean_text(f"{title}\n{story_text}", max_chars)
        local_id = client.create_post(user_id, body)
        if local_id is None:
            stats["skipped"] += 1
            continue
        stats["posts"] += 1
        object_id = str(hit.get("objectID") or "")
        if object_id:
            story_map[object_id] = local_id
        if throttle_ms > 0:
            time.sleep(throttle_ms / 1000.0)

    comment_hits = _fetch_hn_hits("comment", comments)
    comment_hits.reverse()
    for hit in comment_hits:
        author = hit.get("author") or "anon"
        user_id = get_user_id(author)
        if user_id is None:
            stats["skipped"] += 1
            continue
        story_id = str(hit.get("story_id") or "")
        parent_local_id = story_map.get(story_id)
        if not parent_local_id and story_id:
            story_item = story_item_cache.get(story_id)
            if story_item is None and story_id not in story_item_cache:
                story_item = _fetch_hn_item(story_id)
                story_item_cache[story_id] = story_item
            if story_item:
                story_author = story_item.get("author") or "anon"
                story_user_id = get_user_id(story_author)
                if story_user_id:
                    story_title = _clean_text(story_item.get("title") or "", 220)
                    story_text = _clean_text(story_item.get("text") or "", max_chars)
                    story_body = story_title if story_title else "HN story"
                    if story_text:
                        story_body = _clean_text(f"{story_title}\n{story_text}", max_chars)
                    created_story_id = client.create_post(story_user_id, story_body)
                    if created_story_id:
                        story_map[story_id] = created_story_id
                        parent_local_id = created_story_id
                        stats["posts"] += 1
        if not parent_local_id:
            stats["skipped"] += 1
            continue
        text = _clean_text(hit.get("comment_text") or "", max_chars)
        if not text:
            stats["skipped"] += 1
            continue
        local_id = client.create_comment(user_id, text, parent_local_id)
        if local_id is None:
            stats["skipped"] += 1
            continue
        stats["comments"] += 1
        if throttle_ms > 0:
            time.sleep(throttle_ms / 1000.0)

    return stats


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def ingest_reddit_jsonl(
    client: ApiClient,
    path: Path,
    max_items: int,
    max_chars: int,
    throttle_ms: int,
) -> dict[str, int]:
    stats = {"users": 0, "posts": 0, "comments": 0, "skipped": 0}
    user_cache: dict[str, int] = {}
    content_map: dict[str, int] = {}

    def get_user_id(author: str) -> int | None:
        nickname = f"rd_{_safe_nickname(author, 'anon')}"
        if nickname in user_cache:
            return user_cache[nickname]
        user_id = client.login(nickname)
        if user_id is None:
            return None
        user_cache[nickname] = user_id
        stats["users"] += 1
        return user_id

    count = 0
    for item in _iter_jsonl(path):
        if count >= max_items:
            break
        count += 1
        author = str(item.get("author") or "anon")
        user_id = get_user_id(author)
        if user_id is None:
            stats["skipped"] += 1
            continue

        if "title" in item or item.get("selftext") is not None:
            title = _clean_text(str(item.get("title") or ""), 220)
            selftext = _clean_text(str(item.get("selftext") or ""), max_chars)
            body = title if title else "Reddit post"
            if selftext:
                body = _clean_text(f"{title}\n{selftext}", max_chars)
            local_id = client.create_post(user_id, body)
            if local_id is None:
                stats["skipped"] += 1
                continue
            stats["posts"] += 1
            rid = str(item.get("id") or "")
            if rid:
                content_map[f"t3_{rid}"] = local_id
                content_map[rid] = local_id
        elif item.get("body") is not None:
            body = _clean_text(str(item.get("body") or ""), max_chars)
            parent_ref = str(item.get("parent_id") or "")
            parent_local = content_map.get(parent_ref)
            if not parent_local and parent_ref.startswith("t1_"):
                parent_local = content_map.get(parent_ref[3:])
            if not parent_local and parent_ref.startswith("t3_"):
                parent_local = content_map.get(parent_ref[3:])
            if not parent_local or not body:
                stats["skipped"] += 1
                continue
            local_id = client.create_comment(user_id, body, parent_local)
            if local_id is None:
                stats["skipped"] += 1
                continue
            stats["comments"] += 1
            cid = str(item.get("id") or "")
            if cid:
                content_map[f"t1_{cid}"] = local_id
                content_map[cid] = local_id
        else:
            stats["skipped"] += 1

        if throttle_ms > 0:
            time.sleep(throttle_ms / 1000.0)

    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest real community data into DreamClaw")
    parser.add_argument("--base-url", default="http://127.0.0.1:8011", help="community-online base URL")
    parser.add_argument("--source", choices=["hn", "reddit-jsonl"], default="hn")
    parser.add_argument("--hn-stories", type=int, default=80, help="HN story hits to fetch")
    parser.add_argument("--hn-comments", type=int, default=200, help="HN comment hits to fetch")
    parser.add_argument("--reddit-jsonl-path", type=str, default="", help="path to Reddit JSONL file")
    parser.add_argument("--reddit-max-items", type=int, default=5000, help="max Reddit JSONL rows to process")
    parser.add_argument("--max-chars", type=int, default=500, help="max content chars to keep")
    parser.add_argument("--throttle-ms", type=int, default=30, help="sleep per write request")
    return parser.parse_args()


def main():
    args = parse_args()
    client = ApiClient(base_url=args.base_url)

    if args.source == "hn":
        stats = ingest_hn(
            client=client,
            stories=max(1, args.hn_stories),
            comments=max(1, args.hn_comments),
            max_chars=max(50, args.max_chars),
            throttle_ms=max(0, args.throttle_ms),
        )
    else:
        path = Path(args.reddit_jsonl_path)
        if not path.exists():
            raise SystemExit(f"Reddit JSONL not found: {path}")
        stats = ingest_reddit_jsonl(
            client=client,
            path=path,
            max_items=max(1, args.reddit_max_items),
            max_chars=max(50, args.max_chars),
            throttle_ms=max(0, args.throttle_ms),
        )

    print(json.dumps({"source": args.source, "stats": stats}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
