# Frontend Architecture

> Authoritative architecture reference for `webui/src/`. Generated from the confirmed template (`VITE_UIUX_TEMPLATE=true`).

---

## 1. Technology Stack

| Layer | Choice | Version |
|-------|--------|---------|
| Framework | React | 18.x |
| Language | TypeScript (strict) | 5.x |
| Build | Vite | 6.x |
| CSS | Tailwind CSS | 3.x |
| Component library | shadcn/ui | — |
| Routing | react-router-dom | 7.x |
| i18n | i18next + react-i18next | — |
| Icons | lucide-react | — |
| Charts | recharts | — |
| Graph viz | react-flow | — |

---

## 2. Route Map

All routes defined in `App.tsx`. Protected routes require a valid bootstrap token.

| Path | Page Component | Description |
|------|---------------|-------------|
| `/login` | `LoginPage` | Bootstrap secret entry (unauthenticated) |
| `/` | `HomePage` | Chat surface: `Shell` + `RightRail` (Blackboard / PromptSuggestions) |
| `/sessions` | `SessionsPage` | Structured session table with filters (status, type, date range, text search) |
| `/session/:key` | `SessionDetailPage` | Single session detail: KPI cards, findings rollup, timeline, message replay, reports |
| `/dashboard` | `DashboardPage` | Asset/vuln analytics: charts, risk topology, summary cards |
| `/dashboard/phishing` | `PhishingDetailPage` | Phishing detection analytics |
| `/dashboard/log-analysis` | `LogAnalysisDetailPage` | Log analysis detection analytics |
| `/tasks/:id` | `TaskDetailPage` | Expert-agent task detail |
| `/workflows` | `WorkflowListPage` | Workflow builder list (gated by `WORKFLOW_BUILDER_ENABLED`) |
| `/workflows/:id` | `WorkflowDetailPage` | Workflow editor + run history |
| `/settings` | `SettingsPage` | Model, provider, API key, language, theme |

**Feature flags:**
- `VITE_UIUX_TEMPLATE` (default `true`): template-mode router path vs legacy in-app view switching.
- `WORKFLOW_BUILDER_ENABLED` (from `workflow-client.ts`): gates `/workflows` routes.

---

## 3. Component Tree

### 3.1 Page-level layout

```
App
├── BrowserRouter
│   ├── LoginPage (unauthenticated)
│   └── ProtectedRoute
│       └── ClientProvider
│           ├── HomePage
│           │   ├── Navbar (global header)
│           │   └── Shell (chat surface)
│           │       ├── ThreadShell (empty state / active chat)
│           │       │   ├── ScanQuickStart (hero: input + scenarios + assetSlot)
│           │       │   │   └── AssetAutoManagementSwitch (compact)
│           │       │   └── ThreadViewport
│           │       │       ├── ThreadMessages → MessageBubble
│           │       │       └── ThreadComposer
│           │       └── RightRail (xl: sidebar)
│           │           ├── BlackboardPanel
│           │           └── PromptSuggestions
│           ├── SessionsPage
│           │   ├── Navbar
│           │   └── Table (SessionRow[])
│           ├── SessionDetailPage
│           │   ├── Navbar
│           │   ├── KPI cards
│           │   ├── Findings section
│           │   ├── SessionTimeline
│           │   ├── Message replay (MessageBubble[])
│           │   └── Reports panel
│           ├── DashboardPage
│           ├── SettingsPage
│           └── Workflow*Page
```

### 3.2 Core component inventory

| Component | File | Lines | Responsibility |
|-----------|------|-------|---------------|
| `Shell` | `components/Shell.tsx` | 244 | Chat orchestrator: session management, sidebar, streaming |
| `ThreadShell` | `components/thread/ThreadShell.tsx` | 323 | Empty-state hero / active thread container |
| `ThreadViewport` | `components/thread/ThreadViewport.tsx` | 203 | Scroll management, message list + composer layout |
| `ThreadComposer` | `components/thread/ThreadComposer.tsx` | 490 | Rich input: slash commands, attachments, send/stop |
| `ThreadMessages` | `components/thread/ThreadMessages.tsx` | 50 | Virtual message list wrapper |
| `MessageBubble` | `components/MessageBubble.tsx` | 523 | Single message rendering: text, tool-calls, media, agent events |
| `ScanQuickStart` | `components/ScanQuickStart.tsx` | 229 | Hero: target input, scenario cards, assetSlot |
| `Navbar` | `components/Navbar.tsx` | 170 | Global nav: logo, links, WS status, notifications |
| `SessionsPage` | `pages/SessionsPage.tsx` | 647 | Session table with filters, batch delete, report download |
| `SessionDetailPage` | `pages/SessionDetailPage.tsx` | 1280 | Session detail: KPI, findings, timeline, messages, reports |
| `DashboardPage` | `pages/DashboardPage.tsx` | 240 | Dashboard hub with chart cards |
| `SettingsPage` | `pages/SettingsPage.tsx` | 296 | Model/provider settings, theme, language, logout |

### 3.3 Thread subsystem

| Component | Purpose |
|-----------|---------|
| `ThreadShell` | Container: hero (ScanQuickStart) ↔ active thread (ThreadViewport) |
| `ThreadViewport` | Scroll container + message list + composer |
| `ThreadMessages` | Maps `UIMessage[]` → `MessageBubble` |
| `ThreadComposer` | Input area: text, slash commands (`SlashCommandPalette`), attachments (`AttachmentChip`), send/stop |
| `ThreadHeader` | Active session header: title, connection badge, actions |
| `AskUserPrompt` | Blocking prompt card for `ask_user` / `request_approval` |
| `StreamErrorNotice` | Inline error banner for `message_too_big` / `llm_retry` |
| `SlashCommandPalette` | `/command` autocomplete dropdown |
| `AttachmentChip` | Attached file/image preview chip |

### 3.4 Message rendering

| Component | Purpose |
|-----------|---------|
| `MessageBubble` | Main bubble: user/assistant/tool, markdown, images, tool-call groups |
| `CodeBlock` | Syntax-highlighted code with copy button |
| `AgentEventCard` | Inline card for `agent_event` (thought, subagent lifecycle, blackboard) |
| `ToolCallCard` | Single tool-call: name, args, status badge, duration |
| `ToolCallGroup` | Groups multiple tool-calls within one assistant bubble |
| `ImageLightbox` | Full-screen image preview |

### 3.5 Right Rail (xl: sidebar panels)

| Component | Purpose |
|-----------|---------|
| `RightRail` | Tabbed sidebar: Blackboard (default) + PromptSuggestions |
| `BlackboardPanel` | Live blackboard entries per chat (REST + WS) |
| `PromptSuggestions` | Quick prompt cards from `/api/prompts` |
| `AgentStatusPanel` | Expert-agent runtime status chips |
| `AssetsPanel` | Per-chat asset feed (REST + WS) |

---

## 4. Hooks (State Management)

### 4.1 Core hooks

| Hook | File | Purpose |
|------|------|---------|
| `useSessions` | `hooks/useSessions.ts` | Sidebar session list: CRUD, optimistic insert |
| `useSessionHistory` | `hooks/useSessions.ts` | Lazy-load persisted messages for a session key |
| `useNanobotStream` | `hooks/useNanobotStream.ts` | WebSocket stream: delta/message/turn_end → UIMessage[] |
| `useSessionsList` | `hooks/useSessionsList.ts` | Structured session table data (SessionRow[]) |
| `useReports` | `hooks/useReports.ts` | Report artefacts per session |
| `useActivityStream` | `hooks/useActivityStream.ts` | Activity event stream (REST + WS merge) |
| `useAgents` | `hooks/useAgents.ts` | Expert-agent registry with runtime status |
| `useNotifications` | `hooks/useNotifications.ts` | Notification center: list, read, mark-all |
| `useUnreadCount` | `hooks/useUnreadCount.ts` | Global unread badge count |
| `useAttachedImages` | `hooks/useAttachedImages.ts` | Image attachment state: paste, drop, file picker |
| `useClipboardAndDrop` | `hooks/useClipboardAndDrop.ts` | Clipboard paste + drag-drop for images/files |
| `useTheme` | `hooks/useTheme.ts` | Dark/light theme toggle, system preference |

### 4.2 Data flow

```
Bootstrap → ClientProvider (client, token, modelName)
                │
                ├── useSessions (sidebar list) ← REST /api/sessions
                ├── useNanobotStream ← WS events → UIMessage[]
                ├── useSessionHistory ← REST /api/sessions/{key}/messages
                ├── useActivityStream ← REST /api/events + WS activity_event
                ├── useNotifications ← REST /api/notifications
                ├── useUnreadCount ← derived from useNotifications
                └── useAgents ← REST /api/agents?include_status=true
```

---

## 5. API Client Layer

| Module | Transport | Purpose |
|--------|-----------|---------|
| `lib/api.ts` | REST (fetch) | Sessions, settings, notifications, events, agents, skills, blackboard, assets, dashboard |
| `lib/secbot-client.ts` | WebSocket | Chat streaming: connect, attach, send, stop, newChat, scan.user_reply |
| `lib/workflow-client.ts` | REST (fetch) | Workflow CRUD, run, cancel, schedule |
| `lib/phishing-client.ts` | REST (fetch) | Phishing dashboard data |
| `lib/log-analysis-client.ts` | REST (fetch) | Log analysis dashboard data |
| `lib/bootstrap.ts` | REST (fetch) | `/webui/bootstrap` — token + WS path + model name |

### 5.1 Auth flow

1. `App.tsx` calls `fetchBootstrap(secret)` → `{token, ws_path, model_name}`
2. `SecbotClient` connects via WebSocket with `?token=...`
3. REST calls use `Bearer ${token}` header
4. On 401, `api.ts` auto-refreshes via `_refreshToken()` → `fetchBootstrap(savedSecret)`
5. On WS close, `SecbotClient.scheduleReconnect()` calls `onReauth()` for token refresh

---

## 6. Type System

Central type definitions in `lib/types.ts` (633 lines):

| Type Group | Key Types |
|------------|-----------|
| Messages | `UIMessage`, `Role`, `MessageKind`, `UIImage`, `UIMediaAttachment` |
| Streaming | `InboundEvent` (8 variants), `Outbound` (5 variants), `ConnectionStatus` |
| Agent events | `AgentEventPayload`, `AgentEventType` (14 types), `ToolCallStatus` |
| Sessions | `ChatSummary`, `SessionRow`, `SessionFindingsRollup`, `SessionTokenRollup`, `ReportRow` |
| Scan | `ScanType` ("full"/"vuln"/"weakpwd"/"asset"/"query"), `SessionStatus` |
| Assets | `AssetEntry`, `AssetKind`, `AssetAutoManagementState`, `AssetRiskTopologyResponse` |
| Notifications | `Notification`, `NotificationKind`, `NotificationListResponse` |
| Activity | `ActivityEvent`, `ActivityLevel`, `ActivitySource`, `ActivityCategory` |
| Settings | `SettingsPayload`, `SettingsUpdate`, `SlashCommand` |
| Bootstrap | `BootstrapResponse` |

---

## 7. i18n

- **Library**: i18next + react-i18next
- **Languages**: `zh-CN` (default), `en`
- **Locale files**: `src/i18n/locales/{zh-CN,en}/common.json`
- **Usage**: `t("key.path", { defaultValue: "fallback" })`
- **Language switching**: `LanguageSwitcher` component in Settings

---

## 8. Build & Dev

| Command | Purpose |
|---------|---------|
| `bun install` | Install dependencies |
| `bun dev` | Dev server (Vite :5173) |
| `bun run build` | Production build |
| `bun run lint` | ESLint (max-warnings 0) |
| `npx tsc --noEmit` | Type check |
| `bun test` | Vitest |

---

## 9. Directory Structure

```
webui/src/
├── components/           # UI components
│   ├── thread/           # Thread subsystem (ThreadShell, ThreadViewport, etc.)
│   ├── message/          # Message rendering (AgentEventCard, ToolCallCard, ToolCallGroup)
│   ├── agents/           # Agent editor views
│   ├── dashboard/        # Dashboard visualization (AssetRiskTopology)
│   ├── settings/         # Settings views
│   ├── workflow/         # Workflow builder components
│   └── ui/               # shadcn/ui primitives (button, card, dialog, etc.)
├── pages/                # Route page components
│   ├── dashboard/        # Dashboard chart options
│   ├── phishing/         # Phishing page components
│   └── workflow/         # Workflow page components
├── hooks/                # React hooks (state management)
├── lib/                  # Core libraries
│   ├── api.ts            # REST API client
│   ├── secbot-client.ts  # WebSocket client
│   ├── workflow-client.ts# Workflow REST client
│   ├── types.ts          # TypeScript type definitions
│   ├── bootstrap.ts      # Auth bootstrap
│   ├── format.ts         # Formatting utilities
│   ├── utils.ts          # General utilities (cn, etc.)
│   └── parsers/          # File parsers (docx, eml, xlsx, txt)
├── i18n/                 # Internationalization
│   ├── config.ts         # i18next config
│   └── locales/          # Translation files
├── data/mock/            # Mock data for dashboard
├── providers/            # React context providers
├── tests/                # Vitest test files
└── workers/              # Web Workers (image encoding)
```

---

## 10. Key Design Patterns

1. **Slot pattern**: `ScanQuickStart.assetSlot` accepts `React.ReactNode` for flexible composition.
2. **Compact variant**: `AssetAutoManagementSwitch.compact` toggles between full-width and inline layouts.
3. **Conditional rendering by ScanType**: `isQuery = row.scanType === "query"` in SessionDetailPage controls KPI cards, findings section, and timeline labels.
4. **Optimistic updates**: `useSessions.createChat()` inserts a session optimistically before server confirmation.
5. **Token refresh dedup**: `api.ts` uses a shared `_refreshPromise` to collapse concurrent 401s into one bootstrap call.
6. **WS reconnect with reauth**: `SecbotClient` exponential backoff + `onReauth` callback for transparent token refresh.
7. **Activity event merge**: `useActivityStream` normalizes REST (`ActivityEvent`) and WS (`ActivityEventFrame`) into a unified list with dedup by derived `id`.
