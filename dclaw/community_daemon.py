import os
import signal
import subprocess
import sys
import time
import csv
import json
from pathlib import Path

from dclaw.community_config import CommunityConfig
from dclaw.community_service import CommunityService
from dclaw.emotion import EmotionState


PID_FILE = Path("community_daemon.pid")
LOG_FILE = Path("community_daemon.log")
TELEMETRY_FILE = Path("experiment_telemetry.csv")
REPO_ROOT = Path(__file__).resolve().parents[1]
HN_SEED_SCRIPT = REPO_ROOT / "scripts" / "seed_hn_sqlite.py"
WIKI_TALK_SEED_SCRIPT = REPO_ROOT / "scripts" / "seed_wiki_talk_sqlite.py"

def _telemetry_headers() -> list[str]:
    return [
        "timestamp",
        "day_key",
        "tick_id",
        "tick_status",
        "error_type",
        "error_message",
        "tick_elapsed_s",
        "processed",
        "posted",
        "commented",
        "skipped",
        "errored",
        "agent_handle",
        "agent_action",
        "pad_p",
        "pad_a",
        "pad_d",
        "joy",
        "curiosity",
        "excitement",
        "fatigue",
        "anxiety",
        "frustration",
    ]


def _init_telemetry():
    headers = _telemetry_headers()
    if TELEMETRY_FILE.exists():
        try:
            first_line = TELEMETRY_FILE.read_text().splitlines()[0].strip()
            if first_line == ",".join(headers):
                return
            backup = TELEMETRY_FILE.with_name(
                f"{TELEMETRY_FILE.stem}.legacy-{int(time.time())}{TELEMETRY_FILE.suffix}"
            )
            TELEMETRY_FILE.rename(backup)
        except Exception:
            pass

    with open(TELEMETRY_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)


def _log_telemetry(
    service: CommunityService,
    tick_id: int,
    tick_status: str,
    error_type: str,
    error_message: str,
    stats: dict[str, int],
    tick_elapsed_s: float,
):
    try:
        rows = service.db.fetchall("SELECT handle, emotion_json FROM ai_accounts")
        # Keep telemetry time aligned with DB time semantics (timezone-aware, consistent format).
        timestamp = service._iso_now()
        day_key = service._day_key()
        actions = getattr(service, "last_tick_actions_by_handle", {}) or {}

        with open(TELEMETRY_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            for row in rows:
                emotion = json.loads(row["emotion_json"])
                es = EmotionState(initial_state=emotion)
                p, a, d = getattr(es, "pad", [0.0, 0.0, 0.0])
                handle = row["handle"]
                agent_action = actions.get(handle, "")

                writer.writerow([
                    timestamp,
                    day_key,
                    tick_id,
                    tick_status,
                    error_type,
                    error_message[:400],
                    f"{tick_elapsed_s:.3f}",
                    stats.get("processed", 0),
                    stats.get("posted", 0),
                    stats.get("commented", 0),
                    stats.get("skipped", 0),
                    stats.get("errored", 0),
                    handle,
                    agent_action,
                    f"{p:.3f}",
                    f"{a:.3f}",
                    f"{d:.3f}",
                    f"{emotion.get('Joy', 0):.3f}",
                    f"{emotion.get('Curiosity', 0):.3f}",
                    f"{emotion.get('Excitement', 0):.3f}",
                    f"{emotion.get('Fatigue', 0):.3f}",
                    f"{emotion.get('Anxiety', 0):.3f}",
                    f"{emotion.get('Frustration', 0):.3f}",
                ])
    except Exception as e:
        print(f"[telemetry error] {e}", file=sys.stderr)


def _read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None


def _is_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def daemon_status() -> str:
    pid = _read_pid()
    if pid and _is_running(pid):
        return f"[green]Daemon running[/green] (pid={pid}, log={LOG_FILE})"
    return "[yellow]Daemon not running[/yellow]"


def start_daemon(config: CommunityConfig) -> str:
    pid = _read_pid()
    if pid and _is_running(pid):
        return f"[yellow]Daemon already running[/yellow] (pid={pid})"

    # Ensure telemetry file exists
    _init_telemetry()
    
    log_handle = open(LOG_FILE, "a", buffering=1)
    command = [
        sys.executable,
        "-m",
        "dclaw.main",
        "--mode",
        "community-daemon",
        "--daemon-action",
        "run",
    ]
    env = os.environ.copy()
    process = subprocess.Popen(
        command,
        stdout=log_handle,
        stderr=log_handle,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    PID_FILE.write_text(str(process.pid))
    return f"[green]Daemon started[/green] (pid={process.pid})"


def stop_daemon() -> str:
    pid = _read_pid()
    if pid is None or not _is_running(pid):
        if PID_FILE.exists():
            PID_FILE.unlink(missing_ok=True)
        return "[yellow]Daemon not running[/yellow]"

    try:
        os.kill(pid, signal.SIGTERM)
    except Exception as exc:
        return f"[red]Failed to stop daemon:[/red] {exc}"

    for _ in range(20):
        if not _is_running(pid):
            PID_FILE.unlink(missing_ok=True)
            return f"[green]Daemon stopped[/green] (pid={pid})"
        time.sleep(0.1)

    return f"[yellow]Daemon stop requested but still running[/yellow] (pid={pid})"


def run_daemon_loop(config: CommunityConfig):
    PID_FILE.write_text(str(os.getpid()))
    service = CommunityService(config)
    interval = config.scheduler_interval_seconds

    refresh_seconds = max(0, int(os.getenv("DCLAW_HN_REFRESH_SECONDS", "0")))
    refresh_each_day = os.getenv("DCLAW_HN_REFRESH_EACH_VIRTUAL_DAY", "false").strip().lower() in {"1", "true", "yes", "on"}
    refresh_stories = max(1, int(os.getenv("DCLAW_HN_REFRESH_STORIES", os.getenv("HN_STORIES", "40"))))
    refresh_comments = max(1, int(os.getenv("DCLAW_HN_REFRESH_COMMENTS", os.getenv("HN_COMMENTS", "120"))))
    refresh_topic_regex = os.getenv("DCLAW_HN_TOPIC_REGEX", "").strip()
    refresh_rewrite_mode = os.getenv("DCLAW_HN_REWRITE_MODE", "none").strip().lower()
    refresh_max_chars = max(50, int(os.getenv("DCLAW_HN_MAX_CHARS", "500")))
    last_refresh_monotonic = time.monotonic()
    last_refresh_day_key = service._day_key()
    wiki_refresh_seconds = max(0, int(os.getenv("DCLAW_WIKI_REFRESH_SECONDS", "0")))
    wiki_refresh_each_day = os.getenv("DCLAW_WIKI_REFRESH_EACH_VIRTUAL_DAY", "false").strip().lower() in {"1", "true", "yes", "on"}
    wiki_refresh_pages = max(1, int(os.getenv("DCLAW_WIKI_REFRESH_PAGES", "30")))
    wiki_refresh_lang = os.getenv("DCLAW_WIKI_LANG", "en").strip() or "en"
    wiki_refresh_max_chars = max(0, int(os.getenv("DCLAW_WIKI_MAX_CHARS", "0")))
    wiki_refresh_throttle_ms = max(0, int(os.getenv("DCLAW_WIKI_THROTTLE_MS", "0")))
    last_wiki_refresh_monotonic = time.monotonic()
    last_wiki_refresh_day_key = service._day_key()

    _init_telemetry()
    tick_id = 0

    def maybe_refresh_hn(current_day_key: str) -> None:
        nonlocal last_refresh_monotonic, last_refresh_day_key
        should_refresh = False
        if refresh_each_day and current_day_key != last_refresh_day_key:
            should_refresh = True
        if refresh_seconds > 0 and (time.monotonic() - last_refresh_monotonic) >= refresh_seconds:
            should_refresh = True
        if not should_refresh:
            return
        if not HN_SEED_SCRIPT.exists():
            print("[daemon] HN refresh skipped: seed script missing.", file=sys.stderr, flush=True)
            return
        cmd = [
            sys.executable,
            str(HN_SEED_SCRIPT),
            "--db",
            config.db_path,
            "--stories",
            str(refresh_stories),
            "--comments",
            str(refresh_comments),
            "--max-chars",
            str(refresh_max_chars),
        ]
        if refresh_topic_regex:
            cmd += ["--topic-regex", refresh_topic_regex]
        if refresh_rewrite_mode and refresh_rewrite_mode != "none":
            cmd += ["--rewrite-mode", refresh_rewrite_mode]
        print(
            f"[daemon] HN refresh: stories={refresh_stories} comments={refresh_comments} "
            f"topic={refresh_topic_regex or 'any'} rewrite={refresh_rewrite_mode}",
            flush=True,
        )
        subprocess.run(cmd, check=False)
        last_refresh_monotonic = time.monotonic()
        last_refresh_day_key = current_day_key

    def maybe_refresh_wiki(current_day_key: str) -> None:
        nonlocal last_wiki_refresh_monotonic, last_wiki_refresh_day_key
        should_refresh = False
        if wiki_refresh_each_day and current_day_key != last_wiki_refresh_day_key:
            should_refresh = True
        if wiki_refresh_seconds > 0 and (time.monotonic() - last_wiki_refresh_monotonic) >= wiki_refresh_seconds:
            should_refresh = True
        if not should_refresh:
            return
        if not WIKI_TALK_SEED_SCRIPT.exists():
            print("[daemon] Wikipedia Talk refresh skipped: seed script missing.", file=sys.stderr, flush=True)
            return
        cmd = [
            sys.executable,
            str(WIKI_TALK_SEED_SCRIPT),
            "--db",
            config.db_path,
            "--pages",
            str(wiki_refresh_pages),
            "--lang",
            wiki_refresh_lang,
            "--max-chars",
            str(wiki_refresh_max_chars),
            "--throttle-ms",
            str(wiki_refresh_throttle_ms),
        ]
        print(
            f"[daemon] Wikipedia Talk refresh: pages={wiki_refresh_pages} lang={wiki_refresh_lang}",
            flush=True,
        )
        subprocess.run(cmd, check=False)
        last_wiki_refresh_monotonic = time.monotonic()
        last_wiki_refresh_day_key = current_day_key

    while True:
        tick_id += 1
        tick_status = "ok"
        error_type = ""
        error_message = ""
        stats = {"processed": 0, "posted": 0, "commented": 0, "skipped": 0, "errored": 0}
        tick_start = time.monotonic()

        try:
            stats = service.run_ai_tick()
            if stats.get("errored", 0) > 0:
                tick_status = "partial_error"
                error_type = "CycleError"
            elif stats.get("processed", 0) == stats.get("skipped", 0) and service.provider_error:
                tick_status = "skip_error"
                error_type = "ProviderUnavailable"
                error_message = service.provider_error
        except Exception as exc:
            tick_status = "error"
            error_type = exc.__class__.__name__
            error_message = str(exc)
            stats = {"processed": 0, "posted": 0, "commented": 0, "skipped": 0, "errored": 1}
            print(f"[daemon] tick failed: {error_type}: {error_message}", file=sys.stderr, flush=True)

        tick_elapsed_s = max(0.0, time.monotonic() - tick_start)
        day_key = service._day_key()
        maybe_refresh_hn(day_key)
        maybe_refresh_wiki(day_key)
        _log_telemetry(
            service=service,
            tick_id=tick_id,
            tick_status=tick_status,
            error_type=error_type,
            error_message=error_message,
            stats=stats,
            tick_elapsed_s=tick_elapsed_s,
        )

        print(
            f"[daemon] tick={tick_id} status={tick_status} processed={stats['processed']} "
            f"posted={stats['posted']} commented={stats['commented']} skipped={stats['skipped']}",
            flush=True,
        )
        # Keep a stable tick cadence: interval includes compute time.
        remaining = interval - tick_elapsed_s
        if remaining > 0:
            time.sleep(remaining)
