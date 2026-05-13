# UI-UX 建设模板（海盾漏洞检测智能体管控台）

> 本文档提炼自 `webui/`（漏洞检测智能体前端）的全部内容、功能与风格，是一份**可直接复制到其他项目**的"前端替换模板"。落地步骤分为 4 步：(1) 复制依赖与配置 → (2) 复制设计令牌 → (3) 套用骨架页面 → (4) 按业务替换组件内容。

---

## 0. 一图速览

- **风格关键词**：暗色（Dark-only）、玻璃拟态、海蓝渐变发光、海洋（Ocean）色板、扁平卡片 + 4px 左侧色条强调、微动效、Lucide 单色图标、紧凑信息密度。
- **页面骨架**：`Sticky Navbar (h-16, backdrop-blur)` + `<main class="container py-6 space-y-6">` + `Card 网格`。
- **典型页面**：登录页（居中卡）、对话首页（左工具栏 + 右聊天）、大屏分析（KPI + ECharts + 列表）、任务详情（信息卡 + 实时流 + 表格）、各类后台管理页（顶栏 + 单卡片表格 + 模态框）。
- **交互特征**：SSE/轮询 + 乐观更新；管理操作走"打开模态框 → 二次确认"；表单错误内联（FastAPI 422 → field-level）。

---

## 1. 技术栈与依赖

### 1.1 运行时

| 类别 | 选择 | 备注 |
| --- | --- | --- |
| 构建 | **Vite 6** + `@vitejs/plugin-react` | 别名 `@` → `./src` |
| 框架 | **React 18.3** + TypeScript 5.6 | `React.StrictMode` |
| 路由 | **React Router 7** | `BrowserRouter` + `<ProtectedRoute>` 包裹 |
| 样式 | **Tailwind CSS 3.4** + `tailwindcss-animate` + `autoprefixer` | `darkMode: ['class']`，但项目实际只跑暗色 |
| 组件原语 | **shadcn/ui 风格自建** (`cva` + `clsx` + `tailwind-merge`) | 不引入完整 shadcn，仅复制 5 个原子 |
| 图标 | **lucide-react** | 单色线性，统一 `h-4 w-4` / `h-3.5 w-3.5` |
| 通知 | **sonner** | `<Toaster position="bottom-right" richColors closeButton />` |
| 图表 | **echarts** + **echarts-for-react** | 折线 + 区域填充，`renderer:'svg'` |
| 长列表 | **react-virtuoso** | 实时日志虚拟滚动 |

### 1.2 测试

- `vitest` + `@testing-library/react` + `jsdom` + `msw`（API mock）。

### 1.3 `package.json` 关键依赖（直接拷贝）

```json
{
  "dependencies": {
    "class-variance-authority": "^0.7.1",
    "clsx": "^2.1.1",
    "echarts": "^5.5.0",
    "echarts-for-react": "^3.0.2",
    "lucide-react": "^0.468.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^7.1.1",
    "react-virtuoso": "^4.18.6",
    "sonner": "^2.0.7",
    "tailwind-merge": "^2.6.0",
    "tailwindcss-animate": "^1.0.7"
  }
}
```

---

## 2. 目录结构

```
webui/
├── index.html               # zh-CN，#root 容器，标题/描述
├── vite.config.ts           # @ 别名
├── tailwind.config.ts       # 设计令牌 + 动画
├── postcss.config.js        # tailwindcss + autoprefixer
└── src/
    ├── main.tsx             # 入口：StrictMode + BrowserRouter + App
    ├── index.css            # 全局：字体、HSL 变量、utilities、滚动条
    ├── App.tsx              # Routes + Toaster + ProtectedRoute
    ├── lib/
    │   ├── api.ts           # 统一 _fetch、ApiError、SSE、401 重定向
    │   ├── auth.ts          # localStorage token、fetchMe
    │   ├── constants.ts     # API_BASE_URL、轮询/重试常量
    │   ├── defaults.ts      # 兜底配置
    │   └── utils.ts         # cn() 合并 className
    ├── components/
    │   ├── ui/              # 原子：button / card / badge / input / textarea
    │   ├── Navbar.tsx       # 顶栏 + 角色感知菜单
    │   ├── StatusCards.tsx  # KPI 三卡
    │   ├── ChatMessage.tsx  # 对话气泡 + 徽章组
    │   ├── PromptSuggestions.tsx
    │   ├── TaskStatusBadge.tsx
    │   ├── LogViewer.tsx    # Virtuoso 实时日志
    │   ├── FindingStream.tsx
    │   └── YoloExpiredToast.tsx
    ├── pages/
    │   ├── LoginPage.tsx
    │   ├── HomePage.tsx
    │   ├── DashboardPage.tsx
    │   ├── TaskDetailPage.tsx
    │   ├── WhitelistsPage.tsx
    │   ├── PlatformSettingsPage.tsx
    │   └── admin/{EngineResources,AuditLogPage}.tsx
    ├── hooks/               # 业务 hooks：useTask、useTaskEvents、usePlatformConfig…
    ├── types/               # 与后端契约一致（snake_case 字段保持）
    └── data/                # 静态/兜底数据
```

---

## 3. 设计令牌（Design Tokens）

### 3.1 CSS 变量（暗色主题）— `src/index.css`

```css
:root {
  --background: 222 47% 6%;          /* 深海蓝近黑 */
  --foreground: 210 40% 96%;         /* 高亮文字 */
  --card: 222 47% 8%;
  --card-foreground: 210 40% 96%;
  --popover: 222 47% 8%;
  --popover-foreground: 210 40% 96%;
  --primary: 189 94% 43%;            /* 青蓝主色（cyan-500 风） */
  --primary-foreground: 222 47% 6%;
  --secondary: 217 33% 17%;
  --secondary-foreground: 210 40% 96%;
  --muted: 217 33% 17%;
  --muted-foreground: 215 20% 65%;
  --accent: 217 33% 17%;
  --accent-foreground: 210 40% 96%;
  --destructive: 0 84% 60%;
  --destructive-foreground: 210 40% 98%;
  --border: 217 33% 17%;
  --input: 217 33% 17%;
  --ring: 189 94% 43%;
  --radius: 0.75rem;                 /* 全局 12px 圆角基线 */

  --gradient-primary: linear-gradient(135deg, hsl(189 94% 43%), hsl(199 89% 48%));
  --gradient-subtle:  linear-gradient(180deg, hsl(222 47% 6%), hsl(222 47% 10%));
  --gradient-card:    linear-gradient(145deg, hsl(222 47% 10%), hsl(222 47% 7%));
  --shadow-elegant:   0 10px 30px -10px hsl(189 94% 43% / 0.25);
  --shadow-glow:      0 0 40px hsl(189 94% 43% / 0.3);
  --transition-smooth: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
```

### 3.2 全局基线

```css
body {
  @apply bg-background text-foreground antialiased;
  font-family: 'Inter', 'Noto Sans SC', system-ui, sans-serif;
  background: var(--gradient-subtle);
  min-height: 100vh;
}
::selection { background: hsl(var(--primary) / 0.3); color: hsl(var(--foreground)); }
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-thumb { background: hsl(var(--muted)); border-radius: 3px; }
```

### 3.3 实用 utilities

```css
.text-gradient { background: var(--gradient-primary); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.bg-glass     { background: hsl(var(--card) / 0.7); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); }
.border-glow  { border: 1px solid hsl(var(--primary) / 0.2); box-shadow: var(--shadow-elegant); }
.hover-lift   { transition: var(--transition-smooth); }
.hover-lift:hover { transform: translateY(-2px); box-shadow: var(--shadow-glow); }
```

### 3.4 字体

通过 Google Fonts 在 `index.css` 顶部加载：

- 正文 / UI：`Inter` 300/400/500/600/700
- 中文：`Noto Sans SC` 300/400/500/700
- 等宽：`JetBrains Mono` 400/500（用于 ID、IP、时间戳、日志）

---

## 4. Tailwind 配置

```ts
// tailwind.config.ts
const config: Config = {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    container: { center: true, padding: '2rem', screens: { '2xl': '1400px' } },
    extend: {
      colors: {
        // 通过 CSS 变量绑定的语义色
        border: 'hsl(var(--border))', input: 'hsl(var(--input))', ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))', foreground: 'hsl(var(--foreground))',
        primary:     { DEFAULT: 'hsl(var(--primary))',     foreground: 'hsl(var(--primary-foreground))' },
        secondary:   { DEFAULT: 'hsl(var(--secondary))',   foreground: 'hsl(var(--secondary-foreground))' },
        destructive: { DEFAULT: 'hsl(var(--destructive))', foreground: 'hsl(var(--destructive-foreground))' },
        muted:       { DEFAULT: 'hsl(var(--muted))',       foreground: 'hsl(var(--muted-foreground))' },
        accent:      { DEFAULT: 'hsl(var(--accent))',      foreground: 'hsl(var(--accent-foreground))' },
        popover:     { DEFAULT: 'hsl(var(--popover))',     foreground: 'hsl(var(--popover-foreground))' },
        card:        { DEFAULT: 'hsl(var(--card))',        foreground: 'hsl(var(--card-foreground))' },
        // 行业拓展色板（按行业可改名：medical / fintech / iot…）
        ocean: { 50:'#f0f9ff',100:'#e0f2fe',200:'#bae6fd',300:'#7dd3fc',400:'#38bdf8',500:'#0ea5e9',600:'#0284c7',700:'#0369a1',800:'#075985',900:'#0c4a6e',950:'#082f49' },
        cyan:  { glow: '#22d3ee' },
        alert: { DEFAULT: '#f97316', foreground: '#fff7ed' },
      },
      borderRadius: { lg: 'var(--radius)', md: 'calc(var(--radius) - 2px)', sm: 'calc(var(--radius) - 4px)' },
      keyframes: {
        'accordion-down': { from: { height: '0' }, to: { height: 'var(--radix-accordion-content-height)' } },
        'accordion-up':   { from: { height: 'var(--radix-accordion-content-height)' }, to: { height: '0' } },
        'pulse-glow':     { '0%,100%': { boxShadow: '0 0 20px hsl(var(--primary) / 0.3)' }, '50%': { boxShadow: '0 0 40px hsl(var(--primary) / 0.6)' } },
        'fade-in-up':     { '0%': { opacity: '0', transform: 'translateY(12px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        'slide-in-right': { '0%': { opacity: '0', transform: 'translateX(20px)' }, '100%': { opacity: '1', transform: 'translateX(0)' } },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up':   'accordion-up 0.2s ease-out',
        'pulse-glow':     'pulse-glow 2s ease-in-out infinite',
        'fade-in-up':     'fade-in-up 0.5s ease-out forwards',
        'slide-in-right': 'slide-in-right 0.4s ease-out forwards',
      },
      fontFamily: {
        sans: ['"Inter"', '"Noto Sans SC"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
}
```

---

## 5. 原子组件（shadcn 极简变体）

> 全部位于 `src/components/ui/`，使用 `cva` 定义变体，搭配 `cn(...)` 合并类名。**这 5 个文件加起来不到 300 行**，是可移植性的核心。

### 5.1 `cn` 工具

```ts
// src/lib/utils.ts
import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)) }
```

### 5.2 Button（7 种变体）

```ts
// 关键变体：default / destructive / outline / secondary / ghost / link / glow
'default':     'bg-primary text-primary-foreground hover:bg-primary/90 shadow-lg shadow-primary/20'
'destructive': 'bg-destructive text-destructive-foreground hover:bg-destructive/90'
'outline':     'border border-input bg-background hover:bg-accent hover:text-accent-foreground'
'secondary':   'bg-secondary text-secondary-foreground hover:bg-secondary/80'
'ghost':       'hover:bg-accent hover:text-accent-foreground'
'link':        'text-primary underline-offset-4 hover:underline'
'glow':        'bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 hover:border-primary/50 shadow-[0_0_20px_rgba(14,165,233,0.15)]'
// 尺寸：default(h-10) / sm(h-9) / lg(h-11) / icon(h-10 w-10)
```

### 5.3 Card（玻璃拟态 + 发光边框）

```tsx
// 默认 className
'rounded-xl border bg-card text-card-foreground shadow-sm bg-glass border-glow'
// 子组件：CardHeader/CardTitle/CardDescription/CardContent/CardFooter，全部 p-6 内边距
```

### 5.4 Badge（7 种语义色）

```ts
default     // 主色填充
secondary   // 次级灰
destructive // 危险红
outline     // 描边
success     // 'bg-emerald-500/15 text-emerald-400'
warning     // 'bg-amber-500/15 text-amber-400'
alert       // 'bg-orange-500/15 text-orange-400'
```

### 5.5 Input / Textarea

```css
'flex h-10 w-full rounded-md border border-input bg-background/50 px-3 py-2 text-sm
 ring-offset-background placeholder:text-muted-foreground
 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring
 disabled:cursor-not-allowed disabled:opacity-50'
```

> Textarea 与之相同，`min-h-[80px] resize-none`。

---

## 6. 页面骨架（套用到任何业务页）

### 6.1 顶栏（Navbar Pattern）

所有"次级页面"复用同一段顶栏（粘性 + 半透明 + 模糊）：

```tsx
<header className="sticky top-0 z-50 w-full border-b border-border/50 bg-background/80 backdrop-blur-md">
  <div className="container flex h-16 items-center justify-between">
    <div className="flex items-center gap-3">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Shield className="h-5 w-5" />
      </div>
      <h1 className="text-base font-semibold tracking-tight text-foreground">页面标题</h1>
    </div>
    <Link to="/"><Button variant="secondary" size="sm"><ArrowLeft className="mr-1.5 h-3.5 w-3.5"/>返回</Button></Link>
  </div>
</header>
```

### 6.2 主内容区

```tsx
<main className="container py-6 space-y-6">
  {/* KPI 卡片网格 */}
  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4"> ... </div>
  {/* 主体两栏 */}
  <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <Card className="lg:col-span-2"> ... </Card>
    <Card> ... </Card>
  </div>
</main>
```

### 6.3 全局根

```tsx
// App.tsx
<Toaster position="bottom-right" richColors closeButton />
<Routes>
  <Route path="/login" element={<LoginPage />} />
  <Route path="/" element={<ProtectedRoute><HomePage /></ProtectedRoute>} />
  ...
</Routes>
```

---

## 7. 典型页面模板（拷贝 = 改文案就能跑）

### 7.1 登录页（居中卡片）

- 容器：`flex min-h-screen items-center justify-center bg-background p-6`
- 表单卡片：`w-full max-w-sm space-y-5 rounded-lg border border-border bg-card p-8 shadow-sm`
- 标题 + 副标题：`text-xl font-semibold` + `text-sm text-muted-foreground`
- 错误：`role="alert"` + `border-destructive/40 bg-destructive/10 text-destructive`
- 提交按钮：`<Loader2 className="animate-spin"/>` + 文案切换
- 重定向防护：`?next=` 仅允许相对路径（`startsWith('/') && !startsWith('//')`）

### 7.2 首页（对话型 智能体台）

- **左 1 / 右 3** 栅格：`grid grid-cols-1 lg:grid-cols-4 gap-6`
- 左栏：常用提示词 chips (`variant="glow"` 按钮) + 状态信息卡 (rounded-xl border bg-card/50)
- 右栏：高度固定的对话容器 `h-[600px] rounded-xl border bg-card/30 overflow-hidden`
  - 滚动区 `flex-1 overflow-y-auto p-5 space-y-5`
  - 输入区 `border-t bg-card/50 p-4`，`Textarea + Button(图标)`
- 行为：`Enter 发送 / Shift+Enter 换行`，提示文案以 `text-[10px] text-muted-foreground` 居中

### 7.3 大屏分析（KPI + ECharts + 列表）

- 顶部 6 列 KPI：`grid-cols-2 md:grid-cols-3 lg:grid-cols-6`，每卡 `<Card className="hover-lift"><CardContent className="p-4 flex gap-3">`
- 主图：`<ReactECharts opts={{ renderer: 'svg' }} style={{ height: 320 }} />`
  - **暗色 ECharts 配色**：`backgroundColor:'transparent'`、轴线 `#334155`、网格 `#1e293b`、文字 `#94a3b8`，工具提示 `rgba(15,23,42,0.9)`
  - 系列色：青 `#0ea5e9` / 橙 `#f97316` / 绿 `#10b981`，附 `linearGradient` 区域填充
- 子卡（最近报告、资产聚类）：`hover:bg-accent/30 transition-colors` 行 hover、`border-l-4 border-l-{color}` 等左侧色条强调

### 7.4 任务详情（信息 + 实时流 + 表格 + 报告）

- 顶栏内嵌 `TaskStatusBadge` + 实时心跳徽章（`animate-ping` 圆点）+ 操作按钮（启动 / 取消 / 刷新）
- 4 列信息卡：`grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4`
- 模块进度列表：每行 `border-border/40 rounded-lg p-3` + 状态徽章 + 时间区间
- 双栏实时流：`<LogViewer/>` + `<FindingStream/>`，固定 `h-[400px]`
- 表格：`w-full text-sm`，`thead text-xs text-muted-foreground border-b border-border/40`，行 `hover:bg-accent/30`

### 7.5 后台管理（白名单 / 引擎资源 / 平台设置 / 审计日志）

- 模式：**单卡 / 多卡 + 操作按钮 + 模态框**。
- 列表行：`flex items-center justify-between rounded-lg border border-border/40 p-4`
- 上传：隐藏 `<input type="file" className="hidden">` + `useRef` 触发，按钮文案随状态切换
- 角色门：`fetchMe()` → `role === 'admin'` 才挂载写表单；非 admin 渲染友好空态卡
- 表单错误：解析 FastAPI 422 `detail[].loc` → `{ fieldKey: msg }` 字典 → 字段下方红色文案
- 危险操作：先打开"激活/删除"确认模态，再调用 API
- 分页：`page / page_size`，"上一页/下一页" + `<ChevronLeft/Right>`

---

## 8. 动效与交互守则

| 场景 | 用法 |
| --- | --- |
| 卡片登场 | `animate-fade-in-up`（信息流、聊天气泡） |
| 侧边登场 | `animate-slide-in-right`（抽屉、Toast） |
| 强调脉冲 | `animate-pulse-glow`（YOLO 高危标识） |
| Loading | `<Loader2 className="animate-spin h-4 w-4" />` |
| 心跳 | `<span class="animate-ping ... bg-emerald-400 opacity-75" />` 套圆点 |
| Hover 抬升 | `hover-lift`（KPI / 报告卡） |
| Hover 着色 | `hover:bg-accent/20` 或 `/30`（列表行） |
| 过渡 | 统一 `transition-colors` 或 `transition: var(--transition-smooth)` |

**反模式**：禁止使用浓重投影、亮白背景、彩色按钮组合冲撞；禁止在暗背景上用纯白 (#fff) 文本（用 `text-foreground = 210 40% 96%`）。

---

## 9. 数据层模式

### 9.1 API 客户端（`lib/api.ts`）

- 单一 `_fetch<T>` 入口：自动注入 `Authorization: Bearer ${token}`、统一 `Content-Type: application/json`、统一 `ApiError` 抛出。
- 401 处理：`clearToken()` + `window.location.href = '/login?next=...'`，**login 提交可通过 `suppressRedirectOn401: true` 反向豁免**。
- 文件上传：单独 `_uploadMultipart`，**不要手动设置 `Content-Type`**（让浏览器写 boundary）。
- 下载：使用 `fetch` 拿 `Blob`，由调用方触发 `<a download>`。
- SSE：用 `fetch + ReadableStream`（而非 `EventSource`，因为需要带 Token），指数退避重连：`SSE_RETRY_BASE_MS=1000 → SSE_RETRY_MAX_MS=30000`。
- 错误形态：`ApiError { status, message, detail }`，422 时 `detail` 是数组用于字段映射。

### 9.2 鉴权（`lib/auth.ts`）

- Token 存 `localStorage['vapt_token']`（或换名）。
- `fetchMe()` 拉 `/auth/me` 校验角色；首次空帧避免登录页"闪一下"。
- `<ProtectedRoute>` 包裹保护路由，`status: 'checking' | 'ok' | 'denied'`。

### 9.3 自定义 Hooks 范式

- 每个资源一个 hook（`useTask`、`useTaskList`、`usePlatformConfig` …）。
- 统一返回 `{ data | items, loading, error, refresh, mutate }`。
- 长任务/列表：常量配置轮询周期 `TASK_LIST_POLL_MS=5000`、`TASK_DETAIL_POLL_MS=3000`。
- 失败兜底：`usePlatformConfig` 失败时返回 `DEFAULT_PLATFORM_CONFIG`，并 `toast.warning` 告警。

### 9.4 类型契约

- 与后端字段保持 **snake_case**，不做客户端命名转换。
- 提供 UI 派生类型 + 转换函数（如 `toUITask(t: TaskDetail): UITask`）。

---

## 10. 状态、空态、错误态三件套

每个数据卡都同时实现：

```tsx
{loading && !data && <Skeleton/>}                  // 骨架：h-[N] animate-pulse rounded-md bg-muted/30
{error && !data && <ErrorCard onRetry={refetch}/>} // 错误：role="alert" + AlertCircle + 重试按钮
{data && isEmpty(data) && <EmptyHint/>}            // 空态：图标 + 中文提示 + 引导动作
{data && !isEmpty(data) && <Render data={data}/>}  // 正常态
{loading && data && <OverlaySpinner/>}             // stale-while-revalidate：data 之上盖一层模糊 spinner
```

---

## 11. 文案 / 国际化 / 信息密度

- 全站中文，`<html lang="zh-CN">`。
- 文案风格：简洁、动词在前（"启动 / 取消 / 上传字典 / 激活"）。
- 状态用图标 + 中文（成功 ✓ / 失败 ✗ / 执行中 ⟳ / 已取消 / 部分成功 / 待执行）。
- 数字、ID、IP、时间 → `font-mono`；时间戳渲染 `toLocaleString('zh-CN')`。
- 信息密度：常规 `text-sm`、辅助 `text-xs` / `text-[10px]`；标题 `text-base` 不超过 `text-lg`。

---

## 12. 可访问性 & 键鼠

- 所有图标按钮加 `data-testid` 或 `aria-label`。
- 错误容器 `role="alert"`；Tab 行 `role="tab" aria-selected={active}`。
- 表单 `<label htmlFor>` 与 `<Input id>` 配对；`autoComplete` 正确填写（`username` / `current-password`）。
- 焦点环：所有可交互元素已配 `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2`。

---

## 13. 替换到其他项目的执行清单（Checklist）

> 假设你要把另一个项目的前端**整体替换**为本风格。

1. **拷贝基础设施**
   - [ ] `package.json` 中 `dependencies` + `devDependencies` 的 12 个包。
   - [ ] `vite.config.ts`、`postcss.config.js`、`tailwind.config.ts`、`tsconfig.*`。
   - [ ] `index.html`（改 `<title>` / `<meta description>` / favicon）。
2. **拷贝设计系统**
   - [ ] `src/index.css` 全文（保留字体 import、HSL 变量、utilities、滚动条）。
   - [ ] `src/lib/utils.ts`（`cn()`）。
   - [ ] `src/components/ui/{button,card,badge,input,textarea}.tsx` 全部 5 文件。
3. **拷贝骨架**
   - [ ] `src/main.tsx`（StrictMode + BrowserRouter）。
   - [ ] `src/App.tsx`（Toaster + Routes，按业务改路径）。
   - [ ] `src/components/Navbar.tsx`（替换品牌 logo / 标题 / 子菜单）。
4. **改造业务**
   - [ ] 把 `lib/api.ts` 中的 `API_BASE_URL` 与端点签名替换为新项目接口。
   - [ ] 按需替换 `lib/auth.ts` 的 token 存储 key 与 `/auth/me` 路径。
   - [ ] 按业务命名改色板（如把 `ocean` 重命名为 `medical/fintech` + 改 hex 序列）。
   - [ ] 用 §7 的页面模板，逐页替换内容；保留布局、状态/空态/错误态三件套与 hover/动效。
5. **品牌微调（可选）**
   - [ ] 修改 `--primary` 色相值（保留 94% 43% 的饱和度/亮度可保持发光质感）。
   - [ ] 修改 `--gradient-primary` 的两端 hue。
   - [ ] 修改 Logo `<Shield/>` 为业务图标，保持 `h-9 w-9 rounded-lg bg-primary/10 text-primary`。

---

## 14. "本项目独有"功能（替换时按需移除/保留）

| 功能 | 取舍建议 |
| --- | --- |
| YOLO 自动执行模式（首页右上 Badge + Toggle + 过期 Toast） | 通用代理类项目可保留为"自动执行 / 手动确认"开关；非 Agent 项目移除。 |
| 实时日志 + 发现流（SSE + Virtuoso） | 任何带"任务运行"业务都建议保留。 |
| 白名单 / 引擎资源 / 审计日志 / 平台设置 4 个管理页 | 安全/运维平台保留；普通业务移除。 |
| ECharts 风险趋势 + 资产聚类 | 替换业务指标即可复用图表样式。 |

---

## 15. 一段 30 秒"风格自检清单"

- ✅ 暗色背景 `--background: 222 47% 6%`，主色青蓝 `--primary: 189 94% 43%`。
- ✅ 顶栏 `sticky top-0 h-16 bg-background/80 backdrop-blur-md`。
- ✅ 主体 `container py-6 space-y-6`。
- ✅ 卡片 `rounded-xl border bg-card text-card-foreground shadow-sm bg-glass border-glow`。
- ✅ 状态色：success=emerald / warning=amber / destructive=red / alert=orange / primary=cyan-blue。
- ✅ 字体：UI=Inter+Noto Sans SC，数字/ID=JetBrains Mono。
- ✅ 图标：lucide-react，统一线性。
- ✅ 动效：`fade-in-up / slide-in-right / pulse-glow / hover-lift`。
- ✅ 空/错/载 三态齐备，关键操作 `Loader2 animate-spin` + 文案切换。

> 满足以上 9 条 = 风格已对齐。

---

附：典型尺寸快查

- 顶栏高 `h-16`；Logo 容器 `h-9 w-9 rounded-lg`；按钮默认 `h-10` / sm `h-9` / lg `h-11`。
- 圆角：`--radius:0.75rem`（lg=12 / md=10 / sm=8）；徽章用 `rounded-full`；输入用 `rounded-md`；卡片用 `rounded-xl`。
- 间距：卡片 padding `p-4 ~ p-6`；主区域 `space-y-6`；网格 `gap-4 / gap-6`。
- 文本：标题 `text-base font-semibold tracking-tight`；正文 `text-sm`；辅助 `text-xs / text-[10px]`；KPI 数字 `text-3xl font-bold` / `text-2xl font-bold`。

---

> 完成本模板替换后，建议保留 `webui/src/components/ui/*` 与 `index.css` 不做改动，业务侧只在 `pages/` 与 `hooks/` 下迭代，可让多个项目长期共享同一套设计系统。
