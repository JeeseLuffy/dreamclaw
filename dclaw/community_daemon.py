import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from dclaw.community_config import CommunityConfig
from dclaw.community_service import CommunityService


PID_FILE = Path("community_daemon.pid")
LOG_FILE = Path("community_daemon.log")


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
    while True:
        stats = service.run_ai_tick()
        print(
            f"[daemon] tick processed={stats['processed']} posted={stats['posted']} "
            f"commented={stats['commented']} skipped={stats['skipped']}",
            flush=True,
        )
        time.sleep(interval)
