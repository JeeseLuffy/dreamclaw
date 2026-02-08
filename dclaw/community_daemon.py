import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from dclaw.community_config import CommunityConfig
from dclaw.community_service import CommunityService


import csv
import json
from datetime import datetime

PID_FILE = Path("community_daemon.pid")
LOG_FILE = Path("community_daemon.log")
TELEMETRY_FILE = Path("experiment_telemetry.csv")

def _init_telemetry():
    if not TELEMETRY_FILE.exists():
        with open(TELEMETRY_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "agent_handle", 
                "pad_p", "pad_a", "pad_d",
                "joy", "curiosity", "excitement", "fatigue", "anxiety", "frustration"
            ])

def _log_telemetry(service: CommunityService):
    try:
        rows = service.db.fetchall("SELECT handle, emotion_json FROM ai_accounts")
        timestamp = datetime.now().isoformat()
        
        with open(TELEMETRY_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            for row in rows:
                emotion = json.loads(row["emotion_json"])
                # Handle both PAD-aware and legacy emotion vectors
                # If PAD is missing, calculate it (lazy approximation or just 0s if not supported)
                # But since we updated EmotionState, we can instantiate it to get PAD
                from dclaw.emotion import EmotionState
                es = EmotionState(initial_state=emotion)
                # Access private member .pad directly or use a getter if available?
                # I added .pad attribute in step 490.
                p, a, d = getattr(es, 'pad', [0.0, 0.0, 0.0])
                
                writer.writerow([
                    timestamp, row["handle"],
                    f"{p:.3f}", f"{a:.3f}", f"{d:.3f}",
                    f"{emotion.get('Joy',0):.3f}", f"{emotion.get('Curiosity',0):.3f}",
                    f"{emotion.get('Excitement',0):.3f}",
                    f"{emotion.get('Fatigue',0):.3f}", f"{emotion.get('Anxiety',0):.3f}",
                    f"{emotion.get('Frustration',0):.3f}"
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
    
    # Initialize telemetry in the daemon process too
    _init_telemetry()
    
    while True:
        stats = service.run_ai_tick()
        
        # Log telemetry every tick
        _log_telemetry(service)
        
        print(
            f"[daemon] tick processed={stats['processed']} posted={stats['posted']} "
            f"commented={stats['commented']} skipped={stats['skipped']}",
            flush=True,
        )
        time.sleep(interval)
