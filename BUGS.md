# agent_code Bug Record

**Updated: 2026-04-15**

---

## Bug 1: `registry.cron.stop()` 位置错误

**文件**: `unified_agent.py`
**状态**: ✅ 已修复

### 问题描述

修改后的 `main()` 函数在内层 `while True` 循环末尾错误地放置了 `registry.cron.stop()`，导致：
1. 每处理一条工具结果就停一次 Cron，而不是在整个交互结束后才停止
2. 没有 `None` 检查，在未启用 cron 时会抛 `AttributeError`

### 修复内容

```python
# 修复前（错误）
        while True:
            response = runner._call_api(tools, history)
            if response is None:
                break
            ...
            history.append({"role": "user", "content": results})
            registry.cron.stop()  # ← 每轮都停，且没判 None

# 修复后（正确）
        while True:
            ...

    # 所有交互循环退出后，停止 cron
    if registry.cron:
        registry.cron.stop()
```

---

## Bug 2: API 调用失败时静默退出

**文件**: `unified_agent.py`
**状态**: ✅ 已修复

### 问题描述

`runner._call_api()` 返回 `None` 时，直接 `break` 出内层循环，回到外层等待 `input()`。若此时 stdin 已关闭（EOF），程序静默退出。用户看不到错误原因，表现为"对话完直接弹出"。

### 修复内容

```python
# 修复前（错误）
if response is None:
    break  # ← break 后回到外层等 input()，若 stdin 关闭则 EOFError

# 修复后（正确）
if response is None:
    print("[Error] API call failed. Retrying...")
    continue  # ← 留在内层循环，让模型重试

# 同时新增 max_tokens 恢复逻辑
if response.stop_reason == "max_tokens":
    history.append({"role": "user", "content": "Output limit hit. Continue directly from where you stopped."})
    continue
```

---

## Bug 3: `normalize_messages` 不支持 Pydantic 对象

**文件**: `infra/base.py`
**状态**: ✅ 已修复

### 问题描述

`normalize_messages` 使用 `isinstance(block, dict)` 来过滤 content 列表中的 block。但 `AgentRunner` 的 `response.content` 是 Pydantic 模型对象列表，不是 dict。因此 `isinstance(block, dict)` 返回 False，所有 Pydantic block 被静默丢弃。

第二次 `_call_api` 时，`history` 里包含的 `response.content`（Pydantic 对象列表）被 `normalize_messages` 过滤成空列表，导致 API 收到损坏的消息序列，返回 `stop_reason=None, content=None`。

### 修复内容

新增 `_to_dict()` 辅助函数，兼容 dict、Pydantic v2（`model_dump`）和 Pydantic v1（`as_dict`）：

```python
def _to_dict(obj):
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if not k.startswith("_")}
    if hasattr(obj, "model_dump"):          # Pydantic v2
        return {k: v for k, v in obj.model_dump().items() if not k.startswith("_")}
    if hasattr(obj, "as_dict"):             # Pydantic v1
        return {k: v for k, v in obj.as_dict().items() if not k.startswith("_")}
    return obj
```

同时修复 merge 逻辑：只有纯字符串内容才合并，包含 block 列表的消息不参与合并（防止 placeholder 消息被错误合并）。

---

## Bug 4: `normalize_messages` 多次调用导致消息重复

**文件**: `infra/base.py`
**状态**: ✅ 已修复

### 问题描述

`normalize_messages` 每次调用都会向传入的 `messages` 列表追加 placeholder tool_result 消息。在 `unified_agent.py` 的内层循环中，同一个 `history` 被多次 normalize，每次都追加新的 placeholder，导致 API 收到的消息序列中包含重复的 placeholder assistant 消息和 tool_result 消息，API 无法正确解析。

### 修复内容

修复方式包含在 Bug 3 的修复中：
1. Placeholder 消息不会被后续 merge 合并（block 消息不参与 merge）
2. `_call_api` 中对同一 history 只 normalize 一次，重试时复用已缓存的 normalized 结果

---

## Bug 5: `_call_api` 重试时 `norm_messages` 未传递

**文件**: `core/agent_loop.py`
**状态**: ✅ 已修复

### 问题描述

`_call_api` 的递归重试调用没有传递 `_norm_cache` 参数，导致重试时 `norm_messages` 未定义。

### 修复内容

使用默认参数 `_norm_cache=None` 模式，在函数入口处统一处理缓存逻辑。

---

## Bug 6: 权限 `always` 模式持久化缺失

**文件**: `capabilities/permissions.py`
**状态**: ⚠️ 待改进

---

## Bug 7: `compact_history` 中 `summarize_history` 失败会丢失上下文

**文件**: `capabilities/compact.py`
**状态**: ⚠️ 待改进

---

## 修复状态汇总

| Bug | 优先级 | 状态 |
|-----|--------|------|
| Bug 1: cron.stop 位置错误 | 高 | ✅ 已修复 |
| Bug 2: API 失败静默退出 | 高 | ✅ 已修复 |
| Bug 3: normalize 不支持 Pydantic | 高 | ✅ 已修复 |
| Bug 4: normalize 多次调用消息重复 | 高 | ✅ 已修复 |
| Bug 5: _call_api 重试 cache 未传递 | 中 | ✅ 已修复 |
| Bug 6: always 规则不持久化 | 低 | ⚠️ 待改进 |
| Bug 7: compact 失败丢上下文 | 低 | ⚠️ 待改进 |

**文件**: `capabilities/permissions.py`
**状态**: ⚠️ 待改进

### 问题描述

用户对 bash 命令回答 `always` 后，权限规则被保存在内存中，程序重启后失效。`always` 规则没有持久化到磁盘。

---

## Bug 4: `compact_history` 中 `summarize_history` 失败会丢失上下文

**文件**: `capabilities/compact.py`
**状态**: ⚠️ 待改进

### 问题描述

`summarize_history` 内部调用 API，如果 API 失败，`summarize_history` 返回错误信息，原始上下文全部丢失，没有回退机制。

---

## 修复状态汇总

| Bug | 优先级 | 状态 |
|-----|--------|------|
| Bug 1: cron.stop 位置错误 | 高 | ✅ 已修复 |
| Bug 2: API 失败静默退出 | 高 | ✅ 已修复 |
| Bug 3: always 规则不持久化 | 低 | ⚠️ 待改进 |
| Bug 4: compact 失败丢上下文 | 低 | ⚠️ 待改进 |
