"""
unified_agent.py — Unified Coding Agent
========================================

All 19 sessions merged into a single interactive agent with
fully composable capabilities.

Usage::

    # Minimal (just the base loop)
    python unified_agent.py

    # With all capabilities enabled
    python unified_agent.py --all

    # Select specific capabilities
    python unified_agent.py --skills --memory --tasks --cron

Capabilities (all opt-in):
  --skills        Skill registry (loads from skills/ directory)
  --memory        Persistent cross-session memory
  --tasks         Shared task board with persistence
  --cron          Cron-based scheduled tasks
  --background    Background thread execution
  --todo          Session plan / todo tracker
  --hooks         PreToolUse / PostToolUse hooks
  --permissions   Permission modes (default/plan/auto)
  --compact       Auto context compaction + transcript persistence
  --worktrees     Git worktree management (requires git repo)
  --multiagent    Multi-agent message bus

Environment variables::
  MODEL_ID             — Anthropic model name (default: claude-sonnet-4-20250514)
  ANTHROPIC_BASE_URL  — Optional custom API endpoint
  AGENT_WORKDIR       — Working directory (default: cwd)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=r"C:\Users\10621\Desktop\code_source\agent_code\.env", override=True)          # 加载 .env，KEY 和 BASE_URL 在此读取

# Ensure this package is importable
sys.path.insert(0, str(Path(__file__).parent))

from core.agent_loop import AgentRegistry, run_agent_loop
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
    "Always verify before assuming. Prefer reading files over guessing. "
    "Be resourceful: search for existing solutions before reinventing them."
)


def build_registry(args: argparse.Namespace) -> AgentRegistry:
    workdir = Path(os.getenv("AGENT_WORKDIR", Path.cwd()))
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
        worktrees=WorktreeManager(Path(os.getenv("AGENT_REPO_ROOT", workdir))) if args.worktrees else None,
        message_bus=MessageBus(workdir / ".team" / "inbox") if args.multiagent else None,
        workdir=workdir,
        skill_dir=workdir / "skills",
        memory_dir=workdir / ".memory",
        tasks_dir=workdir / ".tasks",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified Coding Agent")
    parser.add_argument("--system", default=DEFAULT_SYSTEM, help="System prompt")
    parser.add_argument("--skills", action="store_true", help="Enable skill registry")
    parser.add_argument("--memory", action="store_true", help="Enable persistent memory")
    parser.add_argument("--tasks", action="store_true", help="Enable shared task board")
    parser.add_argument("--cron", action="store_true", help="Enable cron scheduler")
    parser.add_argument("--background", action="store_true", help="Enable background tasks")
    parser.add_argument("--todo", action="store_true", help="Enable session plan tracker")
    parser.add_argument("--hooks", action="store_true", help="Enable hook system")
    parser.add_argument("--permissions", action="store_true", help="Enable permission manager")
    parser.add_argument("--compact", action="store_true", help="Enable auto context compaction")
    parser.add_argument("--worktrees", action="store_true", help="Enable git worktree management")
    parser.add_argument("--multiagent", action="store_true", help="Enable multi-agent message bus")
    parser.add_argument("--all", action="store_true", help="Enable all capabilities")
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

    # Start cron scheduler
    if registry.cron:
        registry.cron.start()

    # Load memory
    if registry.memory:
        registry.memory.load_all()

    print(f"[Agent] workdir={registry.workdir}")
    enabled = [k for k, v in vars(args).items()
               if v and k not in ("system", "permission_mode")]
    print(f"[Agent] capabilities enabled: {enabled or 'base loop only'}")

    try:
        run_agent_loop(args.system, registry)
    finally:
        if registry.cron:
            registry.cron.stop()


if __name__ == "__main__":
    main()
