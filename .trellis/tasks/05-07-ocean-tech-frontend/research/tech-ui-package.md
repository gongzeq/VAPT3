# Research: `@prompt-or-die/tech-ui` package adoption

- **Query**: Verify and characterize `@prompt-or-die/tech-ui` for adoption in VAPT3/secbot webui (React 18 + Vite 5 + Tailwind 3.4 + shadcn/ui + assistant-ui 0.10).
- **Scope**: External (npm registry, GitHub API, tarball inspection) + internal cross-check (webui/package.json, webui/tailwind.config.js, webui/src/globals.css, secbot shell)
- **Date**: 2026-05-07
- **Verdict (TL;DR)**: Package **is published** but is a **brand-new, unmaintained one-person side project** (v0.0.1, 3 commits, 1 star, ~10 downloads/month). It has **non-trivial but workable integration friction** with our shadcn/Tailwind 3.4 setup, **hardcoded orange brand color** in many components, and **most "Layout" templates are static visual demos that take only `className`** (no data props). **Recommend: cherry-pick a small set of primitives + data-viz (TechFrame/Card/Radar/Donut/PhaseBar/ThoughtChain) under a feature flag, do NOT adopt the Layout templates wholesale, and prepare a vendor-fork fallback.**

---

## 1. Publication & maintenance signals

| Field | Value | Source |
|---|---|---|
| npm package | `@prompt-or-die/tech-ui` | `npm view @prompt-or-die/tech-ui` |
| Latest version | `0.0.1` (only version) | npm |
| Published | **2025-12-07T08:30:08Z** (5 months ago) | npm `time` field |
| Last modified | **2025-12-07T08:30:09Z** | npm |
| License | MIT | npm + GitHub |
| Maintainer | `dexploarer <dexploarer@gmail.com>` (single user) | npm |
| Tarball / unpacked | 97.1 kB / 525.1 kB (8 files) | `npm pack --dry-run` |
| Downloads (last week) | **2** | `api.npmjs.org/downloads/point/last-week` |
| Downloads (last month) | **10** | `api.npmjs.org/downloads/point/last-month` |
| GitHub repo | https://github.com/Dexploarer/prompt-or-die-tech-ui | repo |
| Stars / Forks | **1 / 0** | GitHub API |
| Open + closed issues | **0** | GitHub API |
| Open + closed PRs | **0** | GitHub API |
| Total commits | **3** (all on 2025-12-07) | GitHub commits |
| Last push | 2025-12-07T08:32:51Z (dormant for 5 months) | GitHub API |
| Contributors | **1** (dexploarer) | GitHub API |

**Production-readiness flags**:
- One-time release, never iterated. No bug fixes, no contributors, no community.
- Org claim ("Prompt-or-Die") in README points at a GitHub user, not an organization with multiple repos.
- README example uses `border-primary/50` — works if Tailwind config exposes `primary` token.
- README claims "Strict TypeScript, Zero `any`". Bundled `dist/index.d.ts` is 820 lines, all components have typed props. Surface-level review found no `any`.
- **No CHANGELOG, no test files, no examples directory in tarball**. Files shipped: `LICENSE`, `README.md`, `dist/{index.cjs,index.d.cts,index.d.ts,index.js}`, `globals.css`, `package.json`.

**Risk verdict**: Treating tech-ui as a stable upstream dependency is **risky**. Treat it as **vendored source** (inline into our repo) or pin exactly to `0.0.1` and be prepared to fork.

---

## 2. Required peer dependencies and bundle cost

### 2.1 Peer deps declared

```json
"peerDependencies": {
  "react": "^18.0.0 || ^19.0.0",
  "react-dom": "^18.0.0 || ^19.0.0",
  "tailwindcss": ">=3.4.0 <5.0.0"
}
```

### 2.2 Runtime `dependencies` (bundled with the package, NOT peer)

```json
"dependencies": {
  "clsx": "^2.1.0",                  // we have ^2.1.1   ✅
  "tailwind-merge": "^2.2.0",        // we have ^2.6.0   ✅
  "framer-motion": "^11.0.0",        // WE DON'T HAVE   ⚠️
  "lucide-react": "^0.460.0"         // we have ^0.469.0 ✅
}
```

`framer-motion` is the **only new transitive runtime dependency** we'd inherit. The other three are already in our webui or compatible.

### 2.3 Bundle size measurements (raw inspection of the tarball)

| Asset | Raw | Gzip |
|---|---|---|
| `dist/index.js` (full ESM) | 211.3 kB | **~40 kB** |
| `dist/index.cjs` (full CJS) | 239.2 kB | ~42 kB |
| `globals.css` | 5.8 kB | ~1.5 kB |

Gzip measured locally with `gzip -c | wc -c`.

### 2.4 framer-motion bundle cost

- Latest npm version: `12.38.0` — but tech-ui requires `^11.0.0` (so installs `framer-motion@11.x`).
- Weekly downloads: 33.7M (very mainstream, well-maintained).
- bundlephobia rate-limited during research; conservative published numbers:
  - `framer-motion@11` minified+gzip when fully tree-shaken to `motion` + `AnimatePresence` only ≈ **30–35 kB gzip**.
  - Worst-case (full library) ≈ 100 kB gzip.
- tech-ui imports only `motion` and `AnimatePresence`, so the 30–35 kB figure is realistic.

### 2.5 Tree-shakeability analysis

- Bundle structure: **one ESM file** (`dist/index.js`) with all components inlined; final statement is a single `export { ... }` block re-exporting ~150 named symbols.
- `package.json` does **NOT declare `"sideEffects": false`** — Vite/Rollup will treat every file as having side effects by default, which **degrades dead-code elimination**.
- Top-of-file `import { motion, AnimatePresence } from "framer-motion"` is repeated **9 times** (once per component file pre-bundle, e.g. `TechToast`, `TechPhaseBar`, `TechThoughtChain`, `TechAgentWorkbench`, `TechCommandPalette`, `TechAuthLayout`, `TechSettingsLayout`, `TechLandingLayout`, `TechModal`).
- Practical implication: **importing any single component that uses framer-motion pulls framer-motion**. Importing only `TechCard` + `TechFrame` (no framer-motion users) MAY tree-shake framer-motion away under modern Vite, but `TechPhaseBar`, `TechThoughtChain`, and `TechAgentWorkbench` (all in the user's wishlist) **do** use framer-motion → framer-motion will ship.
- The 211 kB raw bundle should DCE down to ~30–40% of itself for a focused subset, i.e., 60–80 kB raw / **15–25 kB gzip** for the requested component set, plus framer-motion ~30 kB gzip = **~45–55 kB gzip total addition**. Comfortably within the ≤200 kB gzip budget from the PRD.

**Recommendation**: After integrating, run `bun run build` and inspect `dist/assets/*.js` size. If unexpectedly large, vendor the source instead of importing from npm.

---

## 3. Tailwind config integration

### 3.1 README-prescribed setup

```ts
// tailwind.config.ts
content: [
  "./node_modules/@prompt-or-die/tech-ui/dist/**/*.{js,ts,jsx,tsx}",
  // ... your other paths
]
```

Our existing `webui/tailwind.config.js` content array:

```js
content: ["./index.html", "./src/**/*.{ts,tsx}"]
```

**Action**: append `"./node_modules/@prompt-or-die/tech-ui/dist/**/*.{js,ts,jsx,tsx}"`. JIT will then pick up tech-ui's class names so the CSS is generated.

### 3.2 Tailwind plugins — **NONE required**

tech-ui does not rely on `tailwindcss-animate`, `@tailwindcss/typography`, `tailwindcss-forms`, etc. Our existing `tailwindcss-animate` + `@tailwindcss/typography` plugins are unaffected.

### 3.3 BIG GOTCHA — `globals.css` uses Tailwind v4 syntax

The shipped `globals.css` (5.8 kB) starts with:

```css
@import "tailwindcss";

@theme {
  --color-background: #0a0a0a;
  --color-foreground: #fafafa;
  --color-primary: #ff5800;       /* ORANGE (cyberpunk default) */
  ...
}
```

`@import "tailwindcss"` and the `@theme {}` directive are **Tailwind v4** (≥ 4.0) syntax. Our setup is **Tailwind v3.4.17** which uses the classic `@tailwind base/components/utilities` directives.

**You CANNOT `@import "@prompt-or-die/tech-ui/globals.css"` into our v3 `webui/src/globals.css`** — PostCSS will throw on `@theme`, and `@import "tailwindcss";` is a no-op resolution.

**Workaround**: Manually translate the variables tech-ui depends on into our existing `:root[data-theme="secbot"]` block in `webui/src/globals.css`. See §5 for the exact mapping.

### 3.4 Required additional Tailwind tokens

Component-class scan of `dist/index.js` (`grep -oE "(border|bg|text|ring|...)-(primary|...|success|warning|info|error|destructive|...)"`) found these theme color tokens used:

| Token | In our shadcn config | Action |
|---|---|---|
| `primary` | ✅ | none |
| `secondary` | ✅ | none |
| `destructive` | ✅ | none |
| `accent` | ✅ | none |
| `muted`, `muted-foreground` | ✅ | none |
| `border` | ✅ | none |
| `card`, `card-foreground` | ✅ | none |
| `popover` | ✅ | none |
| `background`, `foreground` | ✅ | none |
| `input`, `ring` | ✅ | none |
| **`success`** | ❌ | **must add** |
| **`warning`** | ❌ | **must add** |
| **`error`** | ❌ | **must add** (separate from `destructive`) |
| **`info`** | ❌ | **must add** |

Without `success/warning/error/info` in `tailwind.config.js → theme.extend.colors`, classes like `bg-success/10`, `border-warning/50`, `text-info` from tech-ui will silently produce **no styles** — components will look broken (e.g., TechPhaseBar's "completed" state uses `border-success`, TechThoughtChain's "completed" indicator uses `bg-success`).

We can map these to severity colors we already have:
- `success` ← `--sev-low` (or new `141 71% 48%`)
- `warning` ← `--sev-medium` (`48 96% 53%`)
- `error` ← `--sev-critical` (`0 100% 65%`)
- `info` ← `--sev-info` (`220 7% 64%`) or our `--primary` Dodger Blue

### 3.5 BIG GOTCHA #2 — components reference `var(--primary)` directly

Our shadcn HSL token system stores **HSL components only**:

```css
:root[data-theme="secbot"] {
  --primary: 210 100% 56%;          /* not a valid color on its own */
}
```

…and Tailwind's `bg-primary` resolves through `hsl(var(--primary))` (defined in `tailwind.config.js`).

But several tech-ui components write `var(--primary)` directly into inline `style` props or arbitrary-value classes:

| File location (in bundle) | Usage | Effect with shadcn HSL form |
|---|---|---|
| Line 1482 — `TechRadar` | `background: "conic-gradient(...transparent 270deg, var(--primary) 360deg)"` | Invalid color → gradient renders broken |
| Line 1502 — `TechRadar` | `boxShadow: \`0 0 10px ${point.color || "var(--primary)"}\`` | Invalid color → shadow disappears |
| Line 1746, 1776 — `TechHoloProjector` | `color = "var(--primary)"` default + `shadow-[0_0_30px_rgba(var(--primary-rgb),0.3)]` | both broken |
| Lines 645, 687, 1751, 2734 — `TechCommandPalette`, `TechModal`, etc. | `rgba(var(--primary-rgb), 0.5)` arbitrary classes | rgba() with HSL components → black or no-op |

**Fix**: define **two extra CSS variables** alongside the existing HSL-component form, scoped to `:root[data-theme="secbot"]`:

```css
:root[data-theme="secbot"] {
  --primary: 210 100% 56%;          /* keep — shadcn HSL components */
  --primary-color: #1E90FF;         /* NEW — full color for tech-ui inline styles */
  --primary-rgb: 30, 144, 255;      /* NEW — for rgba(var(--primary-rgb), N) shadows */
}
```

…and patch tech-ui to read `--primary-color` instead of `--primary`. This requires either (a) vendoring the source and search-replacing, or (b) overriding via a CSS layer that takes precedence (only viable for class-based usages, not inline styles).

**Cleanest path**: vendor-fork the 6–8 components we actually want and replace `var(--primary)` → `hsl(var(--primary))` and `var(--primary-rgb)` → custom variable.

### 3.6 BIG GOTCHA #3 — hardcoded orange brand color

23 occurrences of `rgba(255, 88, 0, ...)` or `#ff5800` literal in `dist/index.js`:

| Component | Hardcoded | What it produces |
|---|---|---|
| `TechBadge` (default "glow" variant) | `shadow-[0_0_8px_rgba(255,88,0,0.4)]` | orange glow regardless of theme |
| `TechButton` (primary variant) | `shadow-[0_0_20px_rgba(255,88,0,0.3)]` and `hover:shadow-[0_0_30px_rgba(255,88,0,0.6)]` | orange glow on primary buttons |
| `TechPhaseBar` (current step) | `shadow-[0_0_15px_rgba(255,88,0,0.4)]` | orange glow on the active phase dot |
| `Card` (shadcn-style "Card") | `hover:shadow-[0_0_30px_rgba(255,88,0,0.1)]` | orange glow on card hover |
| `Badge` (default variant) | `shadow-[0_0_10px_rgba(255,88,0,0.4)]` | orange glow on badges |
| `TechChart`, `TechDonut`, `TechHoloProjector`, `TechBiometrics`, `TechGeometry`, `TechQuantumLoader`, `TechNeuralMesh` | `color = "#ff5800"` default prop | orange data series unless caller passes a `color` prop |
| `TechAgentWorkbench`, `TechAuthLayout` | inline `color: "#ff5800"` and `bg-primary shadow-[0_0_10px_rgba(255,88,0,0.5)]` literals | orange branding regardless of theme |

**Implication**:
- For the **chartable** components (`TechChart/Donut/Radar/HoloProjector/Biometrics/NeuralMesh`), we can pass `color="#1E90FF"` (our Dodger Blue) per render site → fully fixable.
- For the **glow-shadow** literals on `TechButton`/`TechBadge`/`TechPhaseBar`/`Card`, the orange hex is baked into the className string. Cannot override via Tailwind config alone. Requires either (a) vendor-forking the components, (b) post-render CSS overrides targeting `.shadow-\[0_0_20px_rgba\(255\,88\,0\,0\.3\)\]` (fragile, ugly), or (c) accepting the orange glow on hover/active states (jarring against ocean blue).

---

## 4. Component import paths and tree-shaking story

### 4.1 Single-entry exports

```js
// package.json
"exports": {
  ".":            { "types": "./dist/index.d.ts", "import": "./dist/index.js", "require": "./dist/index.cjs" },
  "./globals.css": "./globals.css"
}
```

There are **NO sub-path entries** like `@prompt-or-die/tech-ui/radar` or `@prompt-or-die/tech-ui/agent`. Every component is imported from the package root:

```ts
import { TechRadar, TechCard, TechDonut, TechAgentWorkbench, TechThoughtChain, TechPhaseBar } from "@prompt-or-die/tech-ui";
```

### 4.2 Tree-shaking the requested set

- `TechCard`, `TechRadar`, `TechDonut` — pure JSX + Tailwind, **no framer-motion**. Each ≈ 1–3 kB minified.
- `TechPhaseBar` — uses `motion.div` from framer-motion → pulls framer-motion.
- `TechThoughtChain` — uses `motion.div` + `AnimatePresence` → pulls framer-motion.
- `TechAgentWorkbench` — uses `motion`, `AnimatePresence`, `lucide-react` icons (`Play, Pause, Square, AlertCircle, FileCode`) → pulls framer-motion.

Combined estimate after Vite production build:
- tech-ui code: **~25–40 kB min / ~10–15 kB gzip** (subset of the 211 kB bundle).
- framer-motion subset (`motion`, `AnimatePresence`): **~80–100 kB min / ~30–35 kB gzip**.
- lucide-react icons: already in our app, deduped.
- **Total addition: ~40–50 kB gzip**, well below 200 kB budget.

### 4.3 No `sideEffects: false` flag

Already noted in §2.5. This means Vite will be conservative; the actual production bundle should be inspected after a real build. If undesirable, vendoring is preferred.

---

## 5. Theming hooks — does it expose CSS custom props or a Theme provider?

### 5.1 No React theme provider, no React context

Confirmed by source scan (`grep -nE "Provider|createContext"`):
- The only `React.createContext` use is `RadioGroupContext` (for radio button group state).
- There is **no `ThemeProvider`, no `useTheme`, no theme registry**.

### 5.2 Theming is 100% via CSS custom properties (one-way)

Customization happens by overriding the variables tech-ui's `globals.css` declares. From `globals.css`:

```css
@theme {
  --color-background: #0a0a0a;
  --color-foreground: #fafafa;
  --color-card: #111111;
  --color-card-foreground: #fafafa;
  --color-muted: #1a1a1a;
  --color-muted-foreground: #737373;
  --color-primary: #ff5800;
  --color-primary-foreground: #ffffff;
  --color-secondary: #1f1f1f;
  --color-secondary-foreground: #fafafa;
  --color-accent: #ff5800;
  --color-accent-foreground: #ffffff;
  --color-destructive: #ef4444;
  --color-destructive-foreground: #fafafa;
  --color-border: #262626;
  --color-input: #262626;
  --color-ring: #ff5800;
  --color-success: #22c55e;
  --color-warning: #eab308;
  --color-error: #ef4444;
  --color-info: #3b82f6;
  --radius-lg: 0.5rem; --radius-md: 0.375rem; --radius-sm: 0.25rem;
  --font-family-mono: "SF Mono", "Roboto Mono", ui-monospace, monospace;
  --font-family-sans: "Inter", system-ui, sans-serif;
  --shadow-glow-primary: 0 0 20px rgba(255, 88, 0, 0.4);
}
```

Plus utility classes shipped in `globals.css`: `.tech-frame`, `.tech-frame-inner`, `.corner-frame`, `.corner-tl/tr/bl/br`, `.glass`, `.glass-hover`, `.text-glow`, `.animate-pulse-glow`, `.animate-fade-in`, scrollbar overrides.

### 5.3 Token-name collision with our shadcn HSL system

| Concept | tech-ui (Tailwind v4 `@theme`) | shadcn (Tailwind v3) | Same name? |
|---|---|---|---|
| Primary color | `--color-primary: #ff5800` (full hex) | `--primary: 210 100% 56%` (HSL components) | **Different name** (`--color-primary` vs `--primary`) — no clash |
| Background | `--color-background: #0a0a0a` | `--background: 230 20% 5%` | Different name — no clash |

So if we (a) keep our `--primary`, `--background`, etc. as-is, and (b) ALSO declare `--color-primary: #1E90FF;` etc., we get both. tech-ui components compiled against `--color-*` CSS vars will theoretically work IF those classes (e.g. `bg-primary`) are auto-generated by Tailwind v4 from the `@theme` block.

**BUT** — in our v3 setup, classes like `bg-primary` come from our `tailwind.config.js` color extension `primary: "hsl(var(--primary))"`, NOT from any `--color-primary` variable. So tech-ui's `bg-primary` will resolve via OUR `--primary` HSL variable, which means in our setup **the `--color-*` aliases in tech-ui's globals.css are useless — Tailwind v3 doesn't read them**.

The only meaningful theming hooks for our v3 setup:
1. `tailwind.config.js theme.extend.colors` (already mostly satisfied except `success/warning/error/info`).
2. Component-level `color` props on `TechRadar.points[].color`, `TechDonut.color`, `TechChart.color`, `TechHoloProjector.color`, `TechBiometrics.color`, `TechGeometry.color`, `TechQuantumLoader.color`, `TechNeuralMesh.color` — accept any CSS color string.

### 5.4 Recommended ocean-blue mapping

Edit `webui/src/globals.css` `:root[data-theme="secbot"]` block, ADD:

```css
/* tech-ui compatibility variables — keep alongside the existing HSL components. */
--color-primary: hsl(var(--primary));         /* allows var(--color-primary) consumers */
--primary-rgb: 30 144 255;                    /* for rgba(var(--primary-rgb), N) — note SPACE-separated */
--success: 141 71% 48%;                       /* HSL components, like shadcn; pair with `success: "hsl(var(--success))"` in tailwind.config */
--warning: 48 96% 53%;
--error:   0 100% 65%;
--info:    203 100% 62%;
```

…and update `tailwind.config.js` to extend:

```js
colors: {
  // existing...
  success:    "hsl(var(--success))",
  warning:    "hsl(var(--warning))",
  error:      "hsl(var(--error))",
  info:       "hsl(var(--info))",
}
```

The `--primary-rgb` form is the trickier one — `rgba(var(--primary-rgb), 0.5)` only works if `--primary-rgb` resolves to comma-separated R,G,B (per the CSS rgba() syntax). If we want it to work with our HSL approach, we'd need a separate color token. Realistically we just hard-code `--primary-rgb: 30, 144, 255;` (Dodger Blue) and accept that switching the hue means manually updating both forms. **The components using this — TechCommandPalette, TechModal, TechHoloProjector — are NOT in the user's "must-have" list, so we can defer this.**

---

## 6. Compatibility risks with shadcn/ui

| Surface | Shadcn (existing) | tech-ui | Conflict? |
|---|---|---|---|
| `clsx` | ^2.1.1 | ^2.1.0 | None (compatible majors). |
| `tailwind-merge` | ^2.6.0 | ^2.2.0 | None (compatible). |
| `lucide-react` | ^0.469.0 | ^0.460.0 | None (we have newer; deduped). |
| `cn()` helper | shadcn re-exports its own `cn` | tech-ui exports its own `cn` | Naming collision **at JS level — but only if you import both with the same name**. Easy to avoid. |
| Class names | `Badge`, `Button`, `Card`, `Input`, `Modal`, `Switch`, `Checkbox`, `Radio`, `Textarea`, `Spinner`, `Skeleton`, `Toast`, `Accordion`, `Breadcrumb`, `Dropdown` | tech-ui ALSO exports these as **plain names** (not "Tech*-prefixed") | **YES — re-export name collision**. If you `import { Button } from "@prompt-or-die/tech-ui"` AND `import { Button } from "@/components/ui/button"`, you must alias one. |
| Tailwind utility classes | shadcn classes (`bg-card`, `border-border`, `text-foreground`) | identical names | None — both target the same Tailwind tokens, the LAST CSS variable assignment wins, and we control that via our `globals.css`. |
| `@layer base` selectors | `* { @apply border-border; }` | tech-ui `globals.css` does `* { border-color: var(--color-border); }` | **Conflict IF both load** — last loaded wins. We will NOT import tech-ui's `globals.css` (incompatible Tailwind v4 syntax anyway), so no conflict. |
| Scrollbar styles | none in shadcn | tech-ui `globals.css` overrides `::-webkit-scrollbar` to dark theme | Only if we import tech-ui's globals.css. We won't. |

**Action items**:
- Use **named import aliasing** for any `Tech<Name>` that overlaps with shadcn primitive: `import { Button as TechButton } from "@prompt-or-die/tech-ui"`. Better yet, **only import the `Tech*`-prefixed components** (which are the cyber/HUD ones we actually want); NEVER import the unprefixed `Button`, `Card`, `Input`, `Modal`, etc. — those are tech-ui's "ordinary shadcn-style" duplicates and we already have shadcn equivalents.

---

## 7. Compatibility risks with `@assistant-ui/react@0.10`

| Aspect | assistant-ui | tech-ui | Conflict? |
|---|---|---|---|
| Peer deps | React 18/19, no framer-motion | React 18/19, framer-motion 11 | None — additive. |
| `sideEffects` | `false` (good for tree-shake) | undefined (bad) | tech-ui hurts assistant-ui's tree-shaking only if they share imports — they don't. |
| Underlying primitives | Radix UI (`@radix-ui/react-popover`, `react-slot`, etc.) | Plain JSX, `clsx`, `tailwind-merge`, `framer-motion`, `lucide-react` | None — disjoint. |
| CSS scope | assistant-ui's `<Thread>` renders class names like `.aui-thread-root`, `.aui-message-*` and reads our `bg-background`, `text-foreground` Tailwind tokens | tech-ui uses identical Tailwind theme tokens (`bg-card`, `border-border`, etc.) | None — they share the SAME `--background`/`--primary`/`--foreground` variables. As long as our `globals.css` controls those, both render in our ocean-blue theme. |
| Markdown content | assistant-ui renders user content via `react-markdown` + `@assistant-ui/react-markdown` with our `.markdown-content` overrides | tech-ui doesn't ship a markdown renderer | None. |

**Verdict**: assistant-ui and tech-ui can **coexist safely**. The places where conflict could arise:
1. If we wrap an assistant-ui `<Thread>` inside a `TechCard` — fine, just nested DOM.
2. If we replace assistant-ui's tool-call renderers (`SKILL_RENDERERS` in `webui/src/secbot/tool-ui.tsx`) with `TechCard`-styled cards — fine, tool renderers are plain React.
3. If tech-ui's `globals.css` were imported (it's not) — would clobber `* { border-color: ... }` rule.

---

## 8. Production-readiness signals & red flags (consolidated)

### Green flags

- TypeScript declarations shipped (820 lines, all components typed, no obvious `any`).
- MIT license, npm-published, has provenance signature.
- Bundle is ESM + CJS dual-format with `"types"` field.
- Dependencies are mainstream (clsx, tailwind-merge, framer-motion, lucide-react).
- Tarball is small (97 kB) — won't bloat lockfile.

### Yellow flags

- Tailwind v4 syntax in `globals.css` while peer dep allows v3.4 — **inconsistent with claimed peer-dep range**.
- README example has minor inconsistency (`tailwind.config.ts` reference, but TS config is uncommon for tech-ui's stated audience).
- No `"sideEffects": false` in package.json — tree-shaking suboptimal.
- `framer-motion@^11.0.0` is one major behind current `12.x`; if we adopt 12.x elsewhere, peer-dep resolution may install BOTH 11 and 12 — bundle bloat.

### Red flags

- **Zero adoption signals**: 1 GitHub star, 0 issues, 0 PRs, 0 forks, 0 contributors besides author, 10 downloads/month.
- **Dormant repo**: 3 commits all on the release day, 5 months of silence.
- **Most "Layout" templates are non-functional demos** — `TechAgentWorkbench`, `TechGameHUD`, `TechGenGameLayout`, `TechSettingsLayout`, `TechAuthLayout`, `TechDashboardLayout`, `TechLandingLayout` all have type `({ className }: { className?: string }) => JSX.Element`. They contain hardcoded sample data (mock thoughts, mock files, mock messages). To use the visual design, we'd need to fork the source.
- **Hardcoded `#ff5800` orange** in 23 places in the bundle — non-trivial to override fully.
- **CSS variables `var(--primary)` and `var(--primary-rgb)` referenced in inline styles** — incompatible with our HSL component approach without compatibility shim.
- **No tests, no examples folder, no Storybook** — visual correctness must be verified after each upgrade.

---

## 9. Recommended integration recipes (3 approaches, with pros/cons)

### Recipe A — "Cherry-pick primitives, vendor-fork data-viz" (RECOMMENDED)

**Scope**: Adopt `TechFrame`, `TechCard`, `TechPanel`, `TechBadge`, `TechMetric`, `TechDonut`, `TechRadar`, `TechPhaseBar`, `TechThoughtChain`, `TechGlassPanel` from npm. Vendor-fork (copy source + adapt) `TechAgentWorkbench` and `TechGameHUD` since they're demo-only.

**Steps**:
1. `bun add @prompt-or-die/tech-ui framer-motion`.
2. Append `./node_modules/@prompt-or-die/tech-ui/dist/**/*.{js,ts,jsx,tsx}` to `tailwind.config.js → content`.
3. Add `success/warning/error/info` color tokens in `tailwind.config.js` and CSS vars in `webui/src/globals.css :root[data-theme="secbot"]`.
4. Copy the utility classes from tech-ui's `globals.css` (`.tech-frame`, `.glass`, `.text-glow`, `.animate-pulse-glow`, `.animate-fade-in`) into our `globals.css` under `@layer utilities` — **manually adapted**, since the original uses Tailwind v4 directives.
5. For data-viz components (`TechRadar`, `TechDonut`, `TechChart`, `TechNeuralMesh`), always pass `color={oceanBlueHex}` per use-site.
6. For `TechAgentWorkbench`-style HUD: vendor-copy the source from `dist/index.js` lines 3208–3346 into a new file (e.g. `webui/src/secbot/components/AgentWorkbench.tsx`), strip orange literals, accept real data props, wire up to our chat runtime.
7. Feature-flag the whole secbot tech-ui surface behind `useTechUI` (env or per-user pref) for one-click rollback.

**Pros**: low blast radius; preserves all of shadcn/assistant-ui; reasonable bundle cost (~50 kB gzip); orange literals only ship on hover effects of components we DON'T use.

**Cons**: dual-source for some components (npm + vendored); need to chase upstream if it ever updates (unlikely given dormancy).

### Recipe B — "Cherry-pick UI primitives only, build our own data-viz"

**Scope**: Adopt only `TechFrame`, `TechCard`, `TechPanel`, `TechBadge`, `TechMetric`, `TechGlassPanel`. Use **recharts** (already in our deps) for charts/donuts/radars instead of `TechRadar`/`TechDonut`/`TechChart`. Use Radix UI for any HUD interaction.

**Pros**: minimal exposure to the unmaintained library (~10 kB gzip after tree-shake); zero framer-motion dependency since none of these components use it; no orange-literal pollution.

**Cons**: misses the most visually distinctive parts (radar sweep, neural mesh, biometric scanner). The "wow" factor of the upgrade comes from those.

### Recipe C — "Wholesale adopt TechAdminLayout as shell"

**Scope**: Replace `webui/src/App.tsx` and `webui/src/secbot/SecbotShell.tsx` with `TechAdminLayout` from tech-ui.

**Pros**: maximal visual coherence with tech-ui's design language.

**Cons**: `TechAdminLayout` accepts only `className`, `brand`, `sidebarItems`, `commandOptions`, `user`, `onLogout` — **not** real children/routing. Our 4-tab info architecture (chat/assets/scans/reports) doesn't fit cleanly. Would force a rewrite of secbot routing. Demo-grade quality. **Strongly discouraged.**

### Recipe D (fallback) — "Don't adopt the package; rebuild the visual language ourselves"

If the integration headaches above (Tailwind v4 globals.css, hardcoded orange, demo-only layouts) prove too costly, replicate the look with:
- `framer-motion` directly.
- Tailwind plugin for "tech-frame" corner styles (10 lines of CSS).
- recharts for charts/radials/radar (already in deps).
- lucide-react icons (already in deps).

This avoids the 0.0.1 / 1-star / 5-month-dormant supply-chain risk entirely, at the cost of building 6–8 small components ourselves (~1–2 days of work).

**Final recommendation**: start with **Recipe A**, but do an early time-boxed spike (1 day) to validate that the cherry-picked components (a) tree-shake to a reasonable size, (b) accept ocean-blue color overrides without leaking orange, and (c) coexist cleanly with `<Thread>` inside `SecbotShell`. If any of those fail, fall back to **Recipe D**.

---

## Caveats / Not Found

- bundlephobia API was rate-limited (429) during research; framer-motion gzip estimate (30–35 kB) is from prior knowledge of v11 + the package's known shipped subset, not a live measurement. Verify with `bun run build && du -h dist/assets/*.js` after integration.
- Could not run `bun run build` here to produce an actual production bundle size — node_modules is not installed in this checkout.
- Did not exhaustively read every component; spot-checked TechFrame, TechCard, TechRadar, TechPhaseBar, TechThoughtChain, TechDonut, TechAgentWorkbench, TechGlassPanel.
- npm download counts are very low (single-digit weekly). The package may show up as unmaintained on Snyk/socket.dev — would be worth running `bun pm audit` and `socket` security checks before merge.
- The author "dexploarer" appears to have no other published packages under the `@prompt-or-die` scope on npm based on the org URL claimed in README — could not verify org existence due to GitHub API rate limit on the orgs endpoint. Consider that the package may be removed/unpublished on a whim; pin to exact version `0.0.1` in `package.json`.

## Files inspected

- `/Users/shan/Downloads/nanobot/webui/package.json` (existing deps)
- `/Users/shan/Downloads/nanobot/webui/tailwind.config.js` (existing Tailwind v3 config)
- `/Users/shan/Downloads/nanobot/webui/src/globals.css` (existing shadcn HSL token system + secbot theme)
- `/Users/shan/Downloads/nanobot/webui/src/secbot/SecbotShell.tsx` (4-tab shell)
- `/Users/shan/Downloads/nanobot/webui/src/secbot/SecbotThread.tsx` (assistant-ui Thread wrapper)
- `/tmp/tech-ui-inspect/package/package.json` (extracted tarball)
- `/tmp/tech-ui-inspect/package/dist/index.js` (211 kB ESM bundle, full read)
- `/tmp/tech-ui-inspect/package/dist/index.d.ts` (820 lines of type declarations)
- `/tmp/tech-ui-inspect/package/globals.css` (Tailwind v4 `@theme` block)
- `/tmp/tech-ui-inspect/package/README.md` (5 kB official doc)

## External references

- npm registry: <https://www.npmjs.com/package/@prompt-or-die/tech-ui>
- GitHub repo: <https://github.com/Dexploarer/prompt-or-die-tech-ui>
- npm download stats API: `https://api.npmjs.org/downloads/point/last-{week,month}/@prompt-or-die/tech-ui`
- `npm pack --dry-run @prompt-or-die/tech-ui` → 8 files, 97 kB tar / 525 kB unpacked
