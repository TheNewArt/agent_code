# Core: Unified Agent Loop
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
load_dotenv(dotenv_path=r"C:\Users\10621\Desktop\code_source\agent_code\.env", override=True)          # 加载 .env，覆盖系统默认

from anthropic import Anthropic, APIError

from infra.base import extract_text, normalize_messages, read_file, run_bash, write_file, edit_file
from capabilities.compact import CompactState, compact_history, estimate_context_size, micro_compact, persist_large_output, track_recent_file
from capabilities.hooks import HookManager
from capabilities.memory import MemoryManager
from capabilities.permissions import PermissionManager
from capabilities.scheduler import CronScheduler
from capabilities.skills import SkillRegistry
from capabilities.tasks import TaskManager
from capabilities.todo import TodoManager
from capabilities.background import BackgroundManager


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
WORKDIR = Path(os.getenv("AGENT_WORKDIR", Path.cwd()))
MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-20250514")
_ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "")
_client = Anthropic(base_url=_ANTHROPIC_BASE_URL) if _ANTHROPIC_BASE_URL else Anthropic()


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------
BASE_TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to a file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in a file once.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
]


def build_tools(registry: "AgentRegistry") -> list[dict]:
    """Build the full tool list based on enabled capabilities."""
    tools = list(BASE_TOOLS)
    if registry.skills:
        tools.append({"name": "load_skill", "description": "Load the full body of a named skill into context.",
                      "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}})
    if registry.memory:
        tools.append({"name": "save_memory", "description": "Save a persistent memory.",
                      "input_schema": {"type": "object", "properties": {
                          "name": {"type": "string"}, "description": {"type": "string"},
                          "type": {"type": "string", "enum": ["user", "feedback", "project", "reference"]},
                          "content": {"type": "string"}}, "required": ["name", "description", "type", "content"]}})
    if registry.tasks:
        tools.extend([
            {"name": "task_create", "description": "Create a new task.",
             "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}}, "required": ["subject"]}},
            {"name": "task_update", "description": "Update a task.",
             "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "deleted"]}, "owner": {"type": "string"}}, "required": ["task_id"]}},
            {"name": "task_list", "description": "List all tasks.",
             "input_schema": {"type": "object", "properties": {}}},
            {"name": "task_get", "description": "Get task by ID.",
             "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
        ])
    if registry.cron:
        tools.extend([
            {"name": "cron_create", "description": "Schedule a recurring or one-shot task.",
             "input_schema": {"type": "object", "properties": {"cron": {"type": "string"}, "prompt": {"type": "string"}, "recurring": {"type": "boolean"}, "durable": {"type": "boolean"}}, "required": ["cron", "prompt"]}},
            {"name": "cron_delete", "description": "Delete a scheduled task.",
             "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
            {"name": "cron_list", "description": "List scheduled tasks.",
             "input_schema": {"type": "object", "properties": {}}},
        ])
    if registry.background:
        tools.extend([
            {"name": "background_run", "description": "Run a command in background.",
             "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
            {"name": "check_background", "description": "Check background task status.",
             "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}}},
        ])
    if registry.todo:
        tools.append({"name": "plan_update", "description": "Update the session plan.",
                       "input_schema": {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}})
    return tools


# ---------------------------------------------------------------------------
# Registry — holds all capability instances for a session
# ---------------------------------------------------------------------------
@dataclass
class AgentRegistry:
    skills: Optional[SkillRegistry] = None
    memory: Optional[MemoryManager] = None
    tasks: Optional[TaskManager] = None
    cron: Optional[CronScheduler] = None
    background: Optional[BackgroundManager] = None
    todo: Optional[TodoManager] = None
    hooks: Optional[HookManager] = None
    permissions: Optional[PermissionManager] = None
    compact: Optional[CompactState] = None
    worktrees: Optional[Any] = None  # WorktreeManager
    message_bus: Optional[Any] = None  # MessageBus
    skill_dir: Path = Path("skills")
    memory_dir: Path = Path(".memory")
    tasks_dir: Path = Path(".tasks")
    workdir: Path = Path.cwd()


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------
def execute_tool(name: str, args: dict, registry: AgentRegistry, tool_use_id: str = "") -> str:
    # Base tools
    if name == "bash":
        return run_bash(args["command"], registry.workdir)
    if name == "read_file":
        p = args["path"]
        if registry.compact:
            track_recent_file(registry.compact, p)
        content = read_file(p, registry.workdir, args.get("limit"))
        if registry.compact and len(content) > 30000:
            return persist_large_output(f"read_{hash(p) % 100000}", content)
        return content
    if name == "write_file":
        return write_file(args["path"], args["content"], registry.workdir)
    if name == "edit_file":
        return edit_file(args["path"], args["old_text"], args["new_text"], registry.workdir)

    # Skills
    if name == "load_skill" and registry.skills:
        return registry.skills.load_full_text(args["name"])

    # Memory
    if name == "save_memory" and registry.memory:
        return registry.memory.save_memory(args["name"], args["description"], args["type"], args["content"])

    # Tasks
    if name == "task_create" and registry.tasks:
        return registry.tasks.create(args["subject"], args.get("description", ""))
    if name == "task_update" and registry.tasks:
        return registry.tasks.update(args["task_id"], args.get("status"), args.get("owner"))
    if name == "task_list" and registry.tasks:
        return registry.tasks.list_all()
    if name == "task_get" and registry.tasks:
        return registry.tasks.get(args["task_id"])

    # Cron
    if name == "cron_create" and registry.cron:
        return registry.cron.create(args["cron"], args["prompt"],
                                   args.get("recurring", True), args.get("durable", False))
    if name == "cron_delete" and registry.cron:
        return registry.cron.delete(args["id"])
    if name == "cron_list" and registry.cron:
        return registry.cron.list_tasks()

    # Background
    if name == "background_run" and registry.background:
        return registry.background.run(args["command"])
    if name == "check_background" and registry.background:
        return registry.background.check(args.get("task_id"))

    # Todo
    if name == "plan_update" and registry.todo:
        return registry.todo.update(args["items"])

    return f"Unknown tool: {name}"


# ---------------------------------------------------------------------------
# Error recovery
# ---------------------------------------------------------------------------
MAX_RECOVERY_ATTEMPTS = 3
BACKOFF_BASE_DELAY = 1.0
BACKOFF_MAX_DELAY = 30.0
TOKEN_THRESHOLD = 50000
CONTINUATION_MESSAGE = (
    "Output limit hit. Continue directly from where you stopped -- "
    "no recap, no repetition."
)


def backoff_delay(attempt: int) -> float:
    d = min(BACKOFF_BASE_DELAY * (2 ** attempt), BACKOFF_MAX_DELAY)
    return d + random.uniform(0, 1)


def do_auto_compact(client, model: str, messages: list) -> list:
    text = json.dumps(messages, default=str)[:80000]
    prompt = (
        "Summarize this coding-agent conversation for continuity.\n"
        "Preserve: goal, current state, files touched, decisions, remaining work.\n\n" + text
    )
    try:
        r = client.messages.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=4000)
        summary = r.content[0].text
    except Exception as e:
        summary = f"(compact failed: {e})"
    return [{"role": "user", "content": (
        "This session continues from a prior compacted conversation.\n\n"
        f"Summary:\n{summary}\n\nContinue from where we left off."
    )}]


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------
def run_agent_loop(
    system_prompt: str,
    registry: AgentRegistry,
    max_tokens_per_call: int = 8000,
) -> None:
    """
    Unified interactive agent loop.

    Args:
        system_prompt: Base system prompt for the agent.
        registry: AgentRegistry with all capability instances.
        max_tokens_per_call: Max tokens per API call.
    """
    tools = build_tools(registry)
    history: list = []
    max_output_recovery_count = 0

    def build_system() -> str:
        parts = [system_prompt]
        if registry.skills:
            parts.append(f"\nAvailable skills:\n{registry.skills.describe_available()}")
        if registry.memory:
            ms = registry.memory.load_memory_prompt()
            if ms:
                parts.append(f"\n{ms}")
        return "\n\n".join(parts)

    while True:
        # Drain cron notifications
        if registry.cron:
            for note in registry.cron.drain_notifications():
                print(f"[Cron] {note[:100]}")
                history.append({"role": "user", "content": note})

        # Drain background task notifications
        if registry.background:
            for n in registry.background.drain_notifications():
                history.append({"role": "user", "content": f"[bg:{n['task_id']}] {n['status']}: {n['preview']}"})

        # Drain inbox messages (multi-agent)
        if registry.message_bus:
            inbox = registry.message_bus.read_inbox("lead")
            for msg in inbox:
                history.append({"role": "user", "content": f"<inbox>{json.dumps(msg)}</inbox>"})

        # Proactive context size check
        if registry.compact and estimate_context_size(history) > TOKEN_THRESHOLD:
            print("[auto compact]")
            history[:] = compact_history(_client, MODEL, history, registry.compact)

        # Fire SessionStart hooks
        if registry.hooks:
            registry.hooks.run_hooks("SessionStart", {})

        # --- API call with recovery ---
        response = None
        for attempt in range(MAX_RECOVERY_ATTEMPTS + 1):
            try:
                response = _client.messages.create(
                    model=MODEL,
                    system=build_system(),
                    messages=normalize_messages(history),
                    tools=tools,
                    max_tokens=max_tokens_per_call,
                )
                break
            except APIError as e:
                err = str(e).lower()
                if "overlong_prompt" in err or ("prompt" in err and "long" in err):
                    print("[Recovery] Prompt too long, compacting...")
                    history[:] = do_auto_compact(_client, MODEL, history)
                    continue
                if attempt < MAX_RECOVERY_ATTEMPTS:
                    d = backoff_delay(attempt)
                    print(f"[Recovery] API error: {e}. Retrying in {d:.1f}s...")
                    time.sleep(d)
                    continue
                print(f"[Error] API failed after {MAX_RECOVERY_ATTEMPTS} retries: {e}")
                return
            except (ConnectionError, TimeoutError, OSError) as e:
                if attempt < MAX_RECOVERY_ATTEMPTS:
                    d = backoff_delay(attempt)
                    print(f"[Recovery] Connection error: {e}. Retrying in {d:.1f}s...")
                    time.sleep(d)
                    continue
                print(f"[Error] Connection failed: {e}")
                return

        if response is None:
            print("[Error] No response received.")
            return

        history.append({"role": "assistant", "content": response.content})

        # max_tokens recovery
        if response.stop_reason == "max_tokens":
            max_output_recovery_count += 1
            if max_output_recovery_count <= MAX_RECOVERY_ATTEMPTS:
                print(f"[Recovery] max_tokens hit ({max_output_recovery_count}/{MAX_RECOVERY_ATTEMPTS}).")
                history.append({"role": "user", "content": CONTINUATION_MESSAGE})
                continue
            else:
                print("[Error] max_tokens recovery exhausted.")
                return
        max_output_recovery_count = 0

        if response.stop_reason != "tool_use":
            # Print final text
            final = extract_text(history[-1]["content"])
            if final:
                print(final)
            return

        # --- Process tool calls ---
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_input = dict(block.input or {})

            # Permission check
            if registry.permissions:
                decision = registry.permissions.check(block.name, tool_input)
                if decision["behavior"] == "deny":
                    output = f"Permission denied: {decision['reason']}"
                    print(f"  [DENIED] {block.name}")
                elif decision["behavior"] == "ask":
                    if not registry.permissions.ask_user(block.name, tool_input):
                        output = f"Permission denied by user for {block.name}"
                        print(f"  [USER DENIED] {block.name}")
                    else:
                        output = execute_tool(block.name, tool_input, registry, block.id)
                else:
                    output = execute_tool(block.name, tool_input, registry, block.id)
            else:
                output = execute_tool(block.name, tool_input, registry, block.id)

            # PreToolUse hooks
            if registry.hooks:
                ctx = {"tool_name": block.name, "tool_input": tool_input}
                pre = registry.hooks.run_hooks("PreToolUse", ctx)
                for msg in pre.get("messages", []):
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                  "content": f"[Hook]: {msg}"})
                if pre.get("blocked"):
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                  "content": f"Blocked: {pre.get('block_reason', '')}"})
                    history.append({"role": "user", "content": results})
                    return

            print(f"> {block.name}: {str(output)[:200]}")

            # PostToolUse hooks
            if registry.hooks:
                ctx["tool_output"] = output
                post = registry.hooks.run_hooks("PostToolUse", ctx)
                for msg in post.get("messages", []):
                    output = f"{output}\n[Hook note]: {msg}"

            results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})

        history.append({"role": "user", "content": results})

        # Print assistant text
        final = extract_text(history[-1]["content"])
        if final:
            print(final)
