# UX 设计 — Layout 设计

> 本文档基于 `webui/` 下的真实前端实现（React 18 + TypeScript + Vite + Tailwind + Radix/shadcn/ui + i18next）整理，记录当前 WebUI 的整体布局骨架、菜单/面板划分、核心交互流以及设计体系，供后续 UI 扩展与 HUD 模块接入时参考。
>
> 源码根目录：`webui/src/`

---

## 1. 总览：App Shell 骨架

整个前端是一个单页应用（SPA，无 URL 路由，通过 React 状态 `view: "chat" | "settings"` 切换主视图），入口在 [App.tsx](file:///Users/shan/Downloads/nanobot/webui/src/App.tsx)。顶层壳层结构自外而内依次为：

```
┌─────────────────────────────────────────────────────────────┐
│ 启动态（BootState）：loading / auth / ready                 │
│   ├── loading  → 居中 "connecting..." + 脉冲点             │
│   ├── auth     → AuthForm（密码输入，bootstrap 失败提示）  │
│   └── ready    → <ClientProvider> 包裹 <Shell />           │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Shell（lg 断点 1024px 双形态）                             │
│  ┌─────────────┬────────────────────────────────────────┐   │
│  │             │  ThreadHeader（顶部条）                │   │
│  │  Sidebar    │  ─────────────────────────────────────  │   │
│  │  272px 宽   │  ThreadViewport (flex-1)                │   │
│  │  （可折叠） │    ├── 有消息：ThreadMessages           │   │
│  │             │    └── 无消息：Hero 欢迎 + 快捷卡片     │   │
│  │             │  ─────────────────────────────────────  │   │
│  │             │  ThreadComposer（sticky 底部）         │   │
│  └─────────────┴────────────────────────────────────────┘   │
│  移动端：Sidebar 用 <Sheet> 以左侧抽屉覆盖主内容             │
└─────────────────────────────────────────────────────────────┘
```

核心布局特征：

- **两栏 Shell**：左侧固定宽 272px 的 [Sidebar](file:///Users/shan/Downloads/nanobot/webui/src/components/Sidebar.tsx)，右侧主区为 [ThreadShell](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/ThreadShell.tsx)/[SettingsView](file:///Users/shan/Downloads/nanobot/webui/src/components/settings/SettingsView.tsx)。
- **响应式断点**：以 Tailwind `lg:` 为分界。桌面端侧栏通过 `width: 272px ↔ 0` + `transition-[width] duration-300` 平滑折叠；移动端 (`< lg`) 侧栏隐藏，通过 [Sheet](file:///Users/shan/Downloads/nanobot/webui/src/components/ui/sheet.tsx) 从左滑入。
- **持久化**：侧栏展开状态写入 `localStorage["nanobot-webui.sidebar"]`；主题写入 `localStorage["nanobot-webui.theme"]`；认证 secret 写入 `localStorage["nanobot-bootstrap"]`。
- **内容宽度约束**：消息流容器 `max-w-[64rem]`，气泡列 `max-w-[49.5rem]`，Hero 欢迎区 `max-w-[58rem]`，设置页 `max-w-[1000px]`——确保大屏下文本行宽易读。
- **错误边界**：最外层用 [ErrorBoundary](file:///Users/shan/Downloads/nanobot/webui/src/components/ErrorBoundary.tsx) 托住整棵树，渲染异常时保留骨架并给出"重试"按钮，避免白屏。

### 1.1 顶层页面 / 视图一览

| 视图 key | 组件 | 触发入口 |
|---|---|---|
| `chat`（默认） | [ThreadShell](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/ThreadShell.tsx) | 点击会话列表项 / 新建对话 |
| `settings` | [SettingsView](file:///Users/shan/Downloads/nanobot/webui/src/components/settings/SettingsView.tsx) | Header 右上角齿轮 |
| `auth` | `AuthForm`（App.tsx 内置） | Token 未就绪或过期 |
| `loading` | 内联 loading | Bootstrap 中 |

> HUD / Reports / CMDB 等 Secbot 专属视图在架构上可扩展，但当前 `ShellView` 只定义了 `"chat" | "settings"` 两种值，尚未接入其它视图入口。

---

## 2. 侧边栏（Sidebar / Menu）

文件：[webui/src/components/Sidebar.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/Sidebar.tsx)

侧栏自上而下的功能分区：

| 区域 | 内容 | 说明 |
|---|---|---|
| Logo 行 | `nanobot` Logo + 折叠按钮（`PanelLeftClose`） | 点击折叠回调 `onCollapse` 触发 Shell 收起侧栏 |
| 搜索框 | 圆角 pill 样式 `<input>`，左置 `Search` 图标 | 实时过滤 `sessions`，匹配字段：`preview / chatId / channel / key` |
| 新建对话 | `SquarePen` + "New Chat" ghost 按钮 | 调用 `onNewChat` → 后端创建 session → 自动选中 |
| 会话列表 | [ChatList](file:///Users/shan/Downloads/nanobot/webui/src/components/ChatList.tsx) | 按日期分组（今天 / 昨天 / 更早），项内含删除菜单 |
| 底部分隔线 | `Separator` | — |
| 连接状态 | [ConnectionBadge](file:///Users/shan/Downloads/nanobot/webui/src/components/ConnectionBadge.tsx) | 6 态：`idle / connecting / open / reconnecting / closed / error`，彩色小圆点 + 脉冲动效 |

### 2.1 折叠 / 抽屉行为

- **桌面端**：`desktopSidebarOpen` 控制 `width`，`0 ↔ 272px` 过渡；折叠时主区用 `hideSidebarToggleOnDesktop` 控制 Header 中"展开"按钮的可见性。
- **移动端**：`mobileSidebarOpen` 驱动 `<Sheet side="left">`；选择会话后自动关闭抽屉，避免遮挡正文。

### 2.2 主题 / 语言切换入口

- **主题切换**（深色/浅色）**不在**侧栏，而在 **ThreadHeader 右上角**：`Sun / Moon` 图标按钮，见 [ThreadHeader.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/ThreadHeader.tsx#L90-L103)。
- **语言切换**（i18next）通过 [LanguageSwitcher](file:///Users/shan/Downloads/nanobot/webui/src/components/LanguageSwitcher.tsx) 的 DropdownMenu 实现，目前挂在 Settings 区域（非侧栏）。

---

## 3. 主内容区（Panel / Content）

### 3.1 对话视图：ThreadShell

文件：[ThreadShell.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/ThreadShell.tsx)

三段式结构：

```
<section>
  <ThreadHeader />         ← 顶部条：侧栏切换 · 会话标题 · 主题/设置
  <ThreadViewport>         ← 滚动容器 + 消息区 + composer
    {messages.length
      ? <ThreadMessages />  ← 聊天主流
      : emptyState (Hero)}  ← 欢迎屏
    <composer />            ← sticky 底部，Thread 变体
  </ThreadViewport>
</section>
```

#### Header（[ThreadHeader](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/ThreadHeader.tsx)）

- 左：侧栏切换按钮（`Menu` / `PanelLeftOpen`）+ 会话标题（`truncate max-w-[min(60vw,32rem)]`）
- 右：主题 toggle（`Sun / Moon`） + 设置齿轮
- `minimal` 模式：无会话且非加载时，隐藏标题占位但保留操作按钮

#### Viewport（[ThreadViewport](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/ThreadViewport.tsx)）

- 自动吸底：用户滚到距底部 `< 48px` 视为 `atBottom`，新消息到达时自动 `scrollTo`；流式中用 `auto`，非流式用 `smooth`。
- "回到底部"悬浮按钮：离底时在右下方显现 `ArrowDown` 圆形按钮。
- 顶部遮罩：6px 高的 `gradient-to-b` 渐隐，避免滚动内容紧贴 Header。
- 自定义滚动条：`scrollbar-thin`（宽 1.5px，圆角），见 [globals.css](file:///Users/shan/Downloads/nanobot/webui/src/globals.css#L147-L159)。

#### 消息气泡（[MessageBubble](file:///Users/shan/Downloads/nanobot/webui/src/components/MessageBubble.tsx)）

三种渲染路径，由 `message.kind` 与 `role` 决定：

1. **user**：右对齐 pill，`bg-secondary/70 rounded-[18px]`，可带图片/文件附件。
2. **assistant**：裸 Markdown（无气泡），通过 [MarkdownTextRenderer](file:///Users/shan/Downloads/nanobot/webui/src/components/MarkdownTextRenderer.tsx) 渲染 GFM + 数学公式 (KaTeX) + 代码块 ([CodeBlock](file:///Users/shan/Downloads/nanobot/webui/src/components/CodeBlock.tsx)) + 复制按钮。
3. **trace（工具调用/思维链）**：`TraceGroup` 折叠组：
   - 标题行："Using N tool(s)" + 右侧 `ChevronRight` 旋转指示
   - 展开后按 `agentLabel` 分组 → `AgentToolGroup` → `ToolCallItem`（彩色状态点：绿=end / 红=error / 灰=pending）
   - 通过 `call_id` 对 start/end 事件去重

#### Hero 欢迎屏（无消息时）

在 [ThreadShell.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/ThreadShell.tsx) 内内联渲染：

- 居中标题 + 大号 `hero` 变体 Composer
- **快捷动作卡片**（6 个，见 `QUICK_ACTION_KEYS`）：Plan / Analyze / Brainstorm / Code / Summarize / More，带色彩化图标和 `hover:-translate-y-0.5` 浮起动效

#### Composer（[ThreadComposer](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/ThreadComposer.tsx)）

两种 variant，同一组件：

| 属性 | `hero` | `thread` |
|---|---|---|
| 最小高 | `min-h-[78px]` | `min-h-[50px]` |
| 圆角 | `rounded-[28px]` | `rounded-[22px]` |
| 附件按钮 | `h-9 w-9` | `h-7.5 w-7.5` |
| 位置 | 欢迎屏中部 | 消息区底部 sticky |

交互能力：

- **自动行高**：Textarea 随内容自动 grow，上限 260px。
- **发送**：Enter 发送；Shift+Enter 换行；中文输入法合成期间 (`isComposing`) 不触发发送。
- **斜杠命令**：输入以 `/` 开头且无空白时弹出 `SlashCommandPalette`（`absolute bottom-full`），命令来自 `/api/commands`；支持 `↑/↓` 导航，`Tab/Enter` 选中，`Esc` 关闭；最多展示 8 条。
- **图片附件**：`Plus` 按钮触发 `<input type="file">`；支持拖拽、粘贴（`useClipboardAndDrop`）。
- **Model Label**：Composer 内部右下显示当前活跃模型简称（取路径叶子段），由 `ClientProvider` 提供 `modelName`。
- **发送按钮**：`ArrowUp` 图标；`canSend = !disabled && !encoding && !hasErrors && (text || readyImages)`，否则灰化 disabled。

#### 附件管理（[useAttachedImages](file:///Users/shan/Downloads/nanobot/webui/src/hooks/useAttachedImages.ts)）

- 单条消息上限 4 张图（`MAX_IMAGES_PER_MESSAGE`），MIME 白名单：`png / jpeg / webp / gif`（SVG 因 XSS 风险被排除）。
- 三态生命周期：`encoding` → `ready` → `error`；编码走 Web Worker（`imageEncode`），超过尺寸自动 re-encode，编码中 chip 内显示 `Loader2` 旋转。
- `AttachmentChip` 视觉：缩略图 + 文件名（`truncate max-w-[14rem]`）+ 大小/错误文案 + `X` 删除按钮；错误态红色描边 `border-destructive/40`。
- 键盘 `Delete/Backspace` 删除焦点 chip，自动把焦点移到相邻 chip 或回 textarea。

#### HITL 确认卡（[AskUserPrompt](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/AskUserPrompt.tsx)）

当最近一条助手消息携带 `buttons: string[][]` 时，在 Composer 上方插入问询卡：

- `MessageSquareText` 图标 + 加粗问题文本
- 候选答案按钮（`sm:grid-cols-2` 网格），每个按钮 `variant="outline"`
- `Other...` 按钮展开内联 `<textarea>`，Enter 提交自定义答案
- 发送后清空并收起

#### 流式渲染可视化（[useNanobotStream](file:///Users/shan/Downloads/nanobot/webui/src/hooks/useNanobotStream.ts)）

| 事件 | UI 反应 |
|---|---|
| `delta` | 累积进当前 assistant 消息 `content`；首次到达时追加一条空助手消息 |
| 空消息 + streaming | `TypingDots` 三点跳动占位 |
| 流式中 | 文末 `StreamCursor` 闪烁光标 |
| `stream_end` | **不立即**清 `isStreaming`——设 1s 定时器等工具执行；期间收到任何事件会重置计时 |
| `turn_end` | 清 `isStreaming`，刷新会话列表 |
| 切换 chatId | 重置 messages、buffer、streamError、延时器 |

#### 流式错误（[StreamErrorNotice](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/StreamErrorNotice.tsx)）

- 目前主要覆盖 `message_too_big`（WS close code 1009）
- 横幅样式红色可关闭
- 文案走 i18n：`errors.messageTooBig.title/body`

### 3.2 设置视图：SettingsView

文件：[SettingsView.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/settings/SettingsView.tsx)

当前只有单一"General"区块（占位后续扩展 tab）：

| 字段 | 类型 | 说明 |
|---|---|---|
| Model | 文本输入 + "Fetch models" 按钮 + 下拉 | 点击按钮调 `/api/settings/models` 探测端点支持的模型 |
| Provider | 下拉 `auto` + 已配置 provider | 切换 provider 时同步更换 Base URL 与 key 的占位 |
| Base URL | 文本输入 | OpenAI 兼容端点 URL |
| API Key | 密码框 + 显示/隐藏 toggle | 三态：未动（掩码占位）/ 输入（发送新值）/ 清空（空串清除） |

关键实现要点：

- **Key 安全**：Key 通过请求头 `X-Settings-Api-Key` 传输，**不走 query 或 URL**，避免进日志。
- **错误容错**（见 [SettingsView.tsx L82-L105](file:///Users/shan/Downloads/nanobot/webui/src/components/settings/SettingsView.tsx#L82-L105)）：`fetchSettings` 失败时 `alert()` 通知 + **保留页面骨架**，在 body 展示 `Retry` / `Sign out`，杜绝白屏。
- **保存校验**：必填项全填 + 有 dirty 时保存按钮才可点；否则提示。
- **Sign out**：清本地 secret → 回到 `auth` 状态。

---

## 4. 右侧 / 辅助面板

当前实现**没有**独立的右侧详情面板。辅助信息全部以**内联卡片 / 折叠组 / 模态**形式呈现：

| 场景 | 呈现方式 |
|---|---|
| 工具调用详情 | 消息流内 `TraceGroup` 折叠树 |
| 思维链/子代理 | `AgentToolGroup` 按 `agentLabel` 分组 |
| 删除会话确认 | [DeleteConfirm](file:///Users/shan/Downloads/nanobot/webui/src/components/DeleteConfirm.tsx) `AlertDialog`（Radix），红色破坏性按钮 |
| 图片查看 | [ImageLightbox](file:///Users/shan/Downloads/nanobot/webui/src/components/ImageLightbox.tsx) 全屏 `DialogPrimitive`，支持 `← / →` 翻页、`Home/End` 跳首尾、相邻图预解码 |
| 移动端侧栏 | `Sheet`（同一组件，side=left） |
| 语言选择 | `DropdownMenu` |

> 未实现 Toast 组件；**所有可关闭/不可恢复错误统一走 `window.alert()`**（项目规则，见 [SettingsView.tsx L92-L97](file:///Users/shan/Downloads/nanobot/webui/src/components/settings/SettingsView.tsx#L92-L97)），这是 WebUI 的明确约定。

---

## 5. 核心交互逻辑

### 5.1 认证与启动

```
App 挂载
  ↓
loadSavedSecret()
  ├── 有 secret → fetchBootstrap() → {token, ws_path, model_name}
  │                 ├── 成功 → new NanobotClient → status = "ready"
  │                 └── 失败 → status = "auth", failed = true
  └── 无 secret → status = "auth"（展示 AuthForm）
```

- Bootstrap 失败（401/过期）→ 回到 `auth` 并提示。
- WebSocket 断线时 `onReauth` 回调会拉新 token 并 `updateUrl` + 重连；失败则登出回 `auth`。
- **本地开发免密**：支持将 secret 预存 localStorage 自动登录。

### 5.2 会话生命周期

- **创建**：Sidebar "New Chat" 或 Hero Composer 首发 → `onCreateChat()` → 后端返回 chatId → WebSocket `attach` → 切 view 到 chat。
- **选择**：点击会话项 → `setActiveKey` → [useSessionHistory](file:///Users/shan/Downloads/nanobot/webui/src/hooks/useSessions.ts) 拉取历史 → `useNanobotStream` 用初始消息重建状态；ThreadShell 内部维护 `messageCacheRef` 在 chat 切换时保留未持久化消息。
- **删除**：ChatList 菜单垃圾桶 → `DeleteConfirm` 确认 → `DELETE /api/sessions/{key}` → 若删的是当前会话，自动切邻近或设为 null。

### 5.3 消息发送全流程

```
Composer 输入
  → (校验: 非空 / 无 encoding / 无 error)
  → onSend(text, images?)
      ├── 若无 chatId → 先 createChat → pendingFirstRef 暂存 → chatId 就绪后补发
      └── 否则 WebSocket: {type: "message", chat_id, content, media}
  → 乐观追加 user 消息（带 data: 预览）
  → Composer 清空 + 重新获焦
  → 监听 delta / message / stream_end / turn_end
  → 完成后刷新 Sidebar 会话列表
```

### 5.4 连接状态 & 重连

- [NanobotClient](file:///Users/shan/Downloads/nanobot/webui/src/lib/nanobot-client.ts)：单例 WebSocket，多路复用多个 chatId（服务端在每条事件里带 `chat_id`）。
- 重连策略：指数退避，`maxBackoffMs = 15_000`，自动 re-attach 已知 chatId。
- UI 反馈：[ConnectionBadge](file:///Users/shan/Downloads/nanobot/webui/src/components/ConnectionBadge.tsx) 色彩语义（绿=open / 琥珀=connecting+reconnecting+脉冲 / 红=error+脉冲 / 灰=idle+closed），`aria-live="polite"` 做无障碍播报。

### 5.5 键盘与手势规范

| 场景 | 快捷键 |
|---|---|
| 发送消息 | `Enter` |
| 换行 | `Shift + Enter` |
| 取消斜杠菜单 | `Esc` |
| 斜杠命令导航 | `↑ / ↓` |
| 选中斜杠命令 | `Tab / Enter` |
| 删除焦点附件 chip | `Delete / Backspace` |
| Lightbox 翻页 | `← / →` |
| Lightbox 首尾 | `Home / End` |
| Lightbox 关闭 | `Esc` |

拖拽 & 粘贴：Composer 支持文件拖入（`onDragEnter/Over/Leave/Drop` + `ring` 高亮）和 `Ctrl/Cmd+V` 粘贴图片。

### 5.6 错误与反馈矩阵

| 场景 | 反馈方式 | 位置 |
|---|---|---|
| 认证失败 | AuthForm 顶部红字 | 认证页 |
| WS 断线/重连 | ConnectionBadge 颜色+脉冲 | 侧栏底 |
| 消息过大 | StreamErrorNotice 横幅（可关闭） | Composer 上方 |
| 附件 MIME/尺寸错 | 附件 chip 内联错误文案 | Composer |
| 设置加载失败 | `alert()` + 页内 Retry/Sign out | 设置页 |
| 保存失败 | `alert()` | 设置页 |
| 渲染异常 | ErrorBoundary 红框 + Retry | 全局兜底 |
| 高危确认 (HITL) | AskUserPrompt 问询卡 | 消息底部 |
| 删除前确认 | AlertDialog | 模态 |

---

## 6. 设计体系

### 6.1 基础库

- **UI 原语**：[Radix UI](https://www.radix-ui.com/) — `@radix-ui/react-{alert-dialog,dialog,dropdown-menu,scroll-area,separator,tabs,tooltip,slot,avatar}`
- **组件层**：shadcn/ui 风格封装在 `webui/src/components/ui/`（如 [button.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/ui/button.tsx)、`sheet.tsx`、`alert-dialog.tsx`）
- **图标**：[lucide-react](https://lucide.dev)
- **Markdown/数学**：`react-markdown` + `remark-gfm` + `remark-math` + `rehype-katex` + `react-syntax-highlighter`
- **工具**：`class-variance-authority`、`clsx`、`tailwind-merge`（`cn()` 工具函数）

### 6.2 设计 Token（[globals.css](file:///Users/shan/Downloads/nanobot/webui/src/globals.css)）

- **亮色**（`:root`）：基于 shadcn 中性色，背景白、前景深灰 `240 3% 12%`、primary 深蓝灰。
- **暗色**（`.dark`）：背景近黑、前景近白、primary 近白。
- **Secbot 主题**（`[data-theme="secbot"]`）：
  - 背景 `#0A0B10`，前景 `#E6E8EE`，primary `#1E90FF` (Dodger Blue)
  - 漏洞等级色板：critical `#FF4D4F` / high `#FF8A3D` / medium `#FACC15` / low `#3FB6FF` / info `#9AA0AC`（可经 `bg-severity-critical` 等 Tailwind 类直接使用，见 [tailwind.config.js L85-L91](file:///Users/shan/Downloads/nanobot/webui/tailwind.config.js#L85-L91)）
- **侧栏独立色板**：`--sidebar / --sidebar-accent / --sidebar-border`，与主背景区分的微微更浅/更深灰度。
- **圆角**：`--radius: 0.4375rem`，再派生 `lg/md/sm`。

### 6.3 字体与排版

- 字体栈：系统字体优先，按序 fallback 到 PingFang SC / Noto Sans SC / Microsoft YaHei（CJK 友好），等宽 JetBrains Mono → Fira Code → Menlo。
- **CJK 行高**：默认 `--cjk-line-height: 1.625`；当 `:lang(zh)` / `:lang(ja)` / `:lang(ko)` 命中时自动提升到 `1.8`，并在消息 `p` 与 Markdown 容器中引用，避免中文字符行距过紧。

### 6.4 动效规范

- 进入动画：`animate-in fade-in-0 slide-in-from-bottom-1 duration-300`（消息、Hero）
- 下拉 / 抽屉：Radix 的 `data-[state=open/closed]:animate-in/out` + `slide-in-from-*` / `fade-in-0`
- 侧栏折叠：`transition-[width] duration-300 ease-out`
- 悬浮按钮：`hover:-translate-y-0.5`
- **Motion 降级**：所有 loading/缩放类一律带 `motion-reduce:*` 关闭，尊重系统 `prefers-reduced-motion`（见 AttachmentChip、ImageLightbox、SlashCommandPalette）。

### 6.5 i18n

- 语言切换走 i18next（`react-i18next`），key 见 [src/i18n/](file:///Users/shan/Downloads/nanobot/webui/src/i18n)。
- 几乎所有 UI 文案均走 `t(...)`；硬编码极少（如 ErrorBoundary 的中英双语兜底文案）。

---

## 7. 关键文件索引

| 分类 | 文件 | 职责 |
|---|---|---|
| **入口** | [main.tsx](file:///Users/shan/Downloads/nanobot/webui/src/main.tsx) | React DOM 挂载 |
| | [App.tsx](file:///Users/shan/Downloads/nanobot/webui/src/App.tsx) | 顶层 Shell、认证、会话管理、视图切换 |
| | [globals.css](file:///Users/shan/Downloads/nanobot/webui/src/globals.css) | 设计 token、主题变量、全局排版 |
| | [tailwind.config.js](file:///Users/shan/Downloads/nanobot/webui/tailwind.config.js) | 色板 / 字体 / 动画扩展 |
| **布局骨架** | [components/Sidebar.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/Sidebar.tsx) | 左侧栏（Logo / 搜索 / 新建 / 列表 / 连接徽章） |
| | [components/ChatList.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/ChatList.tsx) | 会话列表、日期分组、删除菜单 |
| | [components/thread/ThreadShell.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/ThreadShell.tsx) | 对话壳、Hero 欢迎、快捷动作 |
| | [components/thread/ThreadHeader.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/ThreadHeader.tsx) | 顶部条、主题/设置按钮 |
| | [components/thread/ThreadViewport.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/ThreadViewport.tsx) | 滚动 viewport、吸底、回到底部按钮 |
| | [components/thread/ThreadMessages.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/ThreadMessages.tsx) | 消息列表外壳 |
| | [components/thread/ThreadComposer.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/ThreadComposer.tsx) | 输入框、斜杠命令、附件、模型标签 |
| | [components/thread/AskUserPrompt.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/AskUserPrompt.tsx) | HITL 问询卡 |
| | [components/thread/StreamErrorNotice.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/thread/StreamErrorNotice.tsx) | 传输级错误横幅 |
| | [components/settings/SettingsView.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/settings/SettingsView.tsx) | 设置页（模型/Provider/BaseURL/Key） |
| **反馈组件** | [components/ConnectionBadge.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/ConnectionBadge.tsx) | WS 连接状态徽章 |
| | [components/DeleteConfirm.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/DeleteConfirm.tsx) | 删除确认对话框 |
| | [components/ImageLightbox.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/ImageLightbox.tsx) | 图片灯箱 |
| | [components/ErrorBoundary.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/ErrorBoundary.tsx) | 顶层错误边界 |
| | [components/LanguageSwitcher.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/LanguageSwitcher.tsx) | 语言切换下拉 |
| **内容呈现** | [components/MessageBubble.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/MessageBubble.tsx) | 用户/助手/trace 气泡、思维链 |
| | [components/MarkdownText.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/MarkdownText.tsx) | Markdown 入口（懒加载） |
| | [components/MarkdownTextRenderer.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/MarkdownTextRenderer.tsx) | GFM + math + 代码高亮实现 |
| | [components/CodeBlock.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/CodeBlock.tsx) | 代码块 + 语法高亮 + 复制 |
| **状态/通信** | [providers/ClientProvider.tsx](file:///Users/shan/Downloads/nanobot/webui/src/providers/ClientProvider.tsx) | WS 客户端 + token + 模型名 Context |
| | [lib/nanobot-client.ts](file:///Users/shan/Downloads/nanobot/webui/src/lib/nanobot-client.ts) | WS 多路复用客户端、重连、错误广播 |
| | [lib/api.ts](file:///Users/shan/Downloads/nanobot/webui/src/lib/api.ts) | REST 端点封装（sessions / settings / commands） |
| | [lib/bootstrap.ts](file:///Users/shan/Downloads/nanobot/webui/src/lib/bootstrap.ts) | 认证 bootstrap + secret 持久化 |
| | [lib/types.ts](file:///Users/shan/Downloads/nanobot/webui/src/lib/types.ts) | UIMessage / ChatSummary / 事件类型 |
| | [hooks/useTheme.ts](file:///Users/shan/Downloads/nanobot/webui/src/hooks/useTheme.ts) | 主题管理 + localStorage |
| | [hooks/useSessions.ts](file:///Users/shan/Downloads/nanobot/webui/src/hooks/useSessions.ts) | 会话列表 + 历史消息 |
| | [hooks/useNanobotStream.ts](file:///Users/shan/Downloads/nanobot/webui/src/hooks/useNanobotStream.ts) | 订阅 chat、累积 delta、发送消息 |
| | [hooks/useAttachedImages.ts](file:///Users/shan/Downloads/nanobot/webui/src/hooks/useAttachedImages.ts) | 附件生命周期（编码/错误/上限） |

---

## 8. 扩展建议（给未来的 HUD / CMDB / Reports 视图）

1. **新增视图类型**：将 `ShellView` 从 `"chat" | "settings"` 扩展为联合类型（如 `"hud" | "reports" | "assets"`），在 Sidebar 中增加分组区（如 "Workspaces"、"Operations"），保持侧栏骨架不变。
2. **复用 Token**：Secbot 专属页面应继续使用 `[data-theme="secbot"]` 下的 severity 调色板（`bg-severity-critical` 等），不要引入新的临时色值。
3. **保持错误规范**：所有错误继续走 `alert()` + 内联 Retry，而非 Toast，与现有 [SettingsView](file:///Users/shan/Downloads/nanobot/webui/src/components/settings/SettingsView.tsx) 的 `loadError` 模式对齐。
4. **右侧面板模式**：若需要，可在 `ThreadShell` 的 `<section>` 内增加 flex 子项作为可折叠详情列（参考 Composer sticky 的布局思路），优先使用 `Sheet side="right"` 在移动端展现。
5. **运动可达性**：新组件沿用 `motion-reduce:*` 规范，遵循 [globals.css](file:///Users/shan/Downloads/nanobot/webui/src/globals.css) 里 CJK 行高和 `scrollbar-thin` 工具类。
