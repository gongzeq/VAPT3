# shadcn CLI 污染事件快照

**日期**：2026-05-08
**任务**：05-07-ocean-tech-frontend（PR2 完成后、PR3 启动前的异常发现）
**HEAD**：`a69d21f9` (main)
**处置决定**：丢弃全部 46 个脏改动（21 modified + 25 untracked），重新进入 PR3

## 为什么判定为污染

某次 shadcn CLI 对着"Next.js + Tailwind v4"上游模板重跑了一遍，覆盖/新增了 45 个 webui 文件。关键矛盾：

| 信号 | 观察 | 与项目约束的冲突 |
|---|---|---|
| `webui/src/app/dashboard/data.json` | Next.js app-dir 约定 | 本项目是 Vite/React，不走 app-dir |
| 新文件顶部 `"use client"` | Next.js RSC 指令 | Vite 下是死码 |
| `components/ui/sonner.tsx` 依赖 `next-themes` | Next.js 主题包 | 栈里没有 Next.js |
| `globals.css` 新增 `@theme inline { ... }` | Tailwind **v4** 语法 | PRD Decision 1 明确"TW v4 不兼容"，锁 v3.4 |
| `package.json`: `lucide-react: ^0.469.0 → ^1.14.0` | lucide-react 没有 1.x 正式版 | 几乎肯定错版 |
| 同时装 `framer-motion@^11` + `motion@^12.38.0` | 同根两份包 | dedup 冲突 |
| 新增 `@dnd-kit/*`、`zod@4`、`vaul`、`sonner`、`next-themes`、`@tanstack/react-table` | shadcn dashboard-01 上游依赖 | 不在 PRD R3 白名单 / `visualization-libraries.md` 白名单 |
| Radix 多包版本跳跃（`separator 1.1.1→1.1.8` 等） | CLI 默认拉最新 | 触发 lockfile 大面积重算 |
| `webui/src/blocks/dashboard-01/{chart-area-interactive,data-table,nav-documents,nav-secondary,section-cards,site-header}.tsx` 新增于顶层 | 与已提交的 `dashboard-01/components/*` 重复 | 两套同名源文件并存 |
| `magicui/*.tsx` 被"原味"覆盖 | PR2 做的 hex→`hsl(var(--token))` sweep 被擦掉 | 直接回退 PR2 |
| `components/ui/button.tsx` 等被 reformat | 分号被移除、`shadow-sm` 加回原样 | 失去 PR2 主题化修改 |

## 脏改动清单（45 个 webui 文件 + 1 个 journal）

脏文件列表见同目录 `shadcn-cli-pollution.filelist.txt`（`git status --porcelain -- webui/` 输出）。
完整 diff 见同目录 `shadcn-cli-pollution.diff`（2689 行，含所有修改和新增内容）。

## 教训（防复发）

1. **shadcn CLI 必须先验证 preset**：项目 `components.json` 应显式声明 `"framework": "vite"` 与 `"tailwindVersion": "3"`（或至少文档化）。现有 `webui/components.json` 需复核。
2. **添加 shadcn block 前先 dry-run**：`npx shadcn@latest add --dry-run dashboard-01` 预览差异，确认不拉 `next-themes` / `app/` / TW v4 语法后再落地。
3. **CLI 改 package.json 必须过 code review**：任何对 `lucide-react` / `framer-motion` / Radix 大面积 bump 的自动改动都要人工确认是否匹配 PRD 依赖白名单。
4. **PR2 token sweep 受 CI 保护**：在 `magicui/*.tsx` / `tremor/*.tsx` 加 eslint-plugin-no-hex 或 CI grep 规则（见 `spec/frontend/theme-tokens.md` §7），防止后续任何原味覆盖悄悄通过。

## 下一步

丢弃全部 46 个脏改动（`git checkout --` 模态 `M` 的 21 个 + `git clean -fd` 模态 `??` 的 25 个）；journal-1.md 的修改保留。之后按 Session 3 journal Next Steps 进入 **PR3**。
