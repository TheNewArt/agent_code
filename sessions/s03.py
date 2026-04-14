"""
s03.py — Session 03: Todo / Plan Manager
=========================================
Session-level plan tracker. Keep one item in_progress at a time.
Refresh plan on long tasks. Short (max 12 items).
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from anthropic import Anthropic
from dotenv import load_dotenv
load_dotenv(dotenv_path=r"C:\Users\10621\Desktop\code_source\agent_code\.env", override=True)

WORKDIR = Path.cwd()
MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-20250514")
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

PLAN_REMINDER_INTERVAL = 3

@dataclass
class PlanItem:
    content: str
    status: str = "pending"
    active_form: str = ""

@dataclass
class PlanningState:
    items: list[PlanItem] = field(default_factory=list)
    rounds_since_update: int = 0

class TodoManager:
    def __init__(self):
        self.state = PlanningState()

    def update(self, items: list) -> str:
        if len(items) > 12:
            raise ValueError("Keep plan short (max 12 items)")
        normalized = []
        in_progress_count = 0
        for raw in items:
            content = str(raw.get("content", "")).strip()
            status = str(raw.get("status", "pending")).lower()
            active_form = str(raw.get("activeForm", "")).strip()
            if not content:
                raise ValueError("Item content required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Invalid status: {status}")
            if status == "in_progress":
                in_progress_count += 1
            normalized.append(PlanItem(content=content, status=status, active_form=active_form))
        if in_progress_count > 1:
            raise ValueError("Only one item can be in_progress")
        self.state.items = normalized
        self.state.rounds_since_update = 0
        return self.render()

    def note_round(self):
        self.state.rounds_since_update += 1

    def reminder(self) -> Optional[str]:
        if not self.state.items:
            return None
        if self.state.rounds_since_update < PLAN_REMINDER_INTERVAL:
            return None
        return "<reminder>Refresh your session plan before continuing.</reminder>"

    def render(self) -> str:
        if not self.state.items:
            return "No plan yet."
        lines = []
        for item in self.state.items:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}[item.status]
            line = f"{marker} {item.content}"
            if item.status == "in_progress" and item.active_form:
                line += f" ({item.active_form})"
            lines.append(line)
        done = sum(1 for i in self.state.items if i.status == "completed")
        lines.append(f"\n({done}/{len(self.state.items)} completed)")
        return "\n".join(lines)

TODO = TodoManager()

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "plan_update", "description": "Update the session plan. One item can be in_progress.",
     "input_schema": {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}},
    {"name": "plan_show", "description": "Show the current session plan.",
     "input_schema": {"type": "object", "properties": {}}},
]

def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command: str) -> str:
    import subprocess
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=120)
        return (r.stdout + r.stderr).strip()[:50000] or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_read(path: str) -> str:
    try:
        return safe_path(path).read_text()[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        c = fp.read_text()
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"

TOOL_HANDLERS = {
    "bash": lambda kw: run_bash(kw["command"]),
    "read_file": lambda kw: run_read(kw["path"]),
    "write_file": lambda kw: run_write(kw["path"], kw["content"]),
    "edit_file": lambda kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "plan_update": lambda kw: TODO.update(kw["items"]),
    "plan_show": lambda kw: TODO.render(),
}

SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks.\n\nSession plan: use plan_update to set your plan before and during tasks."

def agent_loop(messages: list):
    while True:
        reminder = TODO.reminder()
        if reminder:
            messages.append({"role": "user", "content": reminder})
        response = client.messages.create(model=MODEL, system=SYSTEM, messages=messages, tools=TOOLS, max_tokens=8000)
        messages.append({"role": "assistant", "content": response.content})
        TODO.note_round()
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            handler = TOOL_HANDLERS.get(block.name)
            output = handler(block.input) if handler else f"Unknown: {block.name}"
            print(f"> {block.name}: {str(output)[:200]}")
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        messages.append({"role": "user", "content": results})

if __name__ == "__main__":
    print("s03 — Todo/plan manager. Use plan_update to set your plan.")
    history = []
    while True:
        try:
            query = input("\033[36ms03 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        content = history[-1]["content"]
        if isinstance(content, list):
            for b in content:
                if hasattr(b, "text"):
                    print(b.text)
        print()
