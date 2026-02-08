#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class SimUser:
    user_id: int
    nickname: str


class ApiClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self.base_url}{path}"
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
                return response.status, json.loads(body) if body else {}
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


class HumanTrafficSimulator:
    POST_TEMPLATES = [
        "Quick thought on {topic}: {angle}.",
        "Hot take: {topic} gets better when we optimize for {angle}.",
        "Anyone testing {topic} lately? I care about {angle}.",
        "I just read a thread about {topic}; key point is {angle}.",
    ]
    COMMENT_TEMPLATES = [
        "Nice point. I think {angle}.",
        "I partly agree, but {angle}.",
        "Could you expand this? I’m curious about {angle}.",
        "Interesting. From my side, {angle}.",
    ]
    TOPICS = [
        "agent memory",
        "emotion loops",
        "prompt critic",
        "local LLM deployment",
        "social simulation",
        "AI safety guardrails",
        "benchmark reliability",
    ]
    ANGLES = [
        "runtime stability",
        "human trust",
        "latency under load",
        "quality over quantity",
        "long-term consistency",
        "transparent labeling",
        "practical reproducibility",
    ]

    def __init__(
        self,
        client: ApiClient,
        users: int,
        duration_seconds: int,
        step_seconds: float,
        actions_per_step: int,
        post_ratio: float,
        comment_ratio: float,
        like_ratio: float,
        nickname_prefix: str,
        seed: int,
    ):
        self.client = client
        self.users = users
        self.duration_seconds = duration_seconds
        self.step_seconds = step_seconds
        self.actions_per_step = actions_per_step
        self.post_ratio = post_ratio
        self.comment_ratio = comment_ratio
        self.like_ratio = like_ratio
        self.nickname_prefix = nickname_prefix
        self.random = random.Random(seed)
        self.sim_users: list[SimUser] = []
        self.stats = {
            "login_ok": 0,
            "post_ok": 0,
            "comment_ok": 0,
            "like_ok": 0,
            "quota_reject": 0,
            "other_error": 0,
        }

    def run(self):
        self._bootstrap_users()
        if not self.sim_users:
            print("No users available. Stop.")
            return

        end_at = time.time() + self.duration_seconds
        step = 0
        while time.time() < end_at:
            step += 1
            for _ in range(self.actions_per_step):
                self._one_action()
            if step % 10 == 0:
                print(
                    f"[step={step}] post={self.stats['post_ok']} comment={self.stats['comment_ok']} "
                    f"like={self.stats['like_ok']} quota_reject={self.stats['quota_reject']} errors={self.stats['other_error']}"
                )
            time.sleep(self.step_seconds)

        print("\n=== Human traffic simulation finished ===")
        for key, value in self.stats.items():
            print(f"{key}: {value}")

    def _bootstrap_users(self):
        for index in range(1, self.users + 1):
            nickname = f"{self.nickname_prefix}_{index:03d}"
            status, data = self.client.request("POST", "/auth/login", payload={"nickname": nickname})
            if status != 200:
                self.stats["other_error"] += 1
                continue
            user_id = int(data.get("user_id") or data.get("id") or 0)
            if user_id <= 0:
                self.stats["other_error"] += 1
                continue
            self.sim_users.append(SimUser(user_id=user_id, nickname=nickname))
            self.stats["login_ok"] += 1
        print(f"bootstrapped users: {len(self.sim_users)}/{self.users}")

    def _one_action(self):
        actor = self.random.choice(self.sim_users)
        timeline = self._fetch_timeline()
        action = self._sample_action()

        if action == "post":
            body = self._gen_text(is_post=True)
            status, data = self.client.request(
                "POST",
                "/content",
                payload={"user_id": actor.user_id, "body": body, "parent_id": None},
            )
            self._record_result(status, data, "post_ok")
            return

        if action == "comment" and timeline:
            target = self.random.choice(timeline)
            body = self._gen_text(is_post=False)
            status, data = self.client.request(
                "POST",
                "/content",
                payload={"user_id": actor.user_id, "body": body, "parent_id": int(target["id"])},
            )
            self._record_result(status, data, "comment_ok")
            return

        if action == "like" and timeline:
            target = self.random.choice(timeline)
            status, data = self.client.request(
                "POST",
                f"/content/{int(target['id'])}/like",
                payload={"user_id": actor.user_id},
            )
            self._record_result(status, data, "like_ok")
            return

    def _sample_action(self) -> str:
        total = max(1e-6, self.post_ratio + self.comment_ratio + self.like_ratio)
        post_cut = self.post_ratio / total
        comment_cut = post_cut + self.comment_ratio / total
        roll = self.random.random()
        if roll < post_cut:
            return "post"
        if roll < comment_cut:
            return "comment"
        return "like"

    def _fetch_timeline(self) -> list[dict[str, Any]]:
        status, data = self.client.request("GET", "/timeline", query={"limit": 30})
        if status != 200 or not isinstance(data, list):
            return []
        return data

    def _gen_text(self, is_post: bool) -> str:
        topic = self.random.choice(self.TOPICS)
        angle = self.random.choice(self.ANGLES)
        template = self.random.choice(self.POST_TEMPLATES if is_post else self.COMMENT_TEMPLATES)
        return template.format(topic=topic, angle=angle)

    def _record_result(self, status: int, data: dict[str, Any], success_key: str):
        if status == 200:
            self.stats[success_key] += 1
            return
        detail = str(data.get("detail", "")).lower()
        if "limit reached" in detail:
            self.stats["quota_reject"] += 1
            return
        self.stats["other_error"] += 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DClaw human traffic simulator")
    parser.add_argument("--base-url", default="http://127.0.0.1:8011", help="community-online API base URL")
    parser.add_argument("--users", type=int, default=20, help="simulated human users")
    parser.add_argument("--duration-seconds", type=int, default=600, help="simulation duration")
    parser.add_argument("--step-seconds", type=float, default=1.0, help="sleep interval between action batches")
    parser.add_argument("--actions-per-step", type=int, default=5, help="actions attempted per step")
    parser.add_argument("--post-ratio", type=float, default=0.35, help="post action weight")
    parser.add_argument("--comment-ratio", type=float, default=0.35, help="comment action weight")
    parser.add_argument("--like-ratio", type=float, default=0.30, help="like action weight")
    parser.add_argument("--nickname-prefix", default="human_sim", help="nickname prefix")
    parser.add_argument("--seed", type=int, default=42, help="random seed")
    parser.add_argument("--timeout-seconds", type=float, default=10.0, help="HTTP timeout")
    return parser.parse_args()


def main():
    args = parse_args()
    client = ApiClient(base_url=args.base_url, timeout=args.timeout_seconds)
    simulator = HumanTrafficSimulator(
        client=client,
        users=max(1, args.users),
        duration_seconds=max(5, args.duration_seconds),
        step_seconds=max(0.05, args.step_seconds),
        actions_per_step=max(1, args.actions_per_step),
        post_ratio=max(0.0, args.post_ratio),
        comment_ratio=max(0.0, args.comment_ratio),
        like_ratio=max(0.0, args.like_ratio),
        nickname_prefix=args.nickname_prefix,
        seed=args.seed,
    )
    simulator.run()


if __name__ == "__main__":
    main()
