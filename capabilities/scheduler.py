# Agent capability: Cron Scheduler
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from queue import Empty, Queue


def cron_matches(expr: str, dt: datetime) -> bool:
    """
    Check if a 5-field cron expression matches a datetime.
    Fields: minute hour day-of-month month day-of-week
    Supports: *, */N, N, N-M, N,M
    """
    fields = expr.strip().split()
    if len(fields) != 5:
        return False
    values = [dt.minute, dt.hour, dt.day, dt.month, (dt.weekday() + 1) % 7]
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    for field, value, (lo, hi) in zip(fields, values, ranges):
        if not _field_matches(field, value, lo, hi):
            return False
    return True


def _field_matches(field: str, value: int, lo: int, hi: int) -> bool:
    if field == "*":
        return True
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, step_str = part.split("/", 1)
            step = int(step_str)
        if part == "*":
            if (value - lo) % step == 0:
                return True
        elif "-" in part:
            start, end = part.split("-", 1)
            start, end = int(start), int(end)
            if start <= value <= end and (value - start) % step == 0:
                return True
        else:
            if int(part) == value:
                return True
    return False


AUTO_EXPIRY_DAYS = 7


class CronScheduler:
    """
    Background cron scheduler with durable task persistence.
    Runs a background thread that checks every second.
    Fire notifications are queued and drained by the agent loop.
    """

    def __init__(self, tasks_file: Path | None = None):
        self.tasks: list[dict] = []
        self.queue: Queue = Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_check_minute = -1
        self.tasks_file = tasks_file or Path(".claude/scheduled_tasks.json")

    def start(self) -> None:
        self._load_durable()
        self._thread = threading.Thread(target=self._check_loop, daemon=True)
        self._thread.start()
        if self.tasks:
            print(f"[Cron] Loaded {len(self.tasks)} scheduled tasks")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def create(self, cron_expr: str, prompt: str, recurring: bool = True, durable: bool = False) -> str:
        task_id = str(uuid.uuid4())[:8]
        task = {
            "id": task_id,
            "cron": cron_expr,
            "prompt": prompt,
            "recurring": recurring,
            "durable": durable,
            "createdAt": time.time(),
            "jitter_offset": self._compute_jitter(cron_expr),
        }
        self.tasks.append(task)
        if durable:
            self._save_durable()
        mode = "recurring" if recurring else "one-shot"
        store = "durable" if durable else "session-only"
        return f"Created task {task_id} ({mode}, {store}): cron={cron_expr}"

    def delete(self, task_id: str) -> str:
        before = len(self.tasks)
        self.tasks = [t for t in self.tasks if t["id"] != task_id]
        if len(self.tasks) < before:
            self._save_durable()
            return f"Deleted task {task_id}"
        return f"Task {task_id} not found"

    def list_tasks(self) -> str:
        if not self.tasks:
            return "No scheduled tasks."
        lines = []
        for t in self.tasks:
            mode = "recurring" if t["recurring"] else "one-shot"
            store = "durable" if t["durable"] else "session"
            age_hours = (time.time() - t["createdAt"]) / 3600
            lines.append(
                f"  {t['id']}  {t['cron']}  [{mode}/{store}] "
                f"({age_hours:.1f}h old): {t['prompt'][:60]}"
            )
        return "\n".join(lines)

    def drain_notifications(self) -> list[str]:
        notifications = []
        while True:
            try:
                notifications.append(self.queue.get_nowait())
            except Empty:
                break
        return notifications

    def _compute_jitter(self, cron_expr: str) -> int:
        fields = cron_expr.strip().split()
        if not fields:
            return 0
        minute_field = fields[0]
        try:
            minute_val = int(minute_field)
            if minute_val in (0, 30):
                return (hash(cron_expr) % 4) + 1
        except ValueError:
            pass
        return 0

    def _check_loop(self) -> None:
        while not self._stop_event.is_set():
            now = datetime.now()
            current_minute = now.hour * 60 + now.minute
            if current_minute != self._last_check_minute:
                self._last_check_minute = current_minute
                self._check_tasks(now)
            self._stop_event.wait(timeout=1)

    def _check_tasks(self, now: datetime) -> None:
        expired = []
        fired_oneshots = []
        for task in self.tasks:
            age_days = (time.time() - task["createdAt"]) / 86400
            if task["recurring"] and age_days > AUTO_EXPIRY_DAYS:
                expired.append(task["id"])
                continue
            check_time = now
            jitter = task.get("jitter_offset", 0)
            if jitter:
                check_time = now - timedelta(minutes=jitter)
            if cron_matches(task["cron"], check_time):
                notification = f"[Scheduled task {task['id']}]: {task['prompt']}"
                self.queue.put(notification)
                task["last_fired"] = time.time()
                print(f"[Cron] Fired: {task['id']}")
                if not task["recurring"]:
                    fired_oneshots.append(task["id"])
        if expired or fired_oneshots:
            remove_ids = set(expired) | set(fired_oneshots)
            self.tasks = [t for t in self.tasks if t["id"] not in remove_ids]
            for tid in expired:
                print(f"[Cron] Auto-expired: {tid}")
            for tid in fired_oneshots:
                print(f"[Cron] One-shot completed: {tid}")
            self._save_durable()

    def _load_durable(self) -> None:
        if not self.tasks_file.exists():
            return
        try:
            data = json.loads(self.tasks_file.read_text())
            self.tasks = [t for t in data if t.get("durable")]
        except Exception as e:
            print(f"[Cron] Error loading tasks: {e}")

    def _save_durable(self) -> None:
        durable = [t for t in self.tasks if t.get("durable")]
        self.tasks_file.parent.mkdir(parents=True, exist_ok=True)
        self.tasks_file.write_text(json.dumps(durable, indent=2) + "\n")
