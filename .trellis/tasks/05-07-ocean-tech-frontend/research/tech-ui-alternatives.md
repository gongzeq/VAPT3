# Research: tech-ui alternatives

- **Query**: Recommend mature React component library alternatives to `@prompt-or-die/tech-ui` for a cybersec/AI agent webui
- **Scope**: external (npm + GitHub API verified)
- **Date**: 2026-05-07

## TL;DR / Verdict

For a cybersec/AI-agent webui already on shadcn/ui + Tailwind 3.4 + assistant-ui + recharts, the winning combination is:

- **shadcn/ui blocks** (CLI copy) for layout shells (sidebar/dashboard scaffolds).
- **Tremor Raw** (CLI copy from tremor.so/blocks) for production dataviz where recharts feels low-level (DonutChart, AreaChart, Tracker, Callout). Avoid the `@tremor/react` npm package — its 3.x line has been stale since Jan 2025.
- **MagicUI** (CLI copy via shadcn registry) for HUD micro-interactions (BorderBeam, AnimatedBeam, Marquee, ShimmerButton, NumberTicker).
- **@xyflow/react** (npm) for agent-topology / pipeline graphs — only mature option in this candidate set.
- Build agent thought-chain / tool-call panels in-house using `@assistant-ui/react` primitives + shadcn Card + lucide-react — no mature library covers this niche today.

This combination keeps everything inside the shadcn HSL token system, leans on framer-motion (already a transitive dep of MagicUI/Aceternity/motion-primitives), and stays well under the 200 KB gzip bundle ceiling.

## 1. Library scorecard

All numbers verified 2026-05-07 via `npm view`, `api.npmjs.org/downloads`, and `api.github.com/repos`.

| Library | GH stars | Weekly DL | Last activity | Maintainer | License | TW v3 OK? | Adds to bundle (gzip) |
|---|---|---|---|---|---|---|---|
| MagicUI | 20,896 (magicuidesign/magicui) | n/a (CLI copy) | 2026-05-05 | magicuidesign | MIT | Yes (TW v3 + v4) | per-component (~5–15 KB each); framer-motion ~30 KB shared |
| Aceternity UI | no canonical OSS repo (web-distributed) | n/a (CLI copy / paste) | active site | Manu Arora | mixed (MIT + paid "Pro") | Yes (TW v3) | per-component; tabler-icons + framer-motion shared |
| Tremor (`@tremor/react`) | 3,407 (tremorlabs/tremor) | 298,852/wk | npm 3.18.7 published 2025-01-13 (stale ~16 mo); GH push 2025-10-10 | tremorlabs | Apache 2.0 | Yes (preset CSS) | ~80–110 KB gzip full import |
| Tremor Raw (blocks) | (same org, copy-only) | n/a (CLI copy) | active blocks | tremorlabs | Apache 2.0 | Yes (native) | ~0 npm; per-component code |
| motion-primitives | 5,522 (ibelick/motion-primitives) | n/a (CLI copy) | 2026-03-19 | ibelick | MIT | Yes (TW v3) | per-component; framer-motion required |
| shadcn/ui blocks | 113,737 (shadcn-ui/ui) | n/a (CLI copy) | 2026-05-07 | shadcn | MIT | Yes (native) | ~0 (uses existing primitives) |
| OriginUI | no public component repo (registry-only at originui.com); origin-space org has `ui-experiments` 1,411 stars | n/a (CLI copy) | active site | origin-space | MIT (per site) | Yes (TW v3 + v4 dual) | per-component; built on shadcn |
| @xyflow/react | 36,475 (xyflow/xyflow) | 5,502,689/wk | 2026-05-06 | xyflow | MIT | Yes (CSS import) | ~45–55 KB gzip core + ~20 KB minimap/controls |
| assistant-ui primitives | 9,933 (assistant-ui/assistant-ui — repo moved from Yonom/) | 529,424/wk (`@assistant-ui/react`) | 2026-05-07 (v0.14.0 released today) | assistant-ui org | MIT | Yes (already in deps) | already in bundle |

Notes from verification:
- `@assistant-ui/react` latest is 0.14.0 (2026-05-07); your project is pinned at ^0.10.0 — minor-version churn is expected pre-1.0 and component APIs have shifted between 0.10 and 0.14.
- `@xyflow/react` latest is 12.10.2 (2026-03-27); deps are tiny (`zustand@^4`, `classcat`, `@xyflow/system`).
- `@tremor/react` 3.18.7 still depends on `recharts@^2.13.3` and `@headlessui/react@2.2.0` — installing it will pull recharts (already in your deps, so net delta is small for chart deps but Tremor's own runtime is ~80 KB gzip).
- Aceternity UI and OriginUI are **website-distributed** registries, not GitHub-first projects. There is no canonical OSS repo to star or pin a commit on; you copy from their site or via a shadcn-CLI registry URL. This is a meaningful integration-model difference vs. MagicUI which has a clearly-versioned source repo.

## 2. Component coverage matrix

| Category | MagicUI | Aceternity | Tremor (Raw) | motion-primitives | shadcn blocks | OriginUI | @xyflow/react | assistant-ui |
|---|---|---|---|---|---|---|---|---|
| HUD primitives (frames/glass/scanlines/glow) | Strong (BorderBeam, ShineBorder, AnimatedGridPattern, Meteors, RetroGrid) | Strong (BackgroundBeams, Spotlight, Vortex, GlareCard) | None | Partial (Glow, Tilt) | None | Partial (frames, cards) | None | None |
| AI-agent UI (thought-chain, tool-call, workbench) | None directly | None directly | None | None | None | None | None | Partial (Thread, Message, Composer, ToolCallContentPart slot — no thought-chain primitive) |
| Cybersec dataviz (radar/donut/phase bar/network) | None | None | Strong (DonutChart, AreaChart, BarChart, ProgressBar, Tracker, Callout) | None | Partial (recharts examples in `dashboard-01..07`) | None | Strong (network/topology only) | None |
| Layout shells (admin/dashboard) | None | Partial (Sidebar) | Partial (dashboard blocks at tremor.so) | None | Strong (sidebar-01..16, dashboard-01..07) | Partial (admin variants) | None | Partial (Thread layouts) |
| Micro-interactions (pulse/shimmer/badges) | Strong (ShimmerButton, AnimatedShinyText, NumberTicker, Marquee, Confetti) | Strong (HoverEffect, MovingBorder, AnimatedTooltip) | Partial (Badge, Callout) | Strong (TextEffect, ScrollAnimate, Cursor) | Weak | Partial (badges, buttons) | None | None |

Legend: Strong = clearly best choice for this surface; Partial = some coverage; None = not a fit.

## 3. Per-library deep dive

### MagicUI
Free, open-source CLI-copy component collection installed via shadcn registry: `npx shadcn add "https://magicui.design/r/<component>.json"`. Targets shadcn-style projects, built on Tailwind + framer-motion. Strengths: HUD-y eye-candy — `BorderBeam`, `ShineBorder`, `AnimatedGridPattern`, `Meteors`, `RetroGrid`, `Marquee`, `NumberTicker`, `ShimmerButton`, `AnimatedBeam`. Theming integrates cleanly with shadcn HSL tokens; most components reference `--primary` / `--background` via Tailwind utilities. Install model: **CLI copy-paste, not npm** — components land in `src/components/magicui/*.tsx`, easy to fork. Risk: a few components contain hardcoded color values; sweep with grep after copy and replace raw hex with `hsl(var(--primary))`. Compatible with Tailwind v3.4 today; many components also have v4 variants. Active repo (push 2026-05-05, 20.9k stars) — high confidence.

### Aceternity UI
By Manu Arora; CLI/copy-paste collection of marketing-grade animations. Strengths: `BackgroundBeams`, `Spotlight`, `Vortex`, `GlareCard`, `MovingBorder`, `HoverBorderGradient`, `AnimatedTooltip`. Heavily uses framer-motion. **Critical license note**: a subset are "Aceternity Pro" / paid (not OSS); verify each component before copying. **No canonical public GitHub repo for the components themselves** — distribution is via the website, with shadcn-CLI registry URLs. Theming: components ship with hardcoded gradients and raw colors more often than MagicUI, so adapting to HSL tokens needs more rewriting per component. Install: copy-paste from website per component. Risk: dramatic gradient bias clashes with a clinical cybersec aesthetic; pick selectively (Spotlight, GlareCard, MovingBorder are the safest fits).

### Tremor / Tremor Raw
Tremor is the only **npm-published** option focused on production dataviz/dashboards. Apache 2.0. The npm package `@tremor/react` (3.18.7) is **stale: last stable release 2025-01-13, ~16 months old as of today**, and the org has shifted focus to "Tremor Raw" — shadcn-style copy components on tremor.so/blocks that drop the runtime dep. The 4.x npm line is stuck in beta and was last touched 2024-12-14. For a cybersec dashboard, the components you want are `DonutChart`, `AreaChart`, `BarChart`, `ProgressBar`, `Tracker` (a phase-bar of square cells, perfect for kill-chain or scan-phase visualization), `Callout`, `Metric`. Install model: **prefer Tremor Raw (copy)** over `@tremor/react` (npm). Theming: classic Tremor uses its own preset (`tremor-*` classes) which conflicts with shadcn unless you adopt Tremor Raw. Risk: full `@tremor/react` import adds 80–110 KB gzip; mitigate by using Tremor Raw (zero npm cost) or aggressive tree-shaking.

### @xyflow/react (React Flow)
Industry-standard graph/flow canvas. Verified: 36,475 stars, 5.5M weekly downloads, MIT, last push 2026-05-06 — the most active and most-used library in this candidate set. Perfect for agent topology, attack-chain visualizations, and pipeline DAGs. Pros: pan/zoom, mini-map, custom nodes (your shadcn Card can be a node), edge animations (animated SVG paths), strong TS types. Cons: requires `import '@xyflow/react/dist/style.css'`; CSS variables don't map to shadcn tokens out of the box — wrap nodes in your own components and override edge stroke via `data-` attributes or the `style` prop. Bundle: ~45–55 KB gzip core. Compatible with Tailwind v3 (CSS is scoped). The clear, **only real choice for graph work** on this candidate list.

## 4. Recommended stack (winning combination)

Per surface, with exact component picks:

**Chat (assistant-ui)**
- Keep `@assistant-ui/react` Thread/Message/Composer.
- Wrap with shadcn `Card` + MagicUI `BorderBeam` for the active-thread highlight.
- Use MagicUI `AnimatedShinyText` (or `TextShimmer`) for "thinking…" streaming-status hints.
- Tool-call panels: build in-house using shadcn `Collapsible` + `Card` + lucide `Wrench` icon (see §6).

**Assets / Inventory**
- shadcn `DataTable` (TanStack Table) — already in shadcn blocks `dashboard-01`.
- shadcn `Badge` (with custom variant) for criticality tags, or Tremor Raw `Badge`.
- MagicUI `NumberTicker` for "1,234 assets" hero counters.

**Scans / Pipeline**
- Tremor Raw `Tracker` for kill-chain / scan-phase row.
- Tremor Raw `ProgressBar` for individual scan progress.
- `@xyflow/react` for the multi-stage agent pipeline graph.

**Reports / Dashboards**
- shadcn block `dashboard-01` as scaffold.
- Tremor Raw `DonutChart` (severity breakdown) and `AreaChart` (findings over time); fall back to recharts for anything Tremor Raw lacks.
- Tremor Raw `Callout` for critical alerts above the fold.
- MagicUI `AnimatedGridPattern` as a subtle page background (HUD feel without dominating).

**Globally**
- shadcn block `sidebar-07` for the collapsible app-shell sidebar.
- MagicUI `Marquee` for the live-event ticker (CVE feed / scan events).

## 5. Three adoption recipes

### Recipe A: Minimal (only what's missing)
**Add**:
- `@xyflow/react` (npm) — for the agent-topology page only.
- 2–3 MagicUI components (CLI copy): `BorderBeam`, `NumberTicker`, `AnimatedShinyText`.
- 1 shadcn block (`sidebar-07`) — copy.

**Bundle delta**: ~50–65 KB gzip (xyflow ~50 KB; framer-motion shared/transitive).

**Pros**: Lowest risk, fastest to ship.
**Cons**: Misses dashboard polish; HUD aesthetic feels incomplete.

### Recipe B: Comfortable middle (RECOMMENDED)
**Add**:
- `@xyflow/react` (npm).
- Tremor Raw components (CLI copy from tremor.so/blocks): `DonutChart`, `AreaChart`, `BarChart`, `Tracker`, `ProgressBar`, `Callout`, `Metric`.
- MagicUI components (CLI copy): `BorderBeam`, `ShineBorder`, `AnimatedGridPattern`, `Marquee`, `NumberTicker`, `AnimatedShinyText`, `ShimmerButton`, `AnimatedBeam`.
- shadcn blocks: `sidebar-07`, `dashboard-01` as page scaffolds.

**Bundle delta**: ~80–110 KB gzip (xyflow ~50 KB + framer-motion delta ~25 KB + Tremor Raw and MagicUI add little since they're copy-only TS files).

**Pros**: Full HUD/cybersec aesthetic, production dataviz coverage, all token-compatible, **only one new npm runtime dep** (`@xyflow/react`).
**Cons**: ~12 files to copy in; one-time integration cost (~half a day).

### Recipe C: Maximal (full HUD)
**Add everything in B, plus**:
- Aceternity components (CLI/manual copy): `Spotlight`, `GlareCard`, `MovingBorder`, `HoverBorderGradient`, `Vortex` (background only).
- motion-primitives (CLI copy): `Tilt`, `TextEffect`, `Cursor` follow-effects.
- OriginUI specific overrides where the shadcn variant feels weak.

**Bundle delta**: ~130–170 KB gzip.

**Pros**: Maximum visual differentiation; "movie-grade" cybersec console feel.
**Cons**: Risk of crossing the 200 KB ceiling if many backgrounds animate concurrently; theming-mismatch effort doubles (Aceternity uses raw colors more often). Reserve for hero/login pages.

## 6. AI-agent components gap

**Verdict: No mature OSS library covers AI-agent UI (thought-chain, tool-call panels, agent-workbench timelines) as of 2026-05-07.** This is genuinely a green-field UI category.

What exists:
- `@assistant-ui/react` provides chat-level primitives (Thread, Message, Composer, ToolCallContentPart slot) — these are **building blocks**, not finished agent-workbench components.
- LangChain's LangGraph Studio has UI but is desktop-app-bound (Electron), not a React lib.
- Vercel's AI SDK ships hooks (`useChat`), no visual components.

**Recommendation: build in-house, composing**:
- shadcn `Card`, `Collapsible`, `Accordion`, `ScrollArea`, `Tabs`, `Badge`, `Avatar`.
- assistant-ui `ToolCallContentPart` slot for the data plumbing.
- lucide icons (`Brain`, `Wrench`, `Search`, `FileText`, `ChevronDown`).
- MagicUI `BorderBeam` for the "active step" indicator and `AnimatedShinyText` for streaming reasoning.
- `@xyflow/react` if you want a graph view of the agent's plan (optional).

A plan-of-attack pattern (each step = a `Card` with status icon + tool-call detail in `Collapsible`) ships in ~200 lines and looks better than any generic library would. This is also the right architectural call: agent UIs are too domain-specific (which tools, which schema) to be successfully generalized by a library yet.

## 7. Risks and red flags per library

- **MagicUI**: Some component source contains hardcoded color values; sweep after copy. framer-motion versions occasionally pinned mid-major; lockfile carefully.
- **Aceternity UI**: License heterogeneity — a subset is "Pro" / paid. Verify each component's license before copy. No canonical OSS repo, so you cannot pin a commit; track copy date in the file header. Heavy gradient bias clashes with clinical cybersec UI; selective adoption only.
- **Tremor (npm `@tremor/react`)**: **Stale — 3.18.7 from 2025-01-13 (~16 months old); 4.x line stuck in beta since 2024-12-14**. Avoid the npm package for new adoption; use Tremor Raw (copy from tremor.so/blocks) instead.
- **Tremor Raw**: Copy components are healthy but distributed via website blocks; no semver per block. Pin a copy date and re-fetch deliberately.
- **motion-primitives**: Smaller community (5.5k stars). Treat as bonus polish, not a foundation. Last push 2026-03-19 — active but not as fast-moving as MagicUI.
- **shadcn blocks**: Not versioned independently; "block" updates land via CLI re-fetch, no semver. Pin a commit if you need stability. Repo is extremely active (push today, 113k stars).
- **OriginUI**: Registry-only distribution (originui.com); the org's only widely-starred GitHub repo is `ui-experiments` (1,411 stars). Coverage overlaps shadcn's own blocks ~70% — only worth picking specific components, not bulk adopting.
- **@xyflow/react**: CSS import is required and lives outside Tailwind's config; theming via CSS variables (`--xy-edge-stroke` etc.). Plan a small wrapper file. Watch for v12 → v13 breaking renames if/when they happen.
- **assistant-ui**: 0.14.x is still pre-1.0; your project pins ^0.10.0. Minor versions can break component APIs (Thread/Message slot conventions changed during 0.10 → 0.14). Pin tightly; test before bumping. Repo was renamed/moved from `Yonom/assistant-ui` to `assistant-ui/assistant-ui` — update any pinned URLs.

## 8. References

All URLs verified 2026-05-07.

- MagicUI: https://magicui.design/ , https://github.com/magicuidesign/magicui (20,896 stars, MIT)
- Aceternity UI: https://ui.aceternity.com/ (web-distributed; no canonical OSS repo)
- Tremor: https://tremor.so/ , https://github.com/tremorlabs/tremor (3,407 stars, Apache-2.0); Tremor Raw blocks: https://tremor.so/blocks
- motion-primitives: https://motion-primitives.com/ , https://github.com/ibelick/motion-primitives (5,522 stars, MIT)
- shadcn/ui blocks: https://ui.shadcn.com/blocks , https://github.com/shadcn-ui/ui (113,737 stars, MIT)
- OriginUI: https://originui.com/ (registry-only); origin-space GitHub org: https://github.com/origin-space
- React Flow / xyflow: https://reactflow.dev/ , https://github.com/xyflow/xyflow (36,475 stars, MIT) , npm: https://www.npmjs.com/package/@xyflow/react (12.10.2)
- assistant-ui: https://www.assistant-ui.com/ , https://github.com/assistant-ui/assistant-ui (9,933 stars, MIT) , npm: https://www.npmjs.com/package/@assistant-ui/react (0.14.0 released 2026-05-07)
- framer-motion: https://www.npmjs.com/package/framer-motion (transitive via MagicUI / Aceternity / motion-primitives)
- npm download stats: https://api.npmjs.org/downloads/point/last-week/<package>

## Caveats / Not Found

- All star counts and weekly download numbers verified 2026-05-07 via `api.github.com/repos/<owner>/<repo>` and `api.npmjs.org/downloads/point/last-week/<pkg>`. Re-verify on adoption day; weekly DL fluctuates ±10%.
- Bundle-size estimates are derived from each library's typical component set; actual gzip delta depends on which components you import. Run `vite build --report` (or `rollup-plugin-visualizer`) before/after each Recipe to confirm.
- "Aceternity Pro" license boundary is component-specific and not machine-readable; treat the website as source of truth per component before copying.
- OriginUI's component source distribution: confirmed as registry-only on originui.com; the public GitHub org `origin-space` does not contain a single "originui" repo. If long-term forkability matters, MagicUI is the safer choice.
- No mature OSS library was found for agent thought-chain / tool-call workbench UIs as of 2026-05-07. This is consistent across the candidate set and broader npm/GitHub searches.
