# Agent.md — AI Agent 开发铁律

---

## 00. 如何使用本文档

- **每章三段式**：**铁律（Do）** + **反模式（Don't）** + **Hermes 教训**。Do/Don't 是必须遵守的硬约束，教训段解释「为什么」。
- **遇到不确定的设计**：先回到本文档对照铁律，再查 [Hermes 原文](https://pty819.github.io/hermes-docs) 对应章节。
- **本文档不替代细则规范**：项目内部的具体接口约定、数据库 schema、API 协议应另行规范；本文档负责跨项目可复用的工程铁律。
- **优先级**：以下 14 章按重要度排序 — 越靠前的章节，违反代价越高。第 01-04 章是「不可让步」级别。

---

## 01. 主循环（Agent Loop）

Agent 的本质是 **Observe → Think → Act** 的循环。这个循环必须健壮到「就算每个子系统都在抖动，主循环也不会停」。

### 铁律

1. **回调（callback）必须 try/except 包住**。stream_callback / tool_progress_callback / step_callback 一律视为「不可信外部代码」，其异常绝不能上浮到主循环。
2. **错误必须分类后处理**，不要用 `except Exception: retry`。最少分出 11 类：`auth / auth_permanent / billing / rate_limit / overloaded / server_error / timeout / context_overflow / payload_too_large / model_not_found / format_error / unknown`。Anthropic 路径再多两类：`thinking_signature / long_context_tier`。
3. **iteration budget 必须分层**：单工具 ≤ 100K chars、单轮 ≤ 200K chars、单会话 ≤ 90 iterations（参考值）。子 Agent 默认 50 iterations。
4. **budget 耗尽前必须留「grace call」**。两段式退出：先注入「这是最后一次」系统消息让模型自己收尾；再给一次额外 API 调用让模型出最终回复；这次还 tool_call 就强制退出。
5. **重试用 jittered exponential backoff**：`min(base*2^(n-1), max) + random*0.5*delay`，默认 `base=5s / max=120s`。每次调用用独立 seeded RNG，不污染全局 random。
6. **主循环保持同步（sync）**。需要 await 时用「持久化事件循环 + 异步桥」，不要在主循环里 `asyncio.run()`。
7. **流式响应必须有 stale-stream 检测**。90 秒没有 chunk 就视为僵死，主动断开重连。
8. **iteration budget 是线程安全的共享对象**（parent / child agent 共用一个 Lock-protected counter），不是函数参数。
9. **粘贴的脏数据先清洗再喂给模型**：U+D800–U+DFFF 代理对会直接让 `json.dumps()` 崩溃；stale `<memory-context>` 块要剥掉。
10. **每轮重置 fallback 索引**。fallback 链是「这一轮失败时往哪走」，不是跨轮持久状态。

### 反模式

- ❌ `except Exception as e: time.sleep(5); retry()` —— 把 401 当 500 来 retry，永远不会成功。
- ❌ `asyncio.run(do_tool())` 在长生命周期进程里调用 —— httpx/AsyncOpenAI 连接池会抛 "Event loop is closed"。
- ❌ 在主循环里 `raise` 未分类异常 —— 用户看到一个 traceback，不知道是该换 key 还是该等一会。
- ❌ budget 用完立刻 `break` —— 用户看到一个半截回复、未保存的文件、被中断的命令。
- ❌ 所有 callback 共享一个 try/except —— 一个回调挂了，其余全部静默失败。

### Hermes 教训

- Hermes 主循环 `run_conversation()` 的退出条件是 `(api_call_count < max_iterations and budget.remaining > 0) or _budget_grace_call`，**专门为 grace call 留了第二个分支**。
- 14 种 FailoverReason 的分类管线优先级：`provider-specific patterns → HTTP status → structured error codes → message regex → transport heuristics → context-overflow heuristics → unknown`。每多一层精度，retry 成功率上一个台阶。
- 402 状态码有专门的 `_classify_402()`：包含 "try again" / "resets at" / "retry" 字样的归为 `rate_limit`，否则归为 `billing`（必须轮转凭据）。
- Hermes 选择「同步主循环 + 按需 async 桥」是因为：OpenAI SDK 主路径是同步的；ThreadPoolExecutor 并行工具与 asyncio 嵌套有冲突；同步的 try/except 调试更直观。
- Jitter 用 `time.time_ns() ^ counter ^ 0x9E3779B9` 做种子，是为了对抗 thundering herd —— 多个客户端同时退避，依然不会撞墙。

---

## 02. 工具系统（Tools）

工具是 Agent 的「肌肉」。工具系统的复杂度永远大于你最初估计的两倍 —— 因为模型会用各种你没预料的方式调用它。

### 铁律

1. **工具必须自注册（self-registration）**，模块级调用 `registry.register(name, schema, handler)`。集中式注册表是技术债。
2. **工具发现用 AST 预扫描**：只看 `tree.body` 顶层语句里有没有 `register()` 调用，命中才 import。比 `import then check` 快得多、副作用小得多。
3. **参数必须类型矫正**（type coercion）。模型经常返回 `"42"` 而 schema 是 int、`"true"` 而 schema 是 bool、`"a,b,c"` 而 schema 是 list[str]。在 dispatch 前统一矫正，不要让 handler 自己处理。
4. **工具并行执行分三档**：
   - `NEVER_PARALLEL`：任何会与人交互的工具（clarify / ask_user / approval），单独走，不并行。
   - `PARALLEL_SAFE`：只读、无共享可变状态（read_file / web_search / search_files / session_search）。
   - `PATH_SCOPED`：读写文件类，并行前必须比较**路径分量**判断重叠（不是字符串前缀！）。
   - 不在三档里就**默认串行**。
5. **工具结果有三层 budget**：单工具 ≤ ~100K chars（超出转写盘 + 1.5K 预览）；单轮 ≤ ~200K chars；总迭代 ≤ 90。
6. **工具名幻觉必须修复**：模型可能调用 `read-file` 而注册的是 `read_file`；可能加多余前缀 `mcp__read_file`。先 fuzzy match 修复一次；修不好就把可用工具列表当作 tool_result 喂回去让模型自纠。**连续 3 次修不好就 abort**。
7. **工具注册冲突必须保护**。MCP 第三方工具不能影子化（shadow）内置工具；用 `mcp__<server>__<tool>` 命名空间隔离。
8. **工具 handler 异常必须分类返回**，不要直接 raise。返回 `{"error": "...", "type": "user_error" / "system_error"}` 让模型自己决定要不要重试或换路径。
9. **每个工具声明 `availability_check`** —— 工具未就绪时不该出现在 schema 里，避免模型调用不可用工具浪费 budget。
10. **工具的 `description` 字段直接影响选择**。写描述就是写 prompt，要简洁、明确、给 1-2 个使用场景示例。

### 反模式

- ❌ 把所有工具集中在 `tools.py` 里手动注册 100 个 —— 每加一个工具 PR 都会改这个文件，频繁冲突。
- ❌ Handler 内部做类型转换 —— 每个 handler 都得写一遍，遗漏一个就线上崩。
- ❌ 工具结果不设上限直接塞回 context —— 一次 `read_file` 读了 5MB 的 log，整个会话作废。
- ❌ 并行执行 `write_file("a.txt")` 和 `write_file("a.txt")` 因为「字符串不同」—— 路径标准化后是同一个文件。
- ❌ `register("read_file", ...)` 在两个模块里同时调用 —— 后注册的悄悄覆盖前者，运行时才发现行为不对。

### Hermes 教训

- Hermes Tool Registry 是单例，模块级 `@register` 触发；发现机制是 AST scan `_has_register_call(tree)`，**只检查顶层 statement 不递归**，避免误判 helper 函数里的同名调用。
- 三档并行的判定函数 `_should_parallelize_tool_batch()` 默认返回 `False`，必须所有 call 都在白名单里才返回 `True`。「不确定就串行」是工程铁律。
- Path-scoped 重叠检测比较的是 `Path(a).parts` 和 `Path(b).parts` 的前缀关系，不是字符串 `startswith`。`/var/log` 和 `/var/logs` 字符串前缀是匹配的，路径上是无关的。
- 工具名修复用 Levenshtein + 前后缀剥离；失败时返回的 tool_result 是 `"Available tools: read_file, write_file, ..."`，**让模型自己看清楚再调一次**。比直接报错有效。
- Hermes 的 `coerce_tool_args()` 处理了至少 6 种模型输出畸形：bool 字符串、数字字符串、CSV 列表、JSON-encoded 字符串、`null` 字符串、嵌套 dict 的扁平化。

---

## 03. 提示工程管线（Prompt Pipeline）

System Prompt 不是一段字符串，是一条流水线。流水线的每个 slot 都要可缓存、可审计、可注入扫描。

### 铁律

1. **System Prompt 必须按 slot 组装**：identity / capabilities / available_tools / current_context / memory / skills / user_rules / runtime_state / closing_directives。每个 slot 单独可替换。
2. **system_prompt 在会话内必须字节一致**。一旦生成就缓存到 `_cached_system_prompt`；任何修改要重建并失效缓存，**不能就地 mutate**。
3. **跨会话恢复时 system_prompt 必须从持久存储重载**，不能重新拼装。哪怕拼装函数没变，浮点格式化、字典顺序等微小差异都会让 prompt cache 全部失效。
4. **Anthropic 路径必须用 4 个 cache breakpoint**：1 个给 system prompt，3 个给滚动的最近消息。报告可节省约 75% 输入 token。
5. **所有注入 system_prompt 的外部内容必须扫描**：AGENTS.md / SOUL.md / .cursorrules / MCP tool description / memory 内容 / 工具返回的大文本。
6. **扫描器至少含 10 类正则 + 10 个 invisible Unicode**：
   - 正则：指令覆盖、隐瞒指令、role-tag 注入（`<system>` `<human>`）、规则绕过、HTML/CSS 隐藏、翻译执行陷阱、credential 外泄、敏感文件读取、curl-then-exec、base64 decode。
   - Unicode：U+200B/C/D（零宽）、U+FEFF（BOM）、U+2060（word joiner）、U+202A-E（双向覆写）。
7. **扫描命中要**：context 文件 → **直接屏蔽**替换为 `[BLOCKED: ...]`；MCP 工具描述 → **warn 不屏蔽**（避免误伤合法服务器，但留审计日志）。
8. **system_prompt 不可被用户消息影响**。绝不把用户输入拼到 system 段，永远走 user/assistant message 流。

### 反模式

- ❌ `system_prompt = f"You are an assistant. Current time: {datetime.now()}"` —— 每次都不同，cache 命中率为 0。
- ❌ 在恢复会话时重新调用 `build_system_prompt()` —— 一个空格、一个 emoji、一个换行就让 cache miss。
- ❌ 把 MCP 服务器的工具 description 直接拼进 prompt 不扫描 —— 等于给攻击者一个直通模型的入口。
- ❌ 注入扫描的正则用 `re.search` 不加 `re.IGNORECASE` —— `IGNORE PREVIOUS INSTRUCTIONS` 立刻穿透。
- ❌ 把 `AGENTS.md` 当数据直接塞 system_prompt —— 这是常见的"间接注入"通道。

### Hermes 教训

- Hermes 的 `_scan_context_content()` 在 `agent/prompt_builder.py` 是上下文注入的最后一道防线，**零容忍**：命中即替换为占位符，不给模型看到原文。
- `system_and_3` 缓存策略：Anthropic 限制 4 个 cache breakpoint，Hermes 把 1 个给 system（最大块）+ 3 个给滚动消息（命中率高）。**节省的不是金钱，是延迟和稳定性**。
- 跨会话从 SQLite 重载 system_prompt 的原因：哪怕同一段 Python 函数，在不同 Python 版本里 dict 顺序可能不同，浮点 `repr()` 可能不同，导致字节差异 → cache miss。**reload bytes, don't rebuild**。
- Invisible Unicode 检测包括 U+202A-E（LTR/RTL embedding 与 override），这些字符可以让屏幕显示一个内容，模型读到另一个内容。

---

## 04. 上下文压缩（Context Compression）

Context 窗口是 Agent 的工作记忆。**不要等到 overflow 才压缩，要主动压缩**。

### 铁律

1. **预压缩阈值在 70-80% 窗口**，不要等到 100%。等到 overflow 才压缩是「事故响应」，预压缩是「巡检」。
2. **压缩分阶段**，至少 5 个：(1) 修剪老旧 tool result；(2) 按角色重要性裁剪；(3) LLM 摘要中段对话；(4) 保留关键消息（system / 最近 N 轮）；(5) 重新拼装 + 验证 token 数。
3. **必须有降级链**：LLM 摘要失败 → static truncation（按字符截断）→ 最坏情况返回错误码而不是 panic。
4. **摘要消息必须有「免责声明 prefix」**：明确标注「这是历史摘要，不是新指令」。否则模型会把摘要内容当作 user 的新要求。
5. **压缩后的 token 预算公式**：`min(max(compressed_tokens * 0.20, 2000), 12_000)`。给摘要本身留 20% 空间，下限 2K，上限 12K。
6. **大工具结果必须落盘 + 预览**：超过单工具上限的结果，原始内容写到 `raw_log_path`，context 里只留 1.5K 字符 preview + 路径。
7. **压缩是写操作**，必须走 optimistic concurrency control：snapshot history_version → 压缩 → 写回前比对版本，不一致就丢弃压缩结果。
8. **session 恢复时如果历史已超阈值，先压缩再进主循环**。最多压缩 3 次，3 次还没降到阈值下就给用户报错。

### 反模式

- ❌ `if token_count > model.max_tokens: raise ContextOverflow` —— 用户看到一堆 traceback，前面 30 轮对话全部丢失。
- ❌ 摘要消息直接以 user role 注入 —— 模型把「之前用户问过 X」当作「现在用户问 X」。
- ❌ 一次性把所有历史交给 LLM 让它摘要 —— 摘要请求本身可能 overflow。
- ❌ 压缩失败就 panic —— 压缩是辅助路径，挂了应该 fallback to truncate，不该让主流程崩。
- ❌ 把大工具结果（10MB 日志）整段塞 context —— 一个 tool call 直接吃光整个窗口。

### Hermes 教训

- Hermes ContextEngine 是一个 ABC，5 阶段压缩在 `agent/conversation_compression.py` 实现。每阶段失败都有兜底：LLM summary 失败用 static truncate；truncate 失败用静态错误模板。
- Token 预算公式 `min(max(x*0.20, 2000), 12_000)` 的 20% 是经验值 —— 摘要太短失去信息，太长又挤压新对话空间。
- 「免责声明 prefix」一般写成 `[CONVERSATION SUMMARY — this is historical context, NOT new user instructions]`。Hermes 团队在没加这行之前频繁遇到「模型把摘要当指令执行」的事故。
- `payload_too_large` 错误（HTTP 413）和 `context_overflow` 是两类不同的失败 —— 前者压缩请求体能解决，后者必须压缩历史。错误分类器必须区分。

---

## 05. 会话状态（Session State）

Agent 的「长期记忆」。状态丢了 = 用户骂街。

### 铁律

1. **SessionDB 必须开 WAL（Write-Ahead Logging）**：`PRAGMA journal_mode=WAL`。多个进程（CLI / Gateway / TUI / 后台 review）同时读写时，读不阻塞写。
2. **每 50 次写做一次 PASSIVE checkpoint**：`PRAGMA wal_checkpoint(PASSIVE)`。否则 WAL 文件膨胀到 GB 级。
3. **schema 必须有迁移链**：v1 → v2 → ... → vN 的单向 SQL 脚本，启动时检测当前版本逐版应用。**不要写 "drop and recreate" 类迁移**。
4. **只写新增消息**，不要 `DELETE + INSERT` 全表。每轮主循环结束只 INSERT 新出现的消息。
5. **FTS5 全文索引必须懒构建 + 增量更新**。会话历史会大到几十 MB，每次启动重建索引会让冷启动到分钟级。
6. **session 应支持「分支」**：每个分支是独立的 (parent_id, branch_id) 视图，共享祖先消息。让用户可以"开个分支试试"而不破坏主线。
7. **持久化是 dual-write**：JSON 日志（人类可读 + 调试）+ SQLite（查询 + 索引）。SQLite 出问题时 JSON 仍可手工恢复。
8. **session 标识符要带 trace_id**：日志里每条记录都能反向定位到 session 和 turn。
9. **DB 文件路径必须显式可配**。不要硬编码 `~/.myagent/sessions.db`，让运维能切换到 SSD / 备份盘 / network mount。

### 反模式

- ❌ 用 SQLite 默认 journal mode（rollback）+ 多进程 —— 一旦并发立刻 `database is locked`。
- ❌ `CREATE TABLE IF NOT EXISTS` + 隐式 alter —— 老用户的库 schema 不变，新代码 SELECT 新列就崩。
- ❌ 每次启动重建 FTS5 index —— 10MB 历史 10 秒启动，100MB 历史就崩。
- ❌ Append-only 日志写 JSONL 但用 `open(..., "w")` —— 日志被截断只剩当前 session。
- ❌ session id 用 `int(time.time())` —— 同一秒两个 session 直接撞 id。

### Hermes 教训

- Hermes SessionDB schema 迁移已经走到 v6，每一版迁移脚本都保留在仓库里，启动时通过 `PRAGMA user_version` 检测当前版本逐版 apply。**永远不删旧迁移脚本**。
- WAL + 50 次 PASSIVE checkpoint 的折中：PASSIVE 不阻塞读者，但来不及就让 WAL 涨；TRUNCATE 模式可以彻底清 WAL 但要等所有读者退出。生产环境用 PASSIVE。
- Hermes 的 session 分支模型来自 `/tree` 命令：主分支保存 scope / approved plan / confirmed findings；探索分支保存假设分析、误报排查；离开分支时生成 branch summary 写回主分支。
- Session DB 同时承担「prompt cache 的 reload 源」职责（见 03 章）—— 这是设计上的双重身份，要记住。

---

## 06. 配置管理（Config）

配置混乱是 production 事故的常见根因。Agent 的配置层级比普通服务多一倍：env、文件、profile、运行时覆盖、模型 capability、provider 限制。

### 铁律

1. **配置至少 4 层叠加**：默认 → 文件（`config.yaml`）→ 环境变量 → 运行时覆盖。**后者覆盖前者**，且每层来源在 effective config 里可追溯。
2. **凭据隔离到独立文件**：`~/.<app>/.env` 与 `config.yaml` 分开存，权限 `0600`。**永远不在主配置里放明文 key**。
3. **凭据自动检测要有显式 gating**：哪些环境变量算「凭据」、哪些不算，要白名单显式声明。避免 `CLAUDE_CODE_OAUTH_TOKEN` 这种"看起来像但不该自动用"的变量被误识别。
4. **Profile 系统**：同一 Agent 在不同场景（开发 / 生产 / 隔离测试 / 演示）行为不同。Profile = `config + env + risk_level + tool_whitelist` 的命名组合。
5. **配置变更要 hot reload**：监听文件 + 信号触发，不要让用户为了改一个参数重启进程。
6. **删除的凭据要能阻止再次自动种入**：很多 SDK 会从 `~/.claude/.credentials.json` / OAuth token 缓存自动恢复，需要 `suppress_credential_source()` 类机制显式压制。
7. **i18n 支持要内置**：错误信息、UI 文案、prompt 模板分文件存。**绝不在代码里硬编码可见字符串**。
8. **effective config 必须可 dump**：`my-agent config show` 应该打印「最终生效的配置 + 每个字段来自哪一层」。
9. **凭据池**用结构化文件（如 `auth.json`），跨进程加锁（`fcntl.flock` / `msvcrt.locking`），轮转策略明确。

### 反模式

- ❌ `OPENAI_API_KEY = os.environ.get(...)` 散落在 N 个模块里 —— 凭据轮转时漏改一处就崩。
- ❌ 配置文件存 `0644` —— 同机器其他用户能读 key。
- ❌ 环境变量与配置文件同时定义同一字段，行为静默 —— 用户改了 yaml 没生效以为系统坏了。
- ❌ Profile 用「全局变量切换」实现 —— 切回来时残留状态没清干净。
- ❌ Hot reload 时直接替换 `config = new_config` —— 正在使用旧配置的工具调用拿到一半新一半旧。

### Hermes 教训

- Hermes 凭据池在 `auth.json`，用 `fcntl.flock()`（Unix）/ `msvcrt.locking()`（Windows）做跨进程互斥，15s 超时，可重入。**没有锁就会出现两个进程同时轮转到同一个 key**。
- `is_provider_explicitly_configured()` 显式排除 `CLAUDE_CODE_OAUTH_TOKEN` 这类「看起来像凭据但属于另一个产品」的环境变量。**白名单原则**。
- `suppress_credential_source()` 的存在是因为用户删除了某个 key 后，下次启动它又从某个隐藏路径冒出来 —— 必须有显式的「source 抑制」机制。
- Profile 切换时 Hermes 重建整个 client + tool registry + session context，**不复用旧 profile 的任何对象**，避免状态泄漏。

---

## 07. 模型路由（Model Routing）

支持多个 LLM provider 几乎是必然的 —— 不是为了 vendor 中立，是为了 fallback 和成本控制。

### 铁律

1. **响应必须归一化**：所有 provider 返回的对象统一成 `SimpleNamespace`，下游代码只读 `.content` / `.tool_calls` / `.usage`。
2. **client 必须缓存**，不要每次调用都 `OpenAI()`。TLS 握手 + 连接池建立耗时显著。
3. **Provider 差异封装在 adapter 内**：错误格式转换、特殊参数（thinking_signature）、流式协议（SSE / event-stream）。**不允许 `if provider == "anthropic"` 散落主循环**。
4. **凭据池 + 轮转策略**：单 key 触发 rate_limit 时切换下一个 key；持续失败 N 次标记为「暂停」，过 cooldown 再启用。
5. **Fallback 链每轮重置**：fallback 是「这一轮的应急梯子」，不是跨轮持久。每轮开始时 `_fallback_index = 0`。
6. **402 状态码歧义消解**：消息文本含 "try again" / "resets at" → rate_limit 类（等会儿重试）；否则 billing 类（必须换 key）。
7. **`finish_reason == "length"` 不是错误**，是续写信号。续写时用 `list.append + "".join` 拼接，**不要用 `+=`**（O(n²)）。
8. **provider 特定的 prompt 兼容性问题在 adapter 层处理**：例如 Anthropic 的 thinking 指令不能传给 OpenAI；OpenRouter 某些 model 不支持 tool_call。
9. **`api_mode` 字段路由**：单个 AIAgent 类持有 `api_mode in {chat_completions, anthropic_messages, codex_responses, bedrock_converse}`，根据它走不同 streaming / tool_call 路径。

### 反模式

- ❌ `if isinstance(client, AnthropicClient): ...` 在主循环里出现 —— 加新 provider 就要改十处。
- ❌ 每个 tool call 都 `client = OpenAI(api_key=...)` —— 几百 ms 的 TLS 全是浪费。
- ❌ 402 一律当 billing 报错 —— 实际是临时限流，用户 5 分钟后就能恢复，被你劝退了。
- ❌ Fallback chain 用全局变量记录"上次跑到哪了" —— 这一轮的失败影响下一轮。
- ❌ 把 provider 的原始 response 对象直接传给业务层 —— 换 provider 时业务层全部要改。

### Hermes 教训

- Hermes 用 `types.SimpleNamespace` 而不是自定义 `Response` 类，是因为 lightweight、无 boilerplate、attribute access 直观。**不需要的抽象就别加**。
- 「`if provider == "ollama"` / `if provider == "openrouter"`」散落主循环是 Hermes 公开承认的技术债 —— 因为某些 provider 的行为差异渗透到全局流程（错误格式、连接管理、特殊参数），不是单个 call site 能封装的。**架构警告**：adapter 模式有边界，超出边界时要正视。
- 402 的 `_classify_402()` 函数源于一次事故：一个用户的 OpenRouter 余额其实没花完，但被 401 类错误劝退；事后查日志发现消息里写着 "rate limit, retry in 60s"。
- 连接池复用让 Hermes 单次 API 调用平均延迟降低 ~200ms（TLS 握手成本）。

---

## 08. 进程间通信（IPC）

Agent 越来越少是「一个进程」—— CLI / Gateway / Worker / Slash command 各自跑在不同进程里。IPC 设计错了，整个产品都不稳。

### 铁律

1. **首选 JSON-RPC over stdin/stdout**。简单、human-readable、调试时直接 `cat` 即可观察。不要默认 gRPC / Protobuf 除非真的需要 schema 强约束。
2. **子进程持久化复用**：用一个常驻 SlashWorker 子进程持有解释器 + 已加载模块，不要每次 slash command 都 `subprocess.run()`。冷启动开销以秒计。
3. **子进程崩溃必须隔离**：worker 挂了，主进程不能跟着死。捕获子进程退出码 + stderr，转化为 user-facing 错误，自动重启 worker。
4. **跨进程状态写入用 Optimistic Concurrency Control**：snapshot version → 操作 → commit 前比对 version，**不一致就丢弃自己的修改**。不要用全局锁。
5. **RPC 方法必须有 timeout**。50+ 个 RPC 方法每个都该声明上限，避免某个慢请求挂住整个 gateway。
6. **stdio 用 `_SafeWriter` 包装**：systemd / Docker 下 broken pipe 会抛 `OSError`，业务代码不该看到这个；包一层 swallow。
7. **协议版本号必须显式**：`{"jsonrpc": "2.0", "method": "...", "protocol_version": "1.3"}`。版本不兼容时主动报错而不是行为漂移。
8. **不要在 RPC 边界透传内部对象**：所有跨进程数据都序列化成基础类型 dict / list / str。

### 反模式

- ❌ 用 Python pickle 跨进程传对象 —— 任何对象图变更直接破坏兼容性 + 安全风险。
- ❌ 每个 slash command 都 `fork + exec` —— 用户每次都等 2 秒冷启动。
- ❌ 全局文件锁保护跨进程写 —— 一个 worker hang 住所有人。
- ❌ JSON-RPC 不带 id —— 异步响应回来对不上请求。
- ❌ stderr 直接打到 user-facing 输出 —— `Broken pipe` warning 让用户以为出 bug 了。

### Hermes 教训

- Hermes Gateway 有 **56 个 RPC 方法**，分类成 session / history / streaming / tool / config / plugin / mcp / kanban / skill 等组。每个方法显式声明 timeout，平均 30s，长操作（如压缩）单独配 5min。
- `SlashWorker` 是一个长期运行的 Python 子进程，持有 `HermesCLI` 实例 + 已加载的所有 slash command 模块。通过 stdin/stdout JSON-RPC 通讯，**冷启动一次 ~2s，复用调用 ~50ms**。
- Hermes Optimistic Concurrency 用 `history_version` 自增计数器实现：turn 开始时 snapshot，agent 写回前比对，不一致就丢弃 agent 的输出。**这比"锁住整个 history"更友好**：用户的 undo / retry 操作永远优先。
- `_SafeWriter` 在 `agent/conversation_loop.py` 包装 stdout/stderr，吞掉 `OSError` 和 `ValueError`。源于一次 systemd 部署事故 —— pipe 关闭引发整个 agent crash。

---

## 09. MCP 集成（Model Context Protocol）

第三方 MCP 服务器是攻击面的开放边界。把 MCP 当作「不可信代码」对待。

### 铁律

1. **MCP 工具描述必须扫描**（warn-level）：注入正则覆盖「ignore previous instructions」、`<system>` 注入、隐瞒指令、网络命令、base64 decode、危险 import。命中只 warn 不屏蔽，避免误伤合法服务器。
2. **MCP 工具命名空间隔离**：`mcp__<server>__<tool>`。内置工具优先注册；同名冲突时 **MCP 注册被拒绝**，不允许第三方影子化内置 `terminal` / `read_file`。
3. **OAuth 2.1 必须用 PKCE**，state 与 code_verifier **独立随机生成**。曾有实现把同一值同时当 state 和 verifier —— state 经 Referer 泄露后 verifier 也跟着完蛋。
4. **MCP 子进程必须用熔断器**：连续 N 次（默认 3）失败 → 进入「open」状态，后续调用立即 short-circuit；定时探活试图恢复。**关键是失败快，不是修复**。
5. **环境变量必须剥离**：传递给 MCP 子进程时，过滤所有匹配 `*_API_KEY` / `*_TOKEN` / `*_SECRET` / `*_PASSWORD` / `*_CREDENTIAL` 的变量；只传 server 声明的 `required_environment_variables`。
6. **工具名必须合法**：`[a-zA-Z0-9_-]+`，禁止 `/` `\`、禁止 `__` 前缀（除 `mcp__`）。**防路径穿越 + 防内置工具冒充**。
7. **MCP 错误消息必须脱敏**：错误回到 agent context 前用 `_sanitize_error()` 替换 `sk-...` / `Bearer ...` / API key 模式为 `[REDACTED]`。
8. **支持 stdio 和 HTTP 两种传输**，分别走独立的健康检查 / 超时 / 重连策略。HTTP 路径必须验证 TLS + 服务端证书。

### 反模式

- ❌ MCP 描述直接拼进 system_prompt 不扫描 —— 等于把 prompt 注入入口让给任何第三方服务器。
- ❌ MCP 注册了 `terminal` 工具直接覆盖内置 —— 攻击者通过 `terminal` 拿到 shell 任意命令。
- ❌ OAuth state 与 PKCE verifier 共用同一随机值 —— state 经过 Referer 泄露 = verifier 也泄露。
- ❌ MCP server 一连接就把所有环境变量 `os.environ.copy()` 传过去 —— API key、AWS credential 全送给第三方。
- ❌ MCP server 挂了主循环跟着卡 —— 没有熔断 = 一个不稳定服务器拖垮整个 agent。

### Hermes 教训

- Hermes 集成 OSV 恶意软件数据库做 MCP server 安装时校验（章节 12.9.5）。**第三方代码不要先信任后检查**。
- 熔断器阈值默认 3 次失败，cooldown 60s，half-open 探测 1 次成功就完全恢复。**Hermes 团队反复强调：熔断的价值不是修复故障，是阻止故障扩散**。
- 命名空间 `mcp__<server>__<tool>` 是 4 字符前缀 + 服务器名 + 工具名。**唯独 `mcp__` 这个 `__` 前缀被允许**，其他工具一律禁止双下划线开头，防伪冒。
- `_sanitize_error()` 不只在 MCP 路径用，凡是错误流回 agent context 的地方都用。**任何凭据都不该被模型看到，因为模型可能把它写进文件 / 回显给用户**。

---

## 10. 插件与技能系统（Plugin & Skill）

可扩展性 = 让用户/第三方在不改主仓库的前提下加能力。两个核心机制：**plugin** 改行为（hook），**skill** 加知识（progressive disclosure）。

### 铁律

1. **Plugin 通过显式 hook 介入主流程**：`pre_tool_call` / `post_tool_call` / `on_session_start` / `on_session_end` / `on_message`。**hook 必须可被禁用**，否则坏 plugin = 永久故障。
2. **Plugin discovery 走 `plugin.yaml` 元数据**，不靠 import 时副作用。yaml 含 name / version / entry / capabilities / required_permissions。
3. **Plugin context API 必须冻结**：plugins 看到的 `ctx` 对象只暴露官方 API，不允许穿透到内部对象。否则升级时全部 plugin 崩。
4. **Skill 用 progressive disclosure**：`SKILL.md` 含 metadata + 简短 description + 何时使用。**完整内容按需加载**，不一次塞 system prompt。
5. **Skill 索引 + 双层缓存**：内存 LRU + 磁盘 JSON snapshot。冷启动时从 snapshot 恢复，避免每次重新扫描所有 skill 文件。
6. **Skill 加载触发要明确**：模型显式调用 `load_skill(name)` 时才加载，**不要根据相关度自动注入**（容易 mis-fire 浪费 token）。
7. **Plugin 错误必须隔离**：`pre_tool_call` 抛异常 → 工具调用被拒绝，但主循环继续；`post_tool_call` 抛异常 → 工具结果保留，hook 失败被记录。
8. **Plugin 权限模型**：plugin 声明它需要哪些工具 / 哪些 hook / 哪些文件系统访问；运行时 enforce。

### 反模式

- ❌ Plugin 通过 monkey-patching 主类方法 —— 升级时无声破坏。
- ❌ 所有 skill 启动时全部加载到 context —— 100 个 skill = 100KB prompt overhead。
- ❌ Plugin 抛异常直接上浮主循环 —— 一个 bug plugin 让整个 agent 不可用。
- ❌ Skill 用文件名做唯一标识 —— 用户重命名后引用全部失效。
- ❌ Plugin context 直接是 `self`（整个 agent 实例）—— plugin 可以调用任意内部方法，等于无沙箱。

### Hermes 教训

- Hermes Plugin 系统的 `PluginContext` API 只暴露 ~15 个方法（session 读、log、emit event、注册 hook），**internal state 全部隐藏**。这是「冻结契约」原则。
- Skill 双层缓存：内存 LRU 默认 128 entries，磁盘 JSON snapshot 在 `~/.hermes/skill_cache.json`，下次启动直接 load 而不是 rescan filesystem。冷启动从 ~2s 降到 ~200ms。
- Hermes Skill 触发是 LLM 显式调用 `load_skill(name)`，**不是基于检索相关度自动注入**。理由：自动注入误判率高、模型对突然出现的指令会困惑、调试困难。

---

## 11. 安全设计（Security）

Agent 安全的核心命题：**模型不可信，输入不可信，工具结果不可信**。Defense in depth。

### 铁律

1. **危险命令必须人工 approval**。至少识别 38+ 模式：`rm -rf /` 类、`chmod 777` / 递归 chown root、SQL DROP without WHERE、`mkfs` / `dd if=` 类、`curl ... | sh`、`sudo -S/-A/-i/-s`、`git reset --hard` / `push --force` / `clean -f` / `branch -D`。
2. **命令匹配前必须归一化**：去 ANSI 转义、去 null byte、Unicode NFKC（防止 `ｒｍ` 全角字符绕过）。
3. **Approval 至少 3 模式**：`manual`（默认）/ `smart`（辅助 LLM 自动判低风险）/ `off`（明确禁用 = 危险）。Cron / 自动化场景默认 `deny`。
4. **会话级 approval 状态用 `contextvars.ContextVar`**，不要用全局 dict —— 并发请求会互相污染。
5. **沙箱执行必须剥离凭据 env**：`*_API_KEY` / `*_TOKEN` / `*_SECRET` / `*_PASSWORD` 一律 strip；只通过 `env_passthrough` 白名单透传。
6. **沙箱必须有资源上限**：CPU / 内存 / 磁盘 / 网络 egress。Docker 沙箱默认 `mount_cwd_to_workspace=false`，不挂载宿主目录。
7. **浏览器自动化必须阻断私网**：本地 / 192.168.x.x / 10.x.x.x / 169.254.x.x（SSRF 防御）；同时设置 inactivity timeout（120s）+ per-command timeout（30s）。
8. **预执行扫描器**（如 Tirith）作为额外防线：在 approval 通过之后、实际执行之前再扫一遍代码注入模式。**配 `fail_open=True`** —— 扫描超时不阻断合法操作，但留审计日志。
9. **凭据永远不能进入 model context**：所有错误信息流回模型前用 `_sanitize_error()` 替换 `sk-...` / `Bearer ...` 模式为 `[REDACTED]`。
10. **敏感写入路径必须 approval**：`~/.ssh/` / `~/.<app>/.env` / `/etc/` / `/dev/sd*` 即使通过环境变量引用也要拦截。

### 反模式

- ❌ 用字符串前缀匹配判断危险命令 —— `rm--rf` 绕过、`./rm` 绕过、`ｒｍ` 全角绕过。
- ❌ Approval 设个全局开关 `--yes-i-know` 一刀切关掉 —— 所有保护机制同时失效。
- ❌ Sandbox 用 `subprocess.run(..., env=os.environ.copy())` —— 所有凭据带进沙箱。
- ❌ Browser 工具不阻断 `127.0.0.1` —— SSRF 直击内网服务。
- ❌ 错误信息原样 `raise` 给 agent context —— 模型把 `Authentication failed: key=sk-xxx` 当回复发给用户。

### Hermes 教训

- Hermes Approval 系统在 `secbot/security/approval.py`（同设计模式），38+ 模式来自社区收集的命令注入案例。**Unicode NFKC 这一步**是因为发现过 `cm` / `ｃｍ` / `🅒🅜` 等多种变体绕过。
- Sudo 的 `-S` / `-A` / `-i` / `-s` 都被显式列入危险模式 —— `-S` 从 stdin 读密码可被注入，`-A` 用 askpass 程序也可被劫持。**单一关键字 "sudo" 不够，要看 flag 组合**。
- Tirith 配置 `fail_open=True` 的取舍：拒绝执行（fail_close）更"安全"但会让正常工作中断；fail_open 容忍扫描失败但靠其他防线兜底。**Defense in depth 才能允许任何一层 fail_open**。
- `_sanitize_error()` 在所有错误回到 agent context 的路径都用，包括 MCP / 工具 / 网络请求。**只在一个路径加 sanitize 是无效的 —— 凭据会从其他路径泄漏**。
- 浏览器私网阻断是因为有过 SSRF 事故：模型被诱导访问 `http://localhost:8080/admin`。**任何用户控制的 URL 都该过黑名单**。

---

## 12. 工程模式总结（Patterns）

跨章节复用的工程模式，记住它们就能少写很多代码。

### 必备模式

| 模式 | 解决的问题 | 典型用法 |
|------|------------|----------|
| **Strategy** | 多 provider / 多 backend 行为差异 | `api_mode` 字段路由到不同 dispatch 路径 |
| **Self-Registration** | 工具/插件/技能 N 个 + 集中注册是技术债 | 模块级 `register()` + AST 预扫描 |
| **Observer** | 主循环要通知 N 个外部系统（UI / TTS / hooks） | callbacks `stream_callback` / `tool_progress_callback`，每个 try/except |
| **Adapter** | provider 响应结构不同 | 全部归一化成 `SimpleNamespace` |
| **Circuit Breaker** | 外部服务（MCP）会 hang / crash | 失败计数 → open → 定时探活 → half-open → closed |
| **Optimistic Concurrency Control** | 长 turn + 短写入，避免锁住整个 history | `history_version` snapshot + commit 时比对 |
| **Write-Ahead Log** | 多读端 SQLite | `journal_mode=WAL` + 50 次 PASSIVE checkpoint |
| **Progressive Disclosure** | Skill / 文档不要全塞 prompt | metadata 索引 + 显式 load |

### 必备数据结构

- **`SimpleNamespace`** 做跨 provider 响应统一格式 —— 轻量、无 boilerplate、attribute access。
- **`contextvars.ContextVar`** 做请求级状态（approval mode、session id）—— 并发安全，无全局变量污染。
- **`threading.Lock`-protected counter** 做 iteration budget —— parent / child agent 共享。
- **AST `ast.parse(...).body`** 做工具发现 —— 比 import 快 + 无副作用。

### 数据流原则

- **共享结构化状态**（黑板 / Task Ledger / Evidence Store），**不共享完整会话历史**。会话历史共享 = prompt injection + context drift + token 膨胀 + 责任不清。
- **每个 worker 只读它需要的部分，只写结构化产出**。
- **主控/Orchestrator 唯一拥有**：授权范围、任务状态、风险策略、最终判断、报告签发权。

---

## 13. 反模式与技术债（Anti-patterns）

下面是 Hermes 团队**公开承认的失败**，照着避坑。

### 13.1 God Class

**症状**：核心类（如 `AIAgent` / `run_agent.py`）一年内长到 12,084 行，包含 multi-provider、streaming、compression、recovery、budgets、plugins、memory。

**后果**：
- 单元测试几乎不可能（mock 一切）。
- 新成员 onboarding 周期 2 周起。
- 每个 PR 都 merge conflict。
- 一个 bug fix 容易引入三个回归。

**预防**：每次往主类加方法时问自己「这能不能在子模块里？」**默认答案是「能」**。Hermes 后期 refactor 把 logic 移到 `agent/error_classifier.py` / `agent/retry_utils.py` / `agent/tool_executor.py` 等子模块，但已经积累的耦合很难完全拆开。

**铁律**：单文件超过 800 行就该开始考虑拆分；超过 1500 行必须拆分。

### 13.2 Provider-Specific Hack 散落主循环

**症状**：`if provider == "ollama": ...` / `if provider == "openrouter": ...` 在主循环、错误处理、连接管理处都有。

**后果**：加一个新 provider 要改十处；删一个 provider 要 grep 一遍代码库。

**根因**：某些差异（错误格式、连接管理、特殊参数）确实影响全局流程，不是单个 call site 能封装的。**Adapter 模式有边界**。

**预防**：当 adapter 边界开始渗漏时，正视这是架构问题。考虑：**(a)** 把差异升格成显式抽象（如 `api_mode` 字段路由）；**(b)** 把跨 adapter 的共性提取到 protocol。

### 13.3 手动 Cache 失效

**症状**：`_cached_system_prompt = None` 散落多处；memory 变了忘 invalidate；skill 加载完忘 invalidate。

**后果**：cache miss 率高 / 数据陈旧 / 调试时怀疑人生。

**预防**：用**版本号或内容 hash** 替代「手动设 None」。让 cache 自己判断 invalid。

### 13.4 共享完整会话历史给 Sub-Agent

**症状**：spawn 子 agent 时把 parent 的整段对话直接传过去当 context。

**后果**：
- prompt injection 跨 agent 传播（一个 worker 被注入 = 所有 worker 被注入）。
- Context drift（子 agent 看到不相关的历史，判断混乱）。
- Token 爆炸（每个子 agent 复制一份 history）。
- 责任不清（哪个 agent 看到了哪些信息无法审计）。

**预防**：parent 和 child 共享**结构化黑板**，**不共享完整会话**。child 只读它需要的字段，只写结构化产出。

### 13.5 `asyncio.run()` 在长生命周期进程

**症状**：每次需要 async 调用就 `asyncio.run(do_async())`。

**后果**：`Event loop is closed` 错误（httpx / AsyncOpenAI 连接池跟旧 loop 绑定）；连接池每次重建（性能损失）。

**预防**：用「持久化事件循环 + 异步桥」：主线程一个全局 loop，worker 线程用 thread-local loop，已在 async stack 内时退化成 ThreadPoolExecutor。

### 13.6 未分类异常吞噬

**症状**：`except Exception: log(e); retry()`。

**后果**：401（要换 key）被当 500（要 retry）一直重试；405（model 不存在）一直重试到 budget 用完。

**预防**：错误必须 classify 后再决定处理策略。**精确错误分类胜过通用 retry**。

### 13.7 Parent / Child Budget 共享不明确

**症状**：sub-agent 用独立 `max_iterations` 但跟 parent 共享凭据池 / rate limit。

**后果**：MoA fan-out 时所有 child 同时打同一个 rate limit，parent 反而被饿死。

**预防**：要么完全独立（独立 budget + 独立凭据池），要么完全共享（共享 budget + 共享凭据池）。**混合 = 难以推理**。

---

## 14. 构建路线图（Roadmap）

从零开始构建一个 Agent，按这个顺序最稳。

### MVA（200 行）：核心循环跑通

```text
组件清单：
  - Tool Registry（dict）+ register_tool(name, schema, handler)
  - 3 个内置工具：read_file / write_file / terminal
  - classify_error() 返回 'retry' / 'compress' / 'abort'
  - MinimalAgent(client, model, max_iterations=20)
  - run() 主循环：build system prompt → call API → 无 tool_calls 返回；有 tool_calls 执行 + append + 续轮
```

**MVA 显式排除**：streaming、multi-provider、context compression、parallel tool execution、session persistence、authentication。**这些都是 Phase 2+ 才加**。

### Phase 1 — 核心（1-2 周）

- 工具注册 + dispatch
- 错误分类（最少 5 类：auth / rate_limit / timeout / server_error / unknown）
- Session 持久化（SQLite，无 WAL 无 FTS）
- Iteration budget（单值）

### Phase 2 — 稳定（2-4 周）

- Context 压缩 + 预压缩
- 多 provider（至少 2 个）+ Adapter
- 凭据池 + 轮转
- WAL + checkpoint

### Phase 3 — 性能（1-2 周）

- 并行工具执行（三档）
- Prompt 缓存（Anthropic 4 breakpoint 或自实现）
- 三层 result budget

### Phase 4 — 扩展（2-4 周）

- Plugin / Hook 系统
- MCP 工具集成
- Skill / Skin / Theme
- IPC / Gateway（如果需要多进程）

### Phase 5 — 运维（持续）

- 监控 + 告警
- 日志分析
- 性能 benchmark + 回归检测
- 安全审计（注入扫描、credential leak 检测）

### 推荐技术栈（来自 Hermes）

| 维度 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | LLM SDK 最成熟 |
| LLM | OpenAI SDK + 自实现 Adapter | 兼容性最广 |
| 数据库 | SQLite（单机）/ PostgreSQL（多实例） | 零运维 vs 多读写 |
| 并发 | 同步主循环 + 按需 async 桥 | 调试简单 |
| 工具发现 | self-registration + AST | 快 + 无副作用 |
| 错误处理 | 分类管线 + jittered backoff | 精度 + 稳定 |
| Context | 预压缩 + LLM 摘要 + prompt cache | 节省 ~75% token |
| IPC | JSON-RPC over stdin/stdout | 简单可观察 |

### 何时偏离这个栈

- **微服务**：多租户规模 + 工具隔离需求。
- **全异步**：上百并发连接的 server 形态。
- **PostgreSQL**：多实例部署 + 复杂查询。
- **gRPC**：高频低延迟内部调用。
- **REST**：外部集成需求。

---

## 附录 A — Hermes 原文索引

| 主题 | URL |
|------|-----|
| 前言 | https://pty819.github.io/hermes-docs/chapters/preface.html |
| 基础概念 | https://pty819.github.io/hermes-docs/chapters/part1/index.html |
| 核心循环 | https://pty819.github.io/hermes-docs/chapters/agent-loop.html |
| 工具系统 | https://pty819.github.io/hermes-docs/chapters/tool-system.html |
| 提示工程管线 | https://pty819.github.io/hermes-docs/chapters/prompt-pipeline.html |
| 上下文压缩 | https://pty819.github.io/hermes-docs/chapters/context-compression.html |
| 状态与会话 | https://pty819.github.io/hermes-docs/chapters/session-state.html |
| 配置管理 | https://pty819.github.io/hermes-docs/chapters/config-management.html |
| 模型路由 | https://pty819.github.io/hermes-docs/chapters/model-routing.html |
| CLI 与 UI | https://pty819.github.io/hermes-docs/chapters/cli-ui.html |
| TUI Gateway | https://pty819.github.io/hermes-docs/chapters/gateway-rpc.html |
| MCP 集成 | https://pty819.github.io/hermes-docs/chapters/mcp-integration.html |
| 插件系统 | https://pty819.github.io/hermes-docs/chapters/plugin-system.html |
| 技能系统 | https://pty819.github.io/hermes-docs/chapters/skill-system.html |
| 安全设计 | https://pty819.github.io/hermes-docs/chapters/security.html |
| Kanban | https://pty819.github.io/hermes-docs/chapters/kanban.html |
| 工程教训 | https://pty819.github.io/hermes-docs/chapters/lessons.html |
| 构建你自己的 Agent | https://pty819.github.io/hermes-docs/chapters/build-your-own.html |
| 术语表 | https://pty819.github.io/hermes-docs/chapters/glossary.html |
| 文件索引 | https://pty819.github.io/hermes-docs/chapters/file-reference.html |

---

## 附录 B — 14 种 FailoverReason 速查表

| Reason | 触发 | 恢复策略 |
|--------|------|----------|
| `auth` | 401，可能临时 | 轮转凭据 → fallback provider |
| `auth_permanent` | 401 持续失败 | abort |
| `billing` | 402 余额耗尽 | 轮转凭据 → fallback |
| `rate_limit` | 429 | jittered backoff → 轮转 → fallback |
| `overloaded` | 503/529 | jittered backoff |
| `server_error` | 500/502 | retry |
| `timeout` | transport 超时 | rebuild client → retry |
| `context_overflow` | 某些 provider 400 | 压缩 context |
| `payload_too_large` | 413 | 压缩请求 |
| `model_not_found` | 404 | fallback to another model |
| `format_error` | 400 非 overflow | sanitize + retry，再 abort |
| `thinking_signature` | Anthropic 400 | auto-fix retry |
| `long_context_tier` | Anthropic 429 长上下文档 | 压缩 context |
| `unknown` | 不可分类 | jittered backoff |

---

## 附录 C — Prompt Injection 扫描清单

### 10 类正则

1. 指令覆盖：`ignore (all|previous|the) instructions`
2. 隐瞒指令：`do not (tell|inform|mention|reveal)`
3. 系统提示词覆盖：`system: |new instructions:`
4. role-tag 注入：`<system>` / `<human>` / `<assistant>`
5. 规则绕过：`act as if you have no (restrictions|rules)`
6. HTML/CSS 隐藏：`<!-- ... -->` / `display:\s*none`
7. 翻译执行陷阱：`translate (the following|this) into (executable|shell)`
8. credential 外泄：`curl .* \$(KEY|TOKEN|SECRET)`
9. 敏感文件读取：`(\.env|credentials|\.netrc|\.pgpass)`
10. exec/eval 引用：`(exec|eval)\s*\(`

### 10 个 invisible Unicode

| 码点 | 名称 |
|------|------|
| U+200B | Zero-Width Space |
| U+200C | Zero-Width Non-Joiner |
| U+200D | Zero-Width Joiner |
| U+FEFF | Byte Order Mark |
| U+2060 | Word Joiner |
| U+202A | LTR Embedding |
| U+202B | RTL Embedding |
| U+202C | Pop Directional Formatting |
| U+202D | LTR Override |
| U+202E | RTL Override |

---

## 卷尾

> **简单的、可靠的、可调试的方案，永远优于优雅的、复杂的、难以理解的方案。**

如果你在做架构选择时无法决定，回到这句话。
Hermes 的 12,000 行代码与无数次事故复盘最终留下的，就是这一句。
