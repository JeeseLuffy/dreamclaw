import os
import signal
import subprocess
import sys
import time
import csv
import json
from pathlib import Path
from datetime import datetime

from dclaw.community_config import CommunityConfig
from dclaw.community_service import CommunityService
from dclaw.emotion import EmotionState


PID_FILE = Path("community_daemon.pid")
LOG_FILE = Path("community_daemon.log")
TELEMETRY_FILE = Path("experiment_telemetry.csv")

def _telemetry_headers() -> list[str]:
    return [
        "timestamp",
        "tick_id",
        "tick_status",
        "error_type",
        "error_message",
        "processed",
        "posted",
        "commented",
        "skipped",
        "errored",
        "agent_handle",
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
):
    try:
        rows = service.db.fetchall("SELECT handle, emotion_json FROM ai_accounts")
        timestamp = datetime.now().isoformat()

        with open(TELEMETRY_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            for row in rows:
                emotion = json.loads(row["emotion_json"])
                es = EmotionState(initial_state=emotion)
                p, a, d = getattr(es, "pad", [0.0, 0.0, 0.0])

                writer.writerow([
                    timestamp,
                    tick_id,
                    tick_status,
                    error_type,
                    error_message[:400],
                    stats.get("processed", 0),
                    stats.get("posted", 0),
                    stats.get("commented", 0),
                    stats.get("skipped", 0),
                    stats.get("errored", 0),
                    row["handle"],
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

    _init_telemetry()
    tick_id = 0

    while True:
        tick_id += 1
        tick_status = "ok"
        error_type = ""
        error_message = ""
        stats = {"processed": 0, "posted": 0, "commented": 0, "skipped": 0, "errored": 0}

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

        _log_telemetry(
            service=service,
            tick_id=tick_id,
            tick_status=tick_status,
            error_type=error_type,
            error_message=error_message,
            stats=stats,
        )

        print(
            f"[daemon] tick={tick_id} status={tick_status} processed={stats['processed']} "
            f"posted={stats['posted']} commented={stats['commented']} skipped={stats['skipped']}",
            flush=True,
        )
        time.sleep(interval)
