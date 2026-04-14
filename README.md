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
├── multiagent/              ← 多智能体基础设施
│   ├── message_bus.py       ← JSONL 收件箱通信总线
│   ├── worktree_manager.py  ← Git worktree 生命周期 + 任务绑定
│   └── mcp_client.py        ← MCP stdio 客户端 + 插件加载器
└── core/
    └── agent_loop.py         ← 统一 Agent 循环（所有能力整合）
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

## 更新记录

| Commit | 描述 |
|--------|------|
| `d61a9ff` | 重构 agent_loop：分离 ControlPlane 和 ToolRouter，消除散落的 if 链 |
| `edc08d4` | 删除 sessions/ 目录（教学演示文件不需要在主仓库） |
| `e59a05b` | 更新 README：移除 sessions 相关描述 |
| `e053785` | 移除 sessions/ 目录 |
| `a532294` | 初始提交：19个教学 session 集成的编程智能体 |

## 设计原则

1. **可组合** — 统一入口让你按需选择能力，无需全部加载
2. **无魔法** — 所有基础设施都是可见的纯 Python
3. **默认持久化** — 任务、记忆、调度、钩子配置都持久化到磁盘

## 架构设计

```
API 返回 tool_use
        ↓
ControlPlane.pre_tool()    ← 权限判断 + PreToolUse 钩子（统一入口）
        ↓
ToolRouter.dispatch()      ← 工具分发，零 if，靠注册表驱动
        ↓
ControlPlane.post_tool()   ← PostToolUse 钩子（统一入口）
```

**三层边界，各自单一职责：**

| 组件 | 职责 |
|------|------|
| `ControlPlane` | 权限检查（deny/ask/allow）+ Pre/Post 钩子拦截 |
| `ToolRouter` | 注册 → 分发，零 if 判断，靠 `router.dispatch(name, args, ctx)` 执行 |
| `EventSource` | cron / background / message_bus 视为外部事件，主循环只 drain 并注入 history |

**主循环 `AgentRunner.run()` 干净如上，仅含：**
- drain 外部事件
- 上下文压缩检查
- API 调用 + 错误恢复
- max_tokens 恢复
- 工具块处理（统一 pre → dispatch → post，无 if 侵入）
