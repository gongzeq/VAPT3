# Frontend Development Guidelines

> Spec for `webui/` (React + Vite + Tailwind + shadcn/ui + assistant-ui).
> Sourced from `.trellis/tasks/05-07-cybersec-agent-platform/research/cybersec-ui-patterns.md` (R8 调研结论已固化为契约).

---

## Scope

These guidelines bind every PR that touches `webui/src/**`. They define **non-negotiable constraints** for theming, message rendering, and visualization library choice. Behavior or visual changes that violate them require a spec amendment first.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [WebUI Design](./webui-design.md) | Navigational hub: view hierarchy, assistant-ui integration, sub-spec map | Active |
| [Theme Tokens](./theme-tokens.md) | CSS variables, primary = 海蓝 `#1E90FF`, severity palette | Active |
| [Component Patterns](./component-patterns.md) | MessageBubble 三件套, tool-call rendering, destructive AlertDialog | Active |
| [Visualization Libraries](./visualization-libraries.md) | Chart/diagram library whitelist (react-flow + recharts only) | Active |

### Cross-Layer Contracts (consumed by `webui/`)

These are owned by the backend but bind the frontend wire format. Any UI change driven by these MUST be paired with the backend PR.

| Contract | Why frontend cares |
|----------|--------------------|
| [websocket-protocol.md](../backend/websocket-protocol.md) | All streaming events the chat surface consumes |
| [scan-lifecycle.md](../backend/scan-lifecycle.md) | State labels and transitions rendered in the plan timeline |
| [high-risk-confirmation.md](../backend/high-risk-confirmation.md) | `risk_level` enum + `ask_user` payload that drives the AlertDialog |

---

## Hard Rules (apply to every PR)

1. **No raw hex / rgb in component code.** Always reference Tailwind semantic class or `hsl(var(--token))`. New tokens go in [theme-tokens.md](./theme-tokens.md) first, then `globals.css`.
2. **No new chart / graph library.** If the requirement is not covered by react-flow or recharts, open a spec PR before adding the dependency.
3. **Tool-call rendering goes through `assistant-ui` `toolUI` registry.** Skill-specific renderers must register by skill name; do not branch inside a single mega-component.
4. **Destructive actions use shadcn `<AlertDialog destructive>` with the structure in [component-patterns.md §3](./component-patterns.md#3-destructive-confirmation-dialog), OR the inline `.approval` card variant per [§3.3](./component-patterns.md#33-inline-approval-variant) for sub-agent high-risk confirmations.** Both variants MUST satisfy anti-misclick constraints. No other custom modal for destructive flows.

---

## Authoring Conventions

- **Language**: English for guideline prose; Chinese is allowed for inline product/brand terms (e.g. 海蓝, 严重度) or quoted decisions to preserve meaning from the original research.
- **Examples**: When citing values that come from the research doc, link back to the section so future readers can audit the rationale.
- **Updates**: Use `trellis-update-spec` when a debugging session, code review, or new research changes any rule here. Do **not** silently edit—record what changed and why.

---

## Pre-Implementation Checklist

Before writing or modifying frontend code:

- [ ] Pulled latest [theme-tokens.md](./theme-tokens.md); will not introduce raw hex.
- [ ] Confirmed the component fits an existing pattern in [component-patterns.md](./component-patterns.md), or explicitly extending it.
- [ ] Required charts/graphs are achievable with the libraries listed in [visualization-libraries.md](./visualization-libraries.md).
- [ ] If the change is destructive (deletes data, runs intrusive scan), reviewed [§3 destructive dialog](./component-patterns.md#3-destructive-confirmation-dialog).
