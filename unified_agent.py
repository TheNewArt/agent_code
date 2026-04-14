"""
unified_agent.py — Unified Coding Agent
========================================

Usage::

    python unified_agent.py --all
    python unified_agent.py --skills --memory --tasks --cron

Capabilities (all opt-in via flags):
  --skills  --memory  --tasks  --cron  --background
  --todo  --hooks  --permissions  --compact  --worktrees  --multiagent
  --all    — enable all capabilities
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(dotenv_path=r"C:\Users\10621\Desktop\code_source\agent_code\.env", override=True)

from core.agent_loop import AgentRegistry, AgentRunner
from capabilities.skills import SkillRegistry
from capabilities.memory import MemoryManager
from capabilities.tasks import TaskManager
from capabilities.scheduler import CronScheduler
from capabilities.background import BackgroundManager
from capabilities.todo import TodoManager
from capabilities.hooks import HookManager
from capabilities.permissions import PermissionManager
from capabilities.compact import CompactState
from multiagent.worktree_manager import WorktreeManager
from multiagent.message_bus import MessageBus


DEFAULT_SYSTEM = (
    "You are a coding agent. Use tools to explore, read, write, and edit files. "
    "Always verify before assuming. Prefer reading files over guessing."
)


def build_registry(args: argparse.Namespace) -> AgentRegistry:
    workdir = Path.cwd()
    return AgentRegistry(
        skills=SkillRegistry(workdir / "skills") if args.skills else None,
        memory=MemoryManager(workdir / ".memory") if args.memory else None,
        tasks=TaskManager(workdir / ".tasks") if args.tasks else None,
        cron=CronScheduler(workdir / ".claude" / "scheduled_tasks.json") if args.cron else None,
        background=BackgroundManager(workdir / ".runtime-tasks") if args.background else None,
        todo=TodoManager() if args.todo else None,
        hooks=HookManager() if args.hooks else None,
        permissions=PermissionManager(mode=args.permission_mode) if args.permissions else None,
        compact=CompactState() if args.compact else None,
        worktrees=WorktreeManager(workdir) if args.worktrees else None,
        message_bus=MessageBus(workdir / ".team" / "inbox") if args.multiagent else None,
        workdir=workdir,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified Coding Agent")
    parser.add_argument("--system", default=DEFAULT_SYSTEM, help="System prompt")
    parser.add_argument("--skills",       action="store_true", help="Skill registry")
    parser.add_argument("--memory",       action="store_true", help="Persistent memory")
    parser.add_argument("--tasks",        action="store_true", help="Task board")
    parser.add_argument("--cron",         action="store_true", help="Cron scheduler")
    parser.add_argument("--background",   action="store_true", help="Background tasks")
    parser.add_argument("--todo",         action="store_true", help="Session plan tracker")
    parser.add_argument("--hooks",        action="store_true", help="Hook system")
    parser.add_argument("--permissions",  action="store_true", help="Permission manager")
    parser.add_argument("--compact",      action="store_true", help="Auto context compaction")
    parser.add_argument("--worktrees",    action="store_true", help="Git worktree management")
    parser.add_argument("--multiagent",   action="store_true", help="Multi-agent message bus")
    parser.add_argument("--all",          action="store_true", help="Enable all capabilities")
    parser.add_argument(
        "--permission-mode",
        choices=("default", "plan", "auto"),
        default="default",
        help="Permission mode (requires --permissions)"
    )
    args = parser.parse_args()

    if args.all:
        for attr in ["skills", "memory", "tasks", "cron", "background",
                     "todo", "hooks", "permissions", "compact", "worktrees", "multiagent"]:
            setattr(args, attr, True)

    registry = build_registry(args)

    # 启动 cron 和加载记忆
    if registry.cron:
        registry.cron.start()
    if registry.memory:
        registry.memory.load_all()

    print("[Agent] workdir=%s" % registry.workdir)
    enabled = [k for k, v in vars(args).items()
                if v and k not in ("system", "permission_mode")]
    print("[Agent] capabilities: %s" % (enabled or ["base loop only"]))

    # AgentRunner 管理 session 基础设施（路由、控制面、事件源）
    runner = AgentRunner(args.system, registry)

    # 交互循环
    history = []
    while True:
        try:
            query = input("\n>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not query:
            continue
        if query.lower() in ("q", "exit", "quit"):
            print("Bye.")
            break

        history.append({"role": "user", "content": query})

        # 单轮：构建工具列表 -> API 调用 -> 处理结果
        tools = runner.router.tools_for_llm()

        # drain 事件
        for src in runner._sources:
            for msg in src.drain():
                history.append(msg)

        # API 调用
        response = runner._call_api(tools, history)
        if response is None:
            print("[Error] API call failed.")
            break

        history.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            from infra.base import extract_text
            text = extract_text(history[-1]["content"])
            if text:
                print(text)
            break

        # 处理工具调用
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_input = dict(block.input or {})

            # 控制面 pre
            pre = runner.plane.pre_tool(block.name, tool_input)
            for msg in pre.injected_messages:
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": msg})

            if pre.blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": pre.output or ""})
                history.append({"role": "user", "content": results})
                print("[Blocked] %s" % pre.output)
                break

            if pre.output:
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": pre.output})
                continue

            # 分发
            output = runner.router.dispatch(block.name, tool_input, runner._ctx())
            print("> %s: %s" % (block.name, str(output)[:200]))

            # 控制面 post
            output = runner.plane.post_tool(block.name, tool_input, output)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})

        history.append({"role": "user", "content": results})

    if registry.cron:
        registry.cron.stop()


if __name__ == "__main__":
    main()
