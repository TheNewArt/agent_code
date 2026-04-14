# Agent Code — 19-Session Teaching Project

An integrated coding agent built from 19 progressive teaching sessions, covering everything from a minimal agent loop to multi-agent teams with git worktrees and MCP plugin support.

## Project Structure

```
agent_code/
├── unified_agent.py          ← Main entry point (all capabilities composable)
├── README.md
├── infra/
│   └── base.py              ← safe_path, run_bash, read/write/edit, normalize_messages
├── capabilities/
│   ├── background.py        ← Background thread execution + notification queue
│   ├── compact.py           ← Context compaction + transcript persistence
│   ├── hooks.py             ← PreToolUse / PostToolUse / SessionStart hooks
│   ├── memory.py            ← Persistent cross-session memory (frontmatter .md files)
│   ├── permissions.py       ← Permission modes: default / plan / auto
│   ├── scheduler.py         ← Cron-based background task scheduler
│   ├── skills.py            ← Skill registry (loads from skills/ directory)
│   ├── tasks.py             ← Persistent shared task board (CRUD)
│   └── todo.py              ← Session-level plan tracker
├── multiagent/
│   ├── message_bus.py       ← JSONL inbox per agent (all comms go here)
│   ├── worktree_manager.py  ← Git worktree lifecycle + task binding + event log
│   └── mcp_client.py        ← MCP stdio client + PluginLoader + MCToolRouter
├── core/
│   └── agent_loop.py        ← Unified agent loop (all capabilities integrated)
└── sessions/
    ├── s01.py  ← Minimal agent loop (bash only)
    ├── s02.py  ← Base tools: bash, read, write, edit + message normalization
    ├── s03.py  ← Todo / plan manager (session-level)
    ├── s04.py  ← Subagent / task delegation (background threads)
    ├── s05.py  ← Skills system (SKILL.md registry)
    ├── s06.py  ← Context compaction + large output persistence
    ├── s07.py  ← Permission modes (default / plan / auto)
    ├── s08.py  ← Hook system (PreToolUse, PostToolUse, SessionStart)
    ├── s09.py  ← Memory manager (persistent across sessions)
    ├── s10.py  ← System prompt builder (dynamic assembly)
    ├── s11.py  ← Error recovery (max_tokens, prompt_too_long, backoff)
    ├── s12.py  ← Task manager (persistent task board)
    ├── s13.py  ← Background manager (threaded tasks + notification queue)
    ├── s14.py  ← Cron scheduler (background scheduled tasks)
    ├── s15.py  ← Multi-agent: message bus + team spawning
    ├── s16.py  ← + Shutdown protocol + plan approval
    ├── s17.py  ← + Autonomous teammates (idle/polling + task claiming)
    ├── s18.py  ← + Git worktree management + task binding
    └── s19.py  ← + MCP client + plugin loader + permission gate
```

## Quick Start

```bash
# Minimal (just the base loop)
python unified_agent.py

# Full capabilities
python unified_agent.py --all

# Specific capabilities
python unified_agent.py --skills --memory --tasks --cron

# Run a single session
python sessions/s03.py
```

## Environment Variables

```bash
MODEL_ID=claude-sonnet-4-20250514
ANTHROPIC_BASE_URL=https://api.example.com/v1  # optional custom endpoint
AGENT_WORKDIR=/path/to/project
AGENT_REPO_ROOT=/path/to/repo  # for git worktree features
```

## Capability Reference

| Flag | What it adds |
|------|-------------|
| `--skills` | `load_skill` + `skills_list` — load skill definitions from `skills/` |
| `--memory` | `save_memory` — persistent cross-session memories |
| `--tasks` | `task_create/update/list/get` — shared task board |
| `--cron` | `cron_create/delete/list` — scheduled background tasks |
| `--background` | `background_run/check_background` — non-blocking threads |
| `--todo` | `plan_update` — session-level plan tracker |
| `--hooks` | `PreToolUse/PostToolUse/SessionStart` — hook system |
| `--permissions` | Permission modes: default / plan / auto |
| `--compact` | Auto context compaction + transcript persistence |
| `--worktrees` | Git worktree create/run/keep/remove + task binding |
| `--multiagent` | Message bus for multi-agent communication |

## Sessions Summary

Each `sNN.py` is a standalone, runnable agent demonstrating one lesson.
They build progressively: later sessions import concepts from earlier ones.

- **s01–s02**: Core loop + base tools
- **s03–s04**: Plan tracking + subagent delegation
- **s05–s07**: Skills, compaction, permissions
- **s08–s10**: Hooks, memory, prompt assembly
- **s11–s14**: Error recovery, task board, background, cron
- **s15–s17**: Multi-agent: message bus, protocols, autonomous teammates
- **s18–s19**: Git worktrees, MCP plugins

## Design Principles

1. **Teaching-first** — Each session isolates one concept clearly
2. **Composable** — The unified agent lets you pick exactly which capabilities you need
3. **No magic** — All infrastructure is visible and editable plain Python
4. **Persistence by default** — State survives sessions (tasks, memory, cron, hooks configs)
