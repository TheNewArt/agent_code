# Agent Code

一个功能完整的 AI 编程智能体，支持可组合的能力模块：技能系统、持久记忆、权限管理、钩子系统、上下文压缩、任务看板、Cron 调度、后台任务、多智能体协作、Git Worktree 和 MCP 插件。

## 项目结构

```
agent_code/
├── unified_agent.py          ← 主入口（所有能力可按需开启）
├── .env                      ← API 配置（API Key 和中转地址）
├── infra/
│   └── base.py              ← 公共基础：safe_path, bash安全, 读写编辑, 消息归一化
├── capabilities/            ← 9个可插拔能力模块
│   ├── background.py        ← 后台线程执行 + 通知队列
│   ├── compact.py           ← 上下文压缩 + 转录持久化
│   ├── hooks.py             ← PreToolUse / PostToolUse / SessionStart 钩子
│   ├── memory.py            ← 跨会话持久记忆
│   ├── permissions.py       ← 权限模式：default / plan / auto
│   ├── scheduler.py         ← Cron 定时调度
│   ├── skills.py            ← 技能注册表（从 skills/ 目录加载）
│   ├── tasks.py             ← 持久任务看板
│   └── todo.py              ← 会话级计划追踪
├── multiagent/             ← 多智能体基础设施
│   ├── message_bus.py       ← JSONL 收件箱通信总线
│   ├── worktree_manager.py ← Git worktree 生命周期 + 任务绑定
│   └── mcp_client.py       ← MCP stdio 客户端 + 插件加载器
└── core/
    └── agent_loop.py        ← 统一 Agent 循环（所有能力整合）
```

## 快速开始

```bash
cd agent_code

# 最小运行（仅 base loop）
python unified_agent.py

# 开启全部能力
python unified_agent.py --all

# 按需开启特定能力
python unified_agent.py --skills --memory --tasks --cron
```

## 环境变量

```bash
# .env 文件中配置
ANTHROPIC_API_KEY=your-api-key
ANTHROPIC_BASE_URL=https://your-proxy/v1   # 中转地址
MODEL_ID=claude-sonnet-4-20250514
AGENT_WORKDIR=/path/to/project
AGENT_REPO_ROOT=/path/to/repo   # git worktree 功能需要
```

## 能力参考

| 标志 | 功能 |
|------|------|
| `--skills` | 技能注册表，从 `skills/` 加载 SKILL.md |
| `--memory` | 跨会话持久记忆 |
| `--tasks` | 共享任务看板（CRUD） |
| `--cron` | 定时调度任务 |
| `--background` | 后台线程执行 |
| `--todo` | 会话级计划追踪 |
| `--hooks` | PreToolUse / PostToolUse / SessionStart 钩子 |
| `--permissions` | 权限模式：default / plan / auto |
| `--compact` | 自动上下文压缩 + 转录持久化 |
| `--worktrees` | Git worktree 管理（需 git 仓库） |
| `--multiagent` | 多智能体通信总线 |

## 设计原则

1. **可组合** — 统一入口让你按需选择能力，无需全部加载
2. **无魔法** — 所有基础设施都是可见的纯 Python
3. **默认持久化** — 任务、记忆、调度、钩子配置都持久化到磁盘
4. **教学导向** — 原始 19 个教学 session 文件在源码中清晰展示每个概念的演进
