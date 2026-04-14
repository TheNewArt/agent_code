# Multi-agent infrastructure: Git Worktree Manager
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path


class EventBus:
    """Append-only lifecycle event log for worktrees."""

    def __init__(self, event_log_path: Path):
        self.path = event_log_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("")

    def emit(self, event: str, **extra) -> None:
        payload = {"event": event, "ts": time.time(), **extra}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    def list_recent(self, limit: int = 20) -> str:
        n = max(1, min(int(limit or 20), 200))
        lines = self.path.read_text(encoding="utf-8").splitlines()
        items = []
        for line in lines[-n:]:
            try:
                items.append(json.loads(line))
            except Exception:
                items.append({"event": "parse_error", "raw": line})
        return json.dumps(items, indent=2)


class WorktreeManager:
    """
    Create, run, and close git worktrees.
    Each worktree can be bound to a task and tracked in a local index.
    """

    def __init__(self, repo_root: Path, tasks_ref: object | None = None):
        self.repo_root = repo_root
        self.tasks_ref = tasks_ref
        self.dir = repo_root / ".worktrees"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / "index.json"
        self.events = EventBus(self.dir / "events.jsonl")
        if not self.index_path.exists():
            self.index_path.write_text(json.dumps({"worktrees": []}, indent=2))
        self.git_available = self._check_git()

    def _check_git(self) -> bool:
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.repo_root, capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _run_git(self, args: list[str]) -> str:
        if not self.git_available:
            raise RuntimeError("Not in a git repository.")
        r = subprocess.run(
            ["git", *args], cwd=self.repo_root,
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            raise RuntimeError((r.stdout + r.stderr).strip() or f"git {' '.join(args)} failed")
        return (r.stdout + r.stderr).strip() or "(no output)"

    def _load_index(self) -> dict:
        return json.loads(self.index_path.read_text())

    def _save_index(self, data: dict) -> None:
        self.index_path.write_text(json.dumps(data, indent=2))

    def _find(self, name: str) -> dict | None:
        for wt in self._load_index().get("worktrees", []):
            if wt.get("name") == name:
                return wt
        return None

    def _update_entry(self, name: str, **changes) -> dict:
        idx = self._load_index()
        updated = None
        for item in idx.get("worktrees", []):
            if item.get("name") == name:
                item.update(changes)
                updated = item
                break
        self._save_index(idx)
        if not updated:
            raise ValueError(f"Worktree '{name}' not found in index")
        return updated

    def create(self, name: str, task_id: int | None = None, base_ref: str = "HEAD") -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", name or ""):
            raise ValueError("Invalid worktree name (1-40 chars: letters, digits, ., _, -)")
        if self._find(name):
            raise ValueError(f"Worktree '{name}' already exists")
        path = self.dir / name
        branch = f"wt/{name}"
        self.events.emit("worktree.create.before", task_id=task_id, wt_name=name)
        try:
            self._run_git(["worktree", "add", "-b", branch, str(path), base_ref])
            entry = {
                "name": name, "path": str(path), "branch": branch,
                "task_id": task_id, "status": "active", "created_at": time.time(),
            }
            idx = self._load_index()
            idx["worktrees"].append(entry)
            self._save_index(idx)
            if task_id is not None and self.tasks_ref:
                try:
                    self.tasks_ref.bind_worktree(task_id, name)
                except Exception:
                    pass
            self.events.emit("worktree.create.after", task_id=task_id, wt_name=name)
            return json.dumps(entry, indent=2)
        except Exception as e:
            self.events.emit("worktree.create.failed", task_id=task_id, wt_name=name, error=str(e))
            raise

    def list_all(self) -> str:
        wts = self._load_index().get("worktrees", [])
        if not wts:
            return "No worktrees in index."
        return "\n".join(
            f"[{wt.get('status', '?')}] {wt['name']} -> {wt['path']} ({wt.get('branch', '-')})"
            + (f" task={wt['task_id']}" if wt.get("task_id") else "")
            for wt in wts
        )

    def status(self, name: str) -> str:
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"
        path = Path(wt["path"])
        if not path.exists():
            return f"Error: Worktree path missing: {path}"
        r = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=path, capture_output=True, text=True, timeout=60,
        )
        return (r.stdout + r.stderr).strip() or "Clean worktree"

    def run(self, name: str, command: str) -> str:
        dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
        if any(d in command for d in dangerous):
            return "Error: Dangerous command blocked"
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"
        path = Path(wt["path"])
        if not path.exists():
            return f"Error: Worktree path missing: {path}"
        self._update_entry(name, last_entered_at=time.time(),
                           last_command_at=time.time(), last_command_preview=command[:120])
        self.events.emit("worktree.run.before", task_id=wt.get("task_id"), wt_name=name)
        try:
            r = subprocess.run(command, shell=True, cwd=path,
                              capture_output=True, text=True, timeout=300)
            self.events.emit("worktree.run.after", task_id=wt.get("task_id"), wt_name=name)
            out = (r.stdout + r.stderr).strip()
            return out[:50000] if out else "(no output)"
        except subprocess.TimeoutExpired:
            self.events.emit("worktree.run.timeout", task_id=wt.get("task_id"), wt_name=name)
            return "Error: Timeout (300s)"

    def closeout(
        self,
        name: str,
        action: str,
        reason: str = "",
        force: bool = False,
        complete_task: bool = False,
    ) -> str:
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"
        task_id = wt.get("task_id")
        self.events.emit(f"worktree.closeout.{action}", wt_name=name, reason=reason)
        if action == "keep":
            self._update_entry(name, status="kept", kept_at=time.time(),
                               closeout={"action": "keep", "reason": reason, "at": time.time()})
            if task_id and self.tasks_ref:
                try:
                    self.tasks_ref.record_closeout(task_id, "kept", reason, True)
                except Exception:
                    pass
            return json.dumps(self._find(name), indent=2)
        elif action == "remove":
            args = ["worktree", "remove"]
            if force:
                args.append("--force")
            args.append(wt["path"])
            self._run_git(args)
            if complete_task and task_id and self.tasks_ref:
                try:
                    self.tasks_ref.update(task_id, status="completed")
                except Exception:
                    pass
            if task_id and self.tasks_ref:
                try:
                    self.tasks_ref.record_closeout(task_id, "removed", reason, False)
                except Exception:
                    pass
            self._update_entry(name, status="removed", removed_at=time.time())
            return f"Removed worktree '{name}'"
        raise ValueError("action must be 'keep' or 'remove'")

    def remove(self, name: str, force: bool = False, complete_task: bool = False, reason: str = "") -> str:
        return self.closeout(name, "remove", reason, force, complete_task)

    def keep(self, name: str) -> str:
        return self.closeout(name, "keep")
