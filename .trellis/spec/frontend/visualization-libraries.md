# Visualization Libraries

> Closed whitelist for chart / graph / timeline rendering in `webui/`.
> Origin: research/cybersec-ui-patterns.md §4.

---

## 1. Allowed Libraries

| Use case | Library | Reason |
|----------|---------|--------|
| Asset / network topology | `react-flow` | First-class React, custom node/edge as React components, fits secbot's 3-layer "asset → service → vuln" graph. |
| Severity / KPI charts | `recharts` | Native fit for shadcn chart blocks (which wrap recharts), small bundle, dashboard-ready. |
| Plan-step timeline | Hand-rolled `<ol>` + Tailwind | The plan-step list is a vertical "step + status + sub-tree" view, not a true time axis. shadcn `Steps` block is the reference pattern. |
| Progress bar | shadcn `<Progress>` | Use `indeterminate` mode while streaming, switch to determinate on completion. |

---

## 2. Banned Libraries

The following are **not allowed** and will be flagged in PR review. Adding them requires a spec amendment with a measured rationale (bundle delta + screenshot of feature impossible with the whitelist).

- ❌ `cytoscape.js` — graph engine is non-React, integration cost outweighs algorithm gains for a 3-layer graph.
- ❌ `nivo` — ~3× recharts bundle, no shadcn integration.
- ❌ `Chart.js` — duplicates recharts capability without React-first ergonomics.
- ❌ `visx` — overkill for the plan-step list; we are not rendering true timelines.
- ❌ `vis-timeline` — same reason as visx, plus larger surface.
- ❌ `d3` direct usage in components — fine as a transitive dep of recharts, banned as a top-level import.
- ❌ Any new "AI-generated chart" lib that has not appeared in this whitelist.

---

## 3. Bundle Discipline

- The whitelist MUST be enforced via `package.json` direct deps. CI should fail when a banned package shows up in `webui/package.json` direct dependencies (not transitive).
- Pin versions exactly (no `^` / `~`) for `react-flow` and `recharts` in `package.json` until a routine upgrade PR.
- Tree-shake-friendly imports only: `import { LineChart } from 'recharts'`, never `import * as Recharts from 'recharts'`.

---

## 4. When the Whitelist Is Insufficient

Open a PR that:

1. Modifies this spec (`§1` adds the new entry, `§2` removes the ban if applicable).
2. Includes `bundle-analyzer` before/after numbers.
3. Demonstrates the requirement cannot be met by composing the existing whitelist (e.g. recharts + custom SVG overlay).
4. Receives review approval from the frontend lead before any component import lands.

---

## 5. Pre-Implementation Checklist

- [ ] Confirmed the chart/graph requirement maps to a library in §1.
- [ ] No new dependency would be introduced; if so, jumped to §4 first.
- [ ] Imports are named (not wildcard) for tree-shaking.
- [ ] If using `react-flow`, custom nodes consume tokens from [theme-tokens.md](./theme-tokens.md), not raw colors.
