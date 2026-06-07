请基于nanobot，构建一个“网络安全智能体”，是一个基于大模型的对话式多智能体协作系统。主控智能体负责理解用户意图、拆解任务，然后动态编排一系列高度解耦的专家智能体，每个专家智能体封装了特定的提示词与工具能力。下面是设计方案。

---

一、总体架构

整个系统分为四层：

1. 对话交互层
      提供聊天界面，接收用户指令，展示执行过程和结果。

2. 调度编排层（主智能体 Orchestrator）
   · 解析用户意图
   · 匹配系统中已注册的专家智能体能力
   · 动态生成执行计划（DAG）
   · 按序调度专家智能体，并传递上下文数据
   · 汇总结果并回复用户

3. 专家智能体层（Agent Pool）
   每个专家智能体由“提示词 + 工具集 + 输入输出规范”组成，相互独立。例如：
   · 资产探测智能体
   · 端口扫描智能体
   · 漏洞扫描智能体
   · 弱口令检测智能体
   · 渗透测试智能体

   · 报告生成智能体

4. 工具/执行层
      实际执行安全操作的原子能力，如调用 nmap、qscan、fscan、nuclei、hydra等。每个专家智能体可以自主调用一个或多个工具。

---

二、关键设计：能力注册与动态编排

1. 专家智能体注册表

每个智能体在系统启动时注册，包含：

```json
{
  "name": "asset_discovery",
  "display_name": "资产探测智能体",
  "description": "对指定网段进行存活主机探测，输出IP列表和基础信息",
  "capabilities": ["存活扫描", "网段探测", "资产发现"],
  "input_hints": {"type": "object", "properties": {"target": {"type": "string", "description": "目标网段，如192.168.1.0/24"}}},
  "endpoint_bound": false
}
```

这些描述会注入主智能体的系统提示中，让它"知道"自己有哪些兵可用。

> **架构演进说明（2026-05）**：早期设计中每个专家智能体注册为独立的 function tool（如 `asset_discovery(target)`、`port_scan(ips)`），现已统一收敛为 **`create_agent(name, task, target)` 单一入口**。orchestrator 不再通过结构化参数调用各专家，而是自行编写完整的任务指令文本（`task`），由框架按 `name` 路由到对应专家智能体。详见 `.trellis/tasks/05-18-subagent-prompt-minimal-create-agent/prd.md`。

2. 主智能体（Orchestrator）提示词设计

主智能体本身是一个 LLM Agent，它不直接执行安全操作，而是通过唯一的 `create_agent` 工具调度专家智能体。工具 schema：

```json
{
  "type": "function",
  "function": {
    "name": "create_agent",
    "description": "创建并调度一个专家智能体执行指定任务",
    "parameters": {
      "type": "object",
      "properties": {
        "name": {"type": "string", "description": "专家智能体名称（必须在注册表中）"},
        "task": {"type": "string", "description": "orchestrator 编写的完整任务指令（含目标、已知信息、动作要求）"},
        "target": {"type": "string", "description": "路由/审计用目标标识"}
      },
      "required": ["name", "task", "target"]
    }
  }
}
```

当用户输入 "扫描192.168.1.0/24网段的高危漏洞" 时，主智能体依次调用：

```
create_agent(name="asset_discovery", task="对 192.168.1.0/24 执行存活探测，返回 JSON 格式 IP 列表", target="192.168.1.0/24")
→ 获取 IP 列表后
create_agent(name="port_scan", task="对以下 IP 执行常用端口扫描：192.168.1.1, 192.168.1.100。返回开放端口及服务指纹", target="192.168.1.0/24")
→ 获取端口/服务后
create_agent(name="vuln_scan", task="基于以下服务信息进行高危漏洞扫描：...", target="192.168.1.0/24")
```

这种设计让 orchestrator 拥有对任务指令的完全控制权，不再受限于各专家预定义的 input_schema，同时由注册表提供能力发现与路由校验。

---

三、专家智能体的实现方式

每个专家智能体可以采用 ReAct (Reason+Act) 模式，内部封装：

· 特定系统提示（例如“你是一个资产探测专家...”）
· 一个或多个工具函数（用 Function Calling 绑定）
· 输出解析器，保证下游能拿到结构化数据

以“资产探测智能体”为例：

```
系统提示：
你是一个资产探测专家。根据用户提供的目标网段，调用 nmap 工具执行 ping 扫描，并整理返回存活 IP 列表。只输出 JSON 结果，不要额外解释。

可用工具：
- nmap_ping_scan(target): 执行 ping 扫描，返回原始结果。
```

当主调度器将 {"target": "192.168.1.0/24"} 传入后，该智能体会调用工具，解析结果，最终输出 {"ips": ["192.168.1.1", "192.168.1.100"]}，交由调度器传递给下一步。

端口扫描智能体则可能接收 ips 列表，调用全连接或半开扫描，输出开放端口及服务指纹。

漏洞扫描智能体根据端口和服务，查询漏洞库（如 CVE 匹配、调用 nuclei 等），最终给出高危漏洞列表。

这种子智能体也可以由更小的智能体组合而成，但当前方案保持“平铺式”专家池，易于管理。

---

四、工作流引擎（调度执行器）

编排器通过 `create_agent(name, task, target)` 统一入口调度专家智能体，利用 LLM 的 function calling 机制实现动态路由：用户输入被送入编排器，编排器通过分析意图，自行编写任务指令并通过 `create_agent` 调度对应专家。每次调用子智能体后，将结果带回对话上下文，继续决策下一步。每个"智能体"就是一个带提示词和工具的独立模块，配置内容包括：它的注册元数据（能力关键词、描述）、系统提示词、绑定的工具集。

数据流是自然接力：编排器从上一步结果中提取关键信息，写入下一步的 `task` 指令文本中，无需结构化变量引用。

---

五、对话界面的交互增强

· 意图澄清：如果用户只说“帮我扫描漏洞”，主智能体可反问“请指定目标网段或资产”。
· 多轮对话：对话历史可保留上下文，如用户先说“探测 10.0.0.0/24”，然后说“对刚才发现的资产扫高危漏洞”，调度器应能自动关联前一步结果。
· 人工确认：高危操作前可要求用户确认。
· 结果展示：除了文本，还可包含表格、拓扑图等富文本。可以一键导出扫描报告。

---

六、技术选型参考

· 框架：
  ·nanobot

· LLM：任意支持 function calling 的模型，如 GPT-4、Claude、开源模型等。
· 工具实现：显示支持用 Python  subprocess 调用nmap、qscan、fscan、nuclei、hydra，并注册为 LLM 的工具。
· 后端：FastAPI 提供 REST接口。

·前端：要有科技感，强调AI原生体验 (交互与思考过程)，以 **React/Vue** 为基础，使用 **Tailwind CSS** 进行高效样式开发，集成 **@prompt-or-die/tech-ui** 或 **Nikhil AI Kit** 的AI专用组件，并使用 **assistant-ui** 快速搭建专业的对话功能。

---

七、示例：新增一个“弱口令检测智能体”

仅需三步：

1. 编写一个智能体配置（YAML），定义提示词、能力描述，绑定 hydra 或自写爆破工具。
2. 在注册表中加入此智能体的元数据（含 `capabilities` 关键词），并声明 `endpoint_bound` 属性。
3. 启动系统。当用户说"扫描完漏洞后顺带检查一下弱口令"，主智能体就会通过 `create_agent` 自动插入这一步，在 `task` 中引用端口扫描的结果（获取开了 22/3306 等服务的主机列表），非常解耦。

---

八、安全与合规提醒

· 所有扫描操作应当仅在获得授权网络上进行。
· 系统需要鉴权，记录操作日志。
· 子智能体调用工具时应限制权限，防止命令注入。



轻量实现设计

1. 子智能体配置化（以资产探测为例）

```yaml
# agents/asset_discovery.yaml
name: asset_discovery
display_name: 资产探测智能体
description: 对指定网段进行 ping 扫描，返回存活主机列表
capabilities: ["存活扫描", "网段探测", "资产发现"]
endpoint_bound: false
input_hints:  # 仅作参考文档，不再用于 LLM 工具入参 schema
  target: string  # 如 192.168.1.0/24
system_prompt: |
  你是一个资产探测专家。请根据输入的 target 网段，使用 nmap_ping_scan 工具执行扫描。
  只返回原始 JSON 结果，不要添加任何解释。
tools:
  - name: nmap_ping_scan
    description: 对给定网段执行 ping 扫描
    parameters:
      target: string
```

端口扫描、漏洞扫描等用同样的方式写成配置。

2. 编排器（主智能体）工作流程

编排器本身也是一个使用 LLM 的对话入口，它唯一的调度工具是 `create_agent`：orchestrator 根据注册表中的专家能力清单分析意图，自行编写完整的任务指令文本，通过 `create_agent(name, task, target)` 调度对应专家。每次调用后，将子智能体返回结果带回对话上下文，继续决策下一步。

在 OpenAI 兼容的 API 下，编排器的 tools 定义：

```json
[
  {
    "type": "function",
    "function": {
      "name": "create_agent",
      "description": "创建并调度一个专家智能体执行指定任务。name 必须在注册表中，task 为完整任务指令，target 为路由/审计标识。",
      "parameters": {
        "type": "object",
        "properties": {
          "name": {"type": "string", "description": "专家智能体名称，如 asset_discovery / port_scan / vuln_scan"},
          "task": {"type": "string", "description": "完整的任务指令文本（含目标、已知信息、动作要求）"},
          "target": {"type": "string", "description": "路由/审计用目标标识"}
        },
        "required": ["name", "task", "target"]
      }
    }
  }
]
```

核心执行循环：

```
用户：扫描 192.168.1.0/24 的高危漏洞
↓
编排器 LLM 首轮（带着 create_agent 工具）：
  分析意图 → 决定先调用 create_agent(name="asset_discovery", task="对 192.168.1.0/24 执行存活探测...", target="192.168.1.0/24")
↓
系统：执行 asset_discovery 子智能体，得到 {"ips":["192.168.1.1","192.168.1.100"]}
↓
将函数调用结果作为工具消息返回给编排器 LLM
↓
编排器 LLM 第二轮：
  分析结果 → 调用 create_agent(name="port_scan", task="对 192.168.1.1, 192.168.1.100 执行端口扫描...", target="192.168.1.0/24")
↓
系统：执行 port_scan，得到开放端口和服务列表
↓
编排器 LLM 第三轮：
  调用 create_agent(name="vuln_scan", task="基于以下服务信息执行高危漏洞扫描...", target="192.168.1.0/24")
↓
最后编排器汇总所有步骤结果，格式化回复用户。
```

关键的几点：

· 编排器只需要一个标准的 LLM 对话循环，加上 `create_agent` 这一个调度工具，无需预先定义流程图。
· 下一步的决策完全由 LLM 根据当前状态和注册表能力描述实时作出，天然支持多轮、中断和异常处理。
· 如果用户需求模糊，编排器可以反问澄清（比如没有提供目标网段时），同样通过对话完成。

· 编排器的每一轮决策都要给用户回复一个摘要信息，不能把思维链全部输出，可以额外调用小模型进行总结。

3. 子智能体的执行

每个子智能体可以按以下方式工作：

· 接收标准化输入（来自编排器生成的参数）。
· 内部使用自己的系统提示词，接入用户上传的skills，通过skills调用更底层的工具（nmap、hydra 等）。
· 返回结构化 JSON（通过输出 schema 保证）。
· 你完全可以为每个子智能体再使用一次 OpenAI API，或者直接用一个预先注册好的 Python 函数封装。

4. 上下文传递与依赖处理

编排器 LLM 在调用 `create_agent` 时，会在 `task` 指令文本中自然地引用上一步产出的关键信息（如 IP 列表、端口/服务列表）。LLM 能看到整个对话历史（包括之前工具返回的结果），因此只需在 `task` 文本中直接写入需要传递的数据，无需显式的 `$step_X.output` 变量引用。子智能体的系统提示采用极简骨架（仅含 hard rules 和 workspace 路径），角色描述和业务指令完全由 orchestrator 在 `task` 中承载。

四、可能需要的增强

· 并行执行：如果编排器在一次响应中发出了多个独立的 tool_calls，可以并行执行它们，等全部完成再一次性返回结果，你的执行器只需处理并发。
· 人工确认：在执行危险动作前，在对话界面中插入一个“确认节点”，暂停循环等待用户输入。
· 长上下文裁剪：如果扫描结果数据很大，可以只保留关键摘要（如 IP/端口列表），避免超出Token限制。
· 异常处理：子智能体执行失败时，能将错误信息插入对话，让编排器决定重试、跳过或询问用户。