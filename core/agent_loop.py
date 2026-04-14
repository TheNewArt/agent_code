# Core: Unified Agent Loop
# ========================
# 架构原则：
#   主循环只做三件事：API调用 -> 处理工具调用 -> 处理最终文本
#   所有能力通过注册表接入，主循环不知道具体是谁
#   控制面（权限/钩子）作为中间件在工具执行前后拦截
#
# 边界定义：
#   1. ControlPlane   — pre/post 拦截点，权限判断，钩子触发
#   2. ToolRouter     — 分发工具，零 if，靠注册表驱动
#   3. EventSources   — cron / background / message_bus 视为外部事件，主循环只 drain 并注入 history

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
load_dotenv(dotenv_path=DOTENV, override=True)

from anthropic import Anthropic, APIError
from infra.base import extract_text, normalize_messages, read_file, run_bash, write_file, edit_file


# ---------------------------------------------------------------------------
# 1. 基础工具（固定不变，不走 if 分发）
# ---------------------------------------------------------------------------
BASE_TOOLS = [
    {"name": "bash",       "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file",  "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to a file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file",  "description": "Replace exact text in a file once.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
]

def _base_read(args: dict, ctx: dict) -> str:
    from capabilities.compact import track_recent_file, persist_large_output
    path = args["path"]
    if ctx.get("compact"):
        track_recent_file(ctx["compact"], path)
    content = read_file(path, ctx["workdir"], args.get("limit"))
    if ctx.get("compact") and len(content) > 30000:
        tag = "read_%d" % (hash(path) % 100000)
        return persist_large_output(tag, content)
    return content

BASE_HANDLERS = {
    "bash":       lambda a, c: run_bash(a["command"], c["workdir"]),
    "read_file":  _base_read,
    "write_file": lambda a, c: write_file(a["path"], a["content"], c["workdir"]),
    "edit_file":  lambda a, c: edit_file(a["path"], a["old_text"], a["new_text"], c["workdir"]),
}


# ---------------------------------------------------------------------------
# 2. 工具路由器 — 零 if，靠注册表分发
# ---------------------------------------------------------------------------
class ToolRouter:
    def __init__(self):
        self._handlers = {}
        self._schemas  = {}

    def register(self, name: str, handler: callable, schema: dict = None) -> None:
        self._handlers[name] = handler
        if schema:
            self._schemas[name] = schema

    def dispatch(self, name: str, args: dict, ctx: dict) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            return "Unknown tool: %s" % name
        try:
            return handler(args, ctx)
        except Exception as e:
            return "Tool error: %s" % e

    def tools_for_llm(self) -> list:
        return list(self._schemas.values()) if self._schemas else list(BASE_TOOLS)


# ---------------------------------------------------------------------------
# 3. 控制面 — pre / post 拦截点
# ---------------------------------------------------------------------------
class ControlPlane:
    def __init__(self, router: ToolRouter):
        self.router = router
        self._perm = None
        self._hooks = None

    def set_permissions(self, mgr) -> None:
        self._perm = mgr

    def set_hooks(self, mgr) -> None:
        self._hooks = mgr

    def pre_tool(self, name: str, args: dict):
        injected, blocked_reason = [], ""

        if self._perm:
            decision = self._perm.check(name, args)
            if decision["behavior"] == "deny":
                return PreResult(False, True, "Permission denied: %s" % decision["reason"], [])
            if decision["behavior"] == "ask" and not self._perm.ask_user(name, args):
                return PreResult(False, True, "Permission denied by user for %s" % name, [])

        if self._hooks:
            ctx = {"tool_name": name, "tool_input": args}
            result = self._hooks.run_hooks("PreToolUse", ctx)
            for msg in result.get("messages", []):
                injected.append("[Hook]: %s" % msg)
            if result.get("blocked"):
                blocked_reason = result.get("block_reason", "blocked by hook")

        if blocked_reason:
            return PreResult(True, True, "Blocked: %s" % blocked_reason, injected)

        return PreResult(True, False, None, injected)

    def post_tool(self, name: str, args: dict, output: str) -> str:
        if not self._hooks:
            return output
        ctx = {"tool_name": name, "tool_input": args, "tool_output": output}
        result = self._hooks.run_hooks("PostToolUse", ctx)
        for msg in result.get("messages", []):
            output = "%s\n[Hook note]: %s" % (output, msg)
        return output


@dataclass
class PreResult:
    has_permission: bool
    blocked: bool
    output: Optional[str]
    injected_messages: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# 4. 事件源接口
# ---------------------------------------------------------------------------
class EventSource:
    def drain(self) -> list: return []


class CronSource(EventSource):
    def __init__(self, scheduler): self.scheduler = scheduler
    def drain(self) -> list:
        return [{"role": "user", "content": n} for n in self.scheduler.drain_notifications()]


class BackgroundSource(EventSource):
    def __init__(self, mgr): self.mgr = mgr
    def drain(self) -> list:
        return [{"role": "user", "content": "[bg:%s] %s: %s" % (n["task_id"], n["status"], n["preview"])}
                for n in self.mgr.drain_notifications()]


class InboxSource(EventSource):
    def __init__(self, bus, agent_name: str = "lead"):
        self.bus = bus; self.agent_name = agent_name
    def drain(self) -> list:
        return [{"role": "user", "content": "<inbox>%s</inbox>" % json.dumps(m)}
                for m in self.bus.read_inbox(self.agent_name)]

# ---------------------------------------------------------------------------
# 5. AgentRegistry
# ---------------------------------------------------------------------------
@dataclass
class AgentRegistry:
    skills:      Optional[Any] = None
    memory:      Optional[Any] = None
    tasks:       Optional[Any] = None
    cron:        Optional[Any] = None
    background:  Optional[Any] = None
    todo:        Optional[Any] = None
    hooks:       Optional[Any] = None
    permissions: Optional[Any] = None
    compact:     Optional[Any] = None
    worktrees:   Optional[Any] = None
    message_bus: Optional[Any] = None
    workdir:     Path = field(default_factory=Path.cwd)


# ---------------------------------------------------------------------------
# 6. AgentRunner
# ---------------------------------------------------------------------------
class AgentRunner:
    def __init__(self, system_prompt: str, registry: AgentRegistry, max_tokens: int = 8000):
        self.system_prompt = system_prompt
        self.registry = registry
        self.max_tokens = max_tokens
        self.model = os.getenv("MODEL_ID", "claude-sonnet-4-20250514")
        self.base_url = os.getenv("ANTHROPIC_BASE_URL", "")
        self._client = Anthropic(base_url=self.base_url) if self.base_url else Anthropic()
        self._compact_state = registry.compact

        self.router = ToolRouter()
        self._register_base_tools()
        self._register_capability_tools()

        self.plane = ControlPlane(self.router)
        if registry.permissions: self.plane.set_permissions(registry.permissions)
        if registry.hooks:       self.plane.set_hooks(registry.hooks)

        self._sources = []
        if registry.cron:        self._sources.append(CronSource(registry.cron))
        if registry.background:  self._sources.append(BackgroundSource(registry.background))
        if registry.message_bus: self._sources.append(InboxSource(registry.message_bus))

        if registry.cron:   registry.cron.start()
        if registry.memory: registry.memory.load_all()

    def _register_base_tools(self) -> None:
        for t in BASE_TOOLS:
            self.router.register(t["name"], BASE_HANDLERS[t["name"]], schema=t)

    def _register_capability_tools(self) -> None:
        r, reg = self.router, self.registry

        if reg.skills:
            r.register("load_skill",  lambda a, _: reg.skills.load_full_text(a["name"]),
                        {"name": "load_skill", "description": "Load skill body.",
                         "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}})
            r.register("skills_list", lambda a, _: reg.skills.describe_available(),
                        {"name": "skills_list", "description": "List skills.",
                         "input_schema": {"type": "object", "properties": {}}}
)

        if reg.memory:
            r.register("save_memory", lambda a, _: reg.memory.save_memory(a["name"], a["description"], a["type"], a["content"]),
                        {"name": "save_memory", "description": "Save a memory.",
                         "input_schema": {"type": "object", "properties": {
                             "name": {"type": "string"}, "description": {"type": "string"},
                             "type": {"type": "string", "enum": ["user", "feedback", "project", "reference"]},
                             "content": {"type": "string"}}, "required": ["name", "description", "type", "content"]}})

        if reg.tasks:
            r.register("task_create", lambda a, _: reg.tasks.create(a["subject"], a.get("description", "")),
                        {"name": "task_create", "description": "Create task.",
                         "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}}, "required": ["subject"]}})
            r.register("task_update", lambda a, _: reg.tasks.update(a["task_id"], a.get("status"), a.get("owner")),
                        {"name": "task_update", "description": "Update task.",
                         "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "deleted"]}, "owner": {"type": "string"}}, "required": ["task_id"]}})
            r.register("task_list",   lambda a, _: reg.tasks.list_all(),
                        {"name": "task_list", "description": "List tasks.",
                         "input_schema": {"type": "object", "properties": {}}})
            r.register("task_get",    lambda a, _: reg.tasks.get(a["task_id"]),
                        {"name": "task_get", "description": "Get task.",
                         "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}})

        if reg.cron:
            def cron_create(a, _): return reg.cron.create(a["cron"], a["prompt"], a.get("recurring", True), a.get("durable", False))
            r.register("cron_create", cron_create,
                        {"name": "cron_create", "description": "Schedule task.",
                         "input_schema": {"type": "object", "properties": {"cron": {"type": "string"}, "prompt": {"type": "string"}, "recurring": {"type": "boolean"}, "durable": {"type": "boolean"}}, "required": ["cron", "prompt"]}})
            r.register("cron_delete", lambda a, _: reg.cron.delete(a["id"]),
                        {"name": "cron_delete", "description": "Delete cron.",
                         "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}})
            r.register("cron_list",   lambda a, _: reg.cron.list_tasks(),
                        {"name": "cron_list", "description": "List crons.",
                         "input_schema": {"type": "object", "properties": {}}})

        if reg.background:
            r.register("background_run",   lambda a, _: reg.background.run(a["command"]),
                        {"name": "background_run", "description": "Run in background.",
                         "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}})
            r.register("check_background", lambda a, _: reg.background.check(a.get("task_id")),
                        {"name": "check_background", "description": "Check background task.",
                         "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}}})

        if reg.todo:
            r.register("plan_update", lambda a, _: reg.todo.update(a["items"]),
                        {"name": "plan_update", "description": "Update plan.",
                         "input_schema": {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}}
)

    def _ctx(self) -> dict:
        return {"workdir": self.registry.workdir, "compact": self._compact_state}

    def _build_system(self) -> str:
        parts = [self.system_prompt]
        if self.registry.skills:
            parts.append("\nAvailable skills:\n" + self.registry.skills.describe_available())
        if self.registry.memory:
            ms = self.registry.memory.load_memory_prompt()
            if ms: parts.append("\n" + ms)
        return "\n\n".join(parts)

    def _compact_history(self, history: list) -> list:
        from capabilities.compact import compact_history
        return compact_history(self._client, self.model, history, self._compact_state)

    def _call_api(self, tools: list, history: list, attempt: int = 0):
        backoff = min(1.0 * (2 ** attempt), 30.0) + random.uniform(0, 1)
        try:
            return self._client.messages.create(
                model=self.model,
                system=self._build_system(),
                messages=normalize_messages(history),
                tools=tools,
                max_tokens=self.max_tokens,
            )
        except APIError as e:
            err = str(e).lower()
            if "overlong" in err or ("prompt" in err and "long" in err):
                if attempt < 2:
                    print("[Recovery] Prompt too long, compacting...")
                    history[:] = self._compact_history(history)
                    return self._call_api(tools, history, attempt + 1)
            if attempt < 3:
                print("[Recovery] API error: %s. Retrying in %.1fs..." % (e, backoff))
                time.sleep(backoff)
                return self._call_api(tools, history, attempt + 1)
            print("[Error] API failed: %s" % e)
            return None
        except (ConnectionError, TimeoutError, OSError) as e:
            if attempt < 3:
                print("[Recovery] Connection error: %s. Retrying in %.1fs..." % (e, backoff))
                time.sleep(backoff)
                return self._call_api(tools, history, attempt + 1)
            print("[Error] Connection failed: %s" % e)
            return None

    def run(self) -> None:
        tools = self.router.tools_for_llm()
        history = []
        max_tokens_recovery = 0

        while True:
            # 1. drain 外部事件
            for src in self._sources:
                for msg in src.drain():
                    history.append(msg)

            # 2. 上下文超限则压缩
            if self._compact_state:
                from capabilities.compact import estimate_context_size
                if estimate_context_size(history) > 50000:
                    print("[auto compact]")
                    history[:] = self._compact_history(history)

            # 3. SessionStart 钩子
            if self.registry.hooks:
                self.registry.hooks.run_hooks("SessionStart", {})

            # 4. API 调用
            response = self._call_api(tools, history)
            if response is None:
                return

            history.append({"role": "assistant", "content": response.content})

            # 5. max_tokens 恢复
            if response.stop_reason == "max_tokens":
                max_tokens_recovery += 1
                if max_tokens_recovery <= 3:
                    history.append({"role": "user", "content": "Output limit hit. Continue directly from where you stopped."})
                    continue
                print("[Error] max_tokens recovery exhausted.")
                return
            max_tokens_recovery = 0

            # 6. 非工具调用 -> 打印文本，结束
            if response.stop_reason != "tool_use":
                text = extract_text(history[-1]["content"])
                if text:
                    print(text)
                return

            # 7. 处理工具调用 (pre -> dispatch -> post)
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_input = dict(block.input or {})

                # 控制面 pre
                pre = self.plane.pre_tool(block.name, tool_input)
                for msg in pre.injected_messages:
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": msg})

                if pre.blocked:
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": pre.output or ""})
                    history.append({"role": "user", "content": results})
                    return

                if pre.output:
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": pre.output})
                    continue

                # 分发
                output = self.router.dispatch(block.name, tool_input, self._ctx())
                print("> %s: %s" % (block.name, str(output)[:200]))

                # 控制面 post
                output = self.plane.post_tool(block.name, tool_input, output)

                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})

            history.append({"role": "user", "content": results})

            # 打印 assistant 文本
            text = extract_text(history[-1]["content"])
            if text:
                print(text)
