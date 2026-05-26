# Subagent Teammate Tools 修复

## 问题描述

子agent（通过 `create_agent` 创建）无法使用团队协作工具（`send_teammate_message`、`list_teammates`、`read_teammate_inbox`），导致子agent之间无法通信。

## 根本原因

`SubagentManager._run_subagent()` 方法在注册工具时，没有包含团队协作工具。这些工具只在主agent（orchestrator）和 teammate 中可用。

## 解决方案

### 1. 修改 `secbot/agent/subagent.py`

#### 1.1 添加 `TeammateManager` 类型导入
```python
if TYPE_CHECKING:
    from secbot.agent.teammate import TeammateManager
    from secbot.agents.registry import AgentRegistry, ExpertAgentSpec
```

#### 1.2 在 `SubagentManager.__init__` 中添加参数
```python
def __init__(
    self,
    # ... 其他参数 ...
    teammate_manager: "TeammateManager | None" = None,
):
    # ... 其他初始化 ...
    self.teammate_manager: "TeammateManager | None" = teammate_manager
```

#### 1.3 在 `_run_subagent` 中注册团队协作工具
```python
tools.register(CurlTool())
# Register teammate communication tools if a TeammateManager is available
if self.teammate_manager is not None:
    from secbot.agent.tools.teammate import (
        ListTeammatesTool,
        ReadTeammateInboxTool,
        SendTeammateMessageTool,
    )
    tools.register(ListTeammatesTool(self.teammate_manager))
    tools.register(SendTeammateMessageTool(self.teammate_manager, sender=label))
    tools.register(
        ReadTeammateInboxTool(
            self.teammate_manager,
            default_name=label,
            allow_name_override=False,
        )
    )
```

### 2. 修改 `secbot/agent/loop.py`

在 `AgentLoop.__init__` 中，创建 `teammates` 后，将其连接到 `subagents`：

```python
self.subagents = SubagentManager(
    # ... 参数 ...
)
self.teammates = TeammateManager(
    # ... 参数 ...
)
# Wire teammate_manager into subagents after both are created
self.subagents.teammate_manager = self.teammates
```

## 效果

修复后，通过 `create_agent` 创建的子agent将拥有以下工具：

1. **send_teammate_message** - 向其他 teammate 发送消息
2. **list_teammates** - 列出所有持久化的 teammate
3. **read_teammate_inbox** - 读取自己的收件箱

## 使用示例

### 子agent发送消息给 orchestrator

```python
# 在子agent中
await send_teammate_message(
    to="orchestrator",
    content="HTTP探测完成，发现开放端口80",
    msg_type="response"
)
```

### 子agent读取收件箱

```python
# 在子agent中
messages = await read_teammate_inbox()
# 处理消息
```

### Orchestrator 发送消息给子agent

注意：子agent通过 `create_agent` 创建，不是持久化的 teammate，所以 orchestrator 不能直接通过 `send_teammate_message` 发送消息给它。

如果需要双向通信，应该使用 `spawn_teammate` 而不是 `create_agent`。

## 架构说明

### Subagent vs Teammate

- **Subagent** (`create_agent`): 一次性后台任务，任务完成后自动销毁
- **Teammate** (`spawn_teammate`): 持久化的协作agent，有独立的收件箱，可以接收多次任务

### 工具可用性矩阵

| 工具 | Orchestrator | Teammate | Subagent (修复前) | Subagent (修复后) |
|------|--------------|----------|-------------------|-------------------|
| send_teammate_message | ✅ | ✅ | ❌ | ✅ |
| list_teammates | ✅ | ✅ | ❌ | ✅ |
| read_teammate_inbox | ✅ | ✅ | ❌ | ✅ |
| spawn_teammate | ✅ | ❌ | ❌ | ❌ |
| create_agent | ✅ | ❌ | ❌ | ❌ |
| blackboard_write | ✅ | ✅ | ✅ | ✅ |
| blackboard_read | ✅ | ✅ | ✅ | ✅ |
| exec | ✅ | ✅ | 条件性 | 条件性 |

## 注意事项

1. **Subagent 不是 Teammate**：虽然 subagent 现在可以发送消息给 teammate，但它本身不是一个持久化的 teammate，所以其他 agent 不能通过 `send_teammate_message` 直接回复它。

2. **单向通信**：Subagent → Teammate 是可行的，但 Teammate → Subagent 需要通过其他机制（如 blackboard）。

3. **生命周期**：Subagent 完成任务后会自动销毁，其收件箱也会消失。

## 测试建议

```python
# 测试子agent可以发送消息
async def test_subagent_can_send_message():
    # 1. 创建一个 teammate
    await spawn_teammate(name="receiver", role="test", task="wait")
    
    # 2. 创建一个 subagent，让它发送消息
    await create_agent(
        agent="httpx-check",
        task="Send a test message to teammate 'receiver' using send_teammate_message"
    )
    
    # 3. 验证 receiver 收到消息
    messages = await read_teammate_inbox(name="receiver")
    assert len(messages) > 0
```

## 相关文件

- `secbot/agent/subagent.py` - Subagent 管理器
- `secbot/agent/loop.py` - 主agent循环
- `secbot/agent/tools/teammate.py` - 团队协作工具定义
- `secbot/agent/teammate.py` - Teammate 管理器
