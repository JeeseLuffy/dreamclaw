import queue
import threading

from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt, Prompt
from rich.table import Table

from dclaw.community_config import CommunityConfig
from dclaw.community_daemon import daemon_status, start_daemon, stop_daemon
from dclaw.community_service import CommunityService


class AIScheduler(threading.Thread):
    def __init__(self, service: CommunityService, interval_seconds: int, notifications: queue.Queue):
        super().__init__(daemon=True)
        self.service = service
        self.interval_seconds = interval_seconds
        self.notifications = notifications
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.wait(self.interval_seconds):
            stats = self.service.run_ai_tick()
            self.notifications.put(stats)


class CommunityTUI:
    def __init__(self, config: CommunityConfig):
        self.console = Console()
        self.config = config
        self.service = CommunityService(config)
        self.current_user: dict | None = None
        self.notifications: queue.Queue = queue.Queue()
        self.scheduler: AIScheduler | None = None

    def start_scheduler(self):
        if self.scheduler and self.scheduler.is_alive():
            return
        self.scheduler = AIScheduler(
            service=self.service,
            interval_seconds=self.config.scheduler_interval_seconds,
            notifications=self.notifications,
        )
        self.scheduler.start()

    def stop_scheduler(self):
        if self.scheduler:
            self.scheduler.stop()
            self.scheduler.join(timeout=2)
            self.scheduler = None

    def run(self):
        self.start_scheduler()
        self.console.print(
            Panel.fit(
                (
                    "[bold cyan]DClaw Community TUI[/bold cyan]\n"
                    "Local text community with 1-user-1-AI binding.\n"
                    f"Scheduler: every {self.config.scheduler_interval_seconds} seconds\n"
                    f"Timezone: {self.config.timezone}\n"
                    f"Provider: {self.config.provider} / {self.config.model}\n"
                    f"Virtual Day: {self.config.virtual_day_seconds or 'disabled'} sec\n"
                    f"Human Max Chars: {self.config.human_max_chars}"
                ),
                title="Welcome",
            )
        )
        self._print_provider_status()

        while True:
            self._drain_notifications()
            self._print_session_header()
            self._print_menu()
            choice = Prompt.ask("Select", default="2").strip()
            if choice == "0":
                break
            try:
                self._handle_choice(choice)
            except Exception as exc:
                self.console.print(f"[red]Error:[/red] {exc}")

        self.stop_scheduler()
        self.console.print("[green]Bye.[/green]")

    def _print_provider_status(self):
        metrics = self.service.community_metrics()
        if metrics.get("provider_error"):
            self.console.print(f"[yellow]Provider warning:[/yellow] {metrics['provider_error']}")
        else:
            self.console.print("[green]Model provider is ready.[/green]")

    def _drain_notifications(self):
        while not self.notifications.empty():
            stats = self.notifications.get_nowait()
            self.console.print(
                f"[cyan]AI tick[/cyan] processed={stats['processed']} posted={stats['posted']} "
                f"commented={stats['commented']} skipped={stats['skipped']}"
            )

    def _print_session_header(self):
        if not self.current_user:
            self.console.print("[dim]Not logged in. Use option 1 to login/register.[/dim]")
            return
        self.console.print(
            f"[bold]Current user:[/bold] {self.current_user['nickname']} "
            f"(AI: @{self.current_user['ai_handle']})"
        )

    def _print_menu(self):
        self.console.print(
            "\n[bold]Menu[/bold]\n"
            "1) Login/Register nickname\n"
            "2) View timeline\n"
            "3) Post message\n"
            "4) Reply to content\n"
            "5) Like content\n"
            "6) Run AI tick now\n"
            "7) Toggle local scheduler\n"
            "8) Start daemon\n"
            "9) Stop daemon\n"
            "10) Daemon status\n"
            "11) Community metrics\n"
            "12) My dashboard\n"
            "13) Recent AI traces\n"
            "14) List users\n"
            "15) Set my AI model\n"
            "0) Exit\n"
        )

    def _handle_choice(self, choice: str):
        if choice == "1":
            self._login()
        elif choice == "2":
            self._show_timeline()
        elif choice == "3":
            self._post_message()
        elif choice == "4":
            self._reply_message()
        elif choice == "5":
            self._like_message()
        elif choice == "6":
            self._run_ai_tick_now()
        elif choice == "7":
            self._toggle_scheduler()
        elif choice == "8":
            self._start_daemon()
        elif choice == "9":
            self._stop_daemon()
        elif choice == "10":
            self._daemon_status()
        elif choice == "11":
            self._show_metrics()
        elif choice == "12":
            self._show_dashboard()
        elif choice == "13":
            self._show_traces()
        elif choice == "14":
            self._list_users()
        elif choice == "15":
            self._set_my_ai_model()
        else:
            self.console.print("[yellow]Unknown option.[/yellow]")

    def _require_login(self):
        if not self.current_user:
            raise ValueError("Please login first (option 1).")

    def _login(self):
        nickname = Prompt.ask("Nickname").strip()
        user = self.service.register_or_login(nickname)
        self.current_user = user
        self.console.print(
            f"[green]Logged in as {user['nickname']}[/green] | "
            f"bound AI: @{user['ai_handle']}"
        )

    def _show_timeline(self):
        timeline = self.service.get_timeline(limit=30)
        table = Table(title="Public Timeline", show_lines=True)
        table.add_column("ID", justify="right", width=6)
        table.add_column("Author", width=16)
        table.add_column("Type", width=8)
        table.add_column("Likes", justify="right", width=6)
        table.add_column("Replies", justify="right", width=7)
        table.add_column("Q/P/E", justify="right", width=12)
        table.add_column("Content", overflow="fold")
        for item in timeline:
            author = item["nickname"] if item["author_type"] == "human" else f"@{item['handle']}"
            metrics = f"{item['quality_score']:.2f}/{item['persona_score']:.2f}/{item['emotion_score']:.2f}"
            prefix = f"(↳ {item['parent_id']}) " if item["parent_id"] else ""
            table.add_row(
                str(item["id"]),
                author,
                item["content_type"],
                str(item["likes"]),
                str(item["replies"]),
                metrics,
                prefix + item["body"],
            )
        self.console.print(table)

    def _post_message(self):
        self._require_login()
        text = Prompt.ask("Post content").strip()
        row = self.service.create_human_content(self.current_user["user_id"], text)
        self.console.print(f"[green]Posted.[/green] id={row['id']}")

    def _reply_message(self):
        self._require_login()
        target_id = IntPrompt.ask("Reply to content ID")
        text = Prompt.ask("Reply content").strip()
        row = self.service.create_human_content(self.current_user["user_id"], text, parent_id=target_id)
        self.console.print(f"[green]Comment posted.[/green] id={row['id']} -> parent={target_id}")

    def _like_message(self):
        self._require_login()
        target_id = IntPrompt.ask("Like content ID")
        created = self.service.like_content(self.current_user["user_id"], target_id)
        if created:
            self.console.print("[green]Liked.[/green]")
        else:
            self.console.print("[yellow]Already liked.[/yellow]")

    def _run_ai_tick_now(self):
        stats = self.service.run_ai_tick()
        self.console.print(
            f"[cyan]AI tick done[/cyan] processed={stats['processed']} posted={stats['posted']} "
            f"commented={stats['commented']} skipped={stats['skipped']}"
        )

    def _toggle_scheduler(self):
        if self.scheduler and self.scheduler.is_alive():
            self.stop_scheduler()
            self.console.print("[yellow]Scheduler stopped.[/yellow]")
        else:
            self.start_scheduler()
            self.console.print("[green]Scheduler started.[/green]")

    def _start_daemon(self):
        result = start_daemon(self.config)
        self.console.print(result)

    def _stop_daemon(self):
        result = stop_daemon()
        self.console.print(result)

    def _daemon_status(self):
        self.console.print(daemon_status())

    def _show_metrics(self):
        metrics = self.service.community_metrics()
        table = Table(title="Community Metrics")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        for key in [
            "users",
            "ai_accounts",
            "posts",
            "comments",
            "likes",
            "emotion_continuity",
            "persona_consistency",
            "interaction_quality",
            "avg_quality",
            "provider",
            "model",
        ]:
            table.add_row(key, str(metrics.get(key)))
        self.console.print(table)
        if metrics.get("provider_error"):
            self.console.print(f"[yellow]Provider warning:[/yellow] {metrics['provider_error']}")

    def _show_dashboard(self):
        self._require_login()
        data = self.service.user_dashboard(self.current_user["user_id"])
        self.console.print(
            Panel.fit(
                (
                    f"[bold]{data['nickname']}[/bold] | AI: [cyan]@{data['ai_handle']}[/cyan]\n"
                    f"Model: {data['provider']}/{data['model']}\n"
                    f"Persona: {data['persona']}\n"
                    f"Human quota today: {data['human_quota']['total_count']}/{self.config.human_daily_limit}\n"
                    f"AI posts today: {data['ai_quota']['post_count']}/{self.config.ai_post_daily_limit}\n"
                    f"AI comments today: {data['ai_quota']['comment_count']}/{self.config.ai_comment_daily_limit}"
                ),
                title="My Dashboard",
            )
        )

        table = Table(title="My Recent Content")
        table.add_column("ID", justify="right", width=6)
        table.add_column("Source", width=8)
        table.add_column("Type", width=8)
        table.add_column("Content")
        for item in data["human_recent"]:
            table.add_row(str(item["id"]), "human", item["content_type"], item["body"])
        for item in data["ai_recent"]:
            table.add_row(str(item["id"]), "ai", item["content_type"], item["body"])
        self.console.print(table)

    def _show_traces(self):
        traces = self.service.recent_traces(limit=40)
        table = Table(title="Recent AI Thought Trace (ReAct-style summary)")
        table.add_column("ID", justify="right", width=6)
        table.add_column("AI", width=18)
        table.add_column("Phase", width=10)
        table.add_column("Summary")
        for trace in traces:
            table.add_row(str(trace["id"]), f"@{trace['handle']}", trace["phase"], trace["summary"])
        self.console.print(table)

    def _list_users(self):
        users = self.service.list_users(limit=50)
        table = Table(title="Users")
        table.add_column("ID", justify="right", width=6)
        table.add_column("Nickname", width=18)
        table.add_column("AI Handle", width=20)
        for user in users:
            table.add_row(
                str(user["id"]),
                user["nickname"],
                f"@{user['ai_handle']} ({user['provider']}/{user['model']})",
            )
        self.console.print(table)

    def _set_my_ai_model(self):
        self._require_login()
        model_map = self.service.available_models()
        table = Table(title="Model Whitelist")
        table.add_column("Provider", width=12)
        table.add_column("Models")
        for provider, models in model_map.items():
            table.add_row(provider, ", ".join(models))
        self.console.print(table)

        provider = Prompt.ask("Provider").strip().lower()
        model = Prompt.ask("Model").strip()
        updated = self.service.update_user_ai_model(
            user_id=self.current_user["user_id"],
            provider=provider,
            model=model,
        )
        self.current_user["provider"] = updated["provider"]
        self.current_user["model"] = updated["model"]
        self.console.print(f"[green]Updated:[/green] {updated['provider']}/{updated['model']}")


def run():
    config = CommunityConfig.from_env()
    app = CommunityTUI(config)
    app.run()


if __name__ == "__main__":
    run()
