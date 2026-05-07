# Research: Customizing `@assistant-ui/react@^0.10.0` for Tech-HUD + Ocean-Blue

- **Query**: How to customize the appearance of `@assistant-ui/react@^0.10.0` Thread / Composer / Message components without forking, so the secbot chat surface can match a "tech HUD + ocean blue" aesthetic and host `@prompt-or-die/tech-ui` primitives (TechCard / TechFrame / TechGlassPanel) inside chat messages and tool-call cards.
- **Scope**: external (assistant-ui docs + npm tarball inspection) + internal (`webui/src/secbot/*`)
- **Date**: 2026-05-07
- **Target version**: `@assistant-ui/react@^0.10.0` resolves to `0.10.0` … `0.10.50` on npm (April 20, 2025 – September 5, 2025). `0.11.0` was released 2025-09-08, and the current latest is `0.14.0` (2026-05-07). Anything documented below as v0.10-specific is verified against the v0.10.0 dist tarball and the v0.10.50 GitHub source tag. Anything documented as v0.10+ remains valid because no breaking change in 0.10.x removed it.

---

## TL;DR — What v0.10 actually exports

Verified from `npm pack @assistant-ui/react@0.10.0` and `@0.10.50`. **`@assistant-ui/react@0.10.x` does NOT export a styled `<Thread>` component** (that was last shipped in v0.7.x as `_default$3 as Thread` from `dist/ui`; it was removed in v0.8 and never returned). v0.10 exports only:

| Surface | What you get |
|---|---|
| Runtime providers / hooks | `AssistantRuntimeProvider`, `TextContentPartProvider`, `useLocalRuntime`, `useExternalStoreRuntime`, `useChatRuntime`, `useAssistantTool`, `useAssistantToolUI`, `makeAssistantTool`, `makeAssistantToolUI`, `useThreadViewportAutoScroll`, plus all `useContentPart*` hooks. |
| Primitives (namespaces) | `ThreadPrimitive`, `ThreadListPrimitive`, `ThreadListItemPrimitive`, `MessagePrimitive`, `ContentPartPrimitive` (alias of `MessagePartPrimitive` in 0.11+), `ComposerPrimitive`, `AttachmentPrimitive`, `BranchPickerPrimitive`, `ActionBarPrimitive`, `AssistantModalPrimitive`. |
| Types | `ToolCallContentPartComponent`, `ToolCallContentPartProps`, `ChatModelAdapter`, `ChatModelRunOptions`, `ChatModelRunResult`, `ThreadMessageLike`, etc. The `*ContentPart*` aliases are deprecated in favor of `*MessagePart*` but still re-exported. |

Styled components are **owned by the consumer**: you generate them via `npx assistant-ui@latest add thread` (or shadcn-style: `npx shadcn@latest add https://r.assistant-ui.com/thread.json`). The CLI drops `components/assistant-ui/thread.tsx` (and `tool-fallback.tsx`, `markdown-text.tsx`, `reasoning.tsx`, `tool-group.tsx`, …) into your repo and you edit them directly.

> **Critical caveat** — `webui/src/secbot/SecbotThread.tsx:5` does `import { AssistantRuntimeProvider, Thread } from "@assistant-ui/react";`. **`Thread` is not in the v0.10.x public API.** The signature `<Thread tools={SKILL_RENDERERS} components={{ ToolFallback: ToolCallCard }} />` does not match any officially shipped Thread component (v0.5's `<Thread config={...}>` only takes `ThreadConfig`; never had `tools` or `components.ToolFallback`). Either (a) the file currently fails to type-check, (b) bun is hoisting an older (≤0.7) cached version, or (c) the codebase has a private patch. Item 4 below covers the migration. Treat `<Thread tools={...}>` as folklore, not contract.

---

## 1) `<Thread>` slot enumeration in v0.10

There are two distinct "slot" surfaces. Don't conflate them.

### 1.1 `ThreadPrimitive.Messages` — message-role slots

Source: `packages/react/src/primitives/thread/...` at the v0.10.50 tag. Modern v0.10+ docs at <https://www.assistant-ui.com/docs/primitives/thread>.

Two equivalent ways to dispatch on message role:

```tsx
// Slot map (still supported in 0.10, deprecated in 0.13+)
<ThreadPrimitive.Messages
  components={{
    Message,         // default for any role
    UserMessage,
    EditComposer,    // shown when message.composer.isEditing
    AssistantMessage,
    SystemMessage,
  }}
/>

// Children render fn (the v0.10 forward-compatible style)
<ThreadPrimitive.Messages>
  {({ message }) => {
    if (message.composer.isEditing) return <MyEditComposer />;
    if (message.role === "user")    return <MyUserMessage />;
    return <MyAssistantMessage />;
  }}
</ThreadPrimitive.Messages>
```

`ThreadPrimitive.MessageByIndex` accepts the same `components` shape and renders only one message — useful for plan-timeline-style "first message" pinning.

### 1.2 `MessagePrimitive.Content` — content-part slots (THE one you want)

Verified from the v0.10.0 tarball at `dist/primitives/message/MessageContent.js.map`. The full type is:

```ts
type MessagePrimitiveContentProps = {
  components?: {
    Empty?:           EmptyContentPartComponent;
    Text?:            TextContentPartComponent;
    Reasoning?:       ReasoningContentPartComponent;
    Source?:          SourceContentPartComponent;
    Image?:           ImageContentPartComponent;
    File?:            FileContentPartComponent;
    Unstable_Audio?:  Unstable_AudioContentPartComponent;
    tools?:
      | { by_name?: Record<string, ToolCallContentPartComponent>;
          Fallback?: ComponentType<ToolCallContentPartProps>; }
      | { Override:  ComponentType<ToolCallContentPartProps>; };
  };
};
```

Resolution order for tool-call parts (v0.10):
1. `tools.Override` if provided — handles **all** tool calls, ignores everything else.
2. Globally-registered renderer (via `makeAssistantToolUI` / `useAssistantToolUI` keyed by `toolName`).
3. `tools.by_name[part.toolName]` from this `MessagePrimitive.Content` instance.
4. `tools.Fallback` from this instance.
5. Renders nothing.

In v0.13+ this is exposed declaratively via `MessagePrimitive.Parts`'s render-fn `({ part }) => part.toolUI ?? <MyFallback {...part} />`, but that API does not exist in v0.10.

### 1.3 The composer + thread shadcn template

The CLI registry (`https://r.assistant-ui.com/registry.json` → `thread.json`) currently serves a v0.13-flavoured template that uses `AuiIf` and `useAuiState`, both of which **are NOT exported from v0.10.x** (`AuiIf` arrived in 0.11). For a v0.10 project, the safer reference is the official primitives + the legacy slots above. Concretely:

```tsx
<ThreadPrimitive.Root>
  <ThreadPrimitive.Viewport autoScroll>
    <ThreadPrimitive.Empty>
      <Welcome />
    </ThreadPrimitive.Empty>

    <ThreadPrimitive.Messages
      components={{
        UserMessage,        // slot 1
        EditComposer,       // slot 2
        AssistantMessage,   // slot 3
        SystemMessage,      // slot 4
      }}
    />

    <ComposerPrimitive.Root>...</ComposerPrimitive.Root>
  </ThreadPrimitive.Viewport>
</ThreadPrimitive.Root>
```

`ThreadPrimitive.Empty` exists in v0.10 (deprecated only in 0.13). `AuiIf` is not available; use it only after upgrading.

### Documentation URLs (current site, all sections valid for v0.10 except where flagged)

- Thread primitive — <https://www.assistant-ui.com/docs/primitives/thread> (the v0.10 API is at the bottom of the page; `Empty`, `If` blocks documented as deprecated still work in v0.10).
- Message primitive — <https://www.assistant-ui.com/docs/primitives/message> (`MessagePrimitive.Content` slot map covered above; `MessagePrimitive.Parts` render-fn requires v0.11+).
- Composer primitive — <https://www.assistant-ui.com/docs/primitives/composer>.
- Generative UI — <https://www.assistant-ui.com/docs/guides/tool-ui> (the `makeAssistantToolUI` flow is unchanged from v0.10).
- Tool UI fallback — <https://www.assistant-ui.com/docs/ui/tool-fallback>.
- Architecture overview — <https://www.assistant-ui.com/docs/architecture>.

---

## 2) Theming model: are CSS vars / Tailwind / data-attrs enough to repaint globally?

### 2.1 What the library ships

- **No Tailwind plugin in `@assistant-ui/react@0.10`.** A separate Tailwind v4 plugin (`@assistant-ui/react-ui/tailwindcss`) exists in the broader ecosystem, but the user's webui is pinned to Tailwind 3.4 (`webui/package.json` line 39), so that path is closed.
- **`tw-shimmer`** — Tailwind v4 only. Cannot be used until Tailwind upgrades to v4. Equivalent shimmer must be hand-rolled (CSS keyframes + a single class) or sourced from the existing `tailwindcss-animate` plugin.
- The library's primitives **render plain HTML elements** (`<div>`, `<button>`, `<form>`, `<textarea>`) with no inline styles; ALL visual styling lives in your shadcn-style template files under `components/assistant-ui/*.tsx`.

### 2.2 What the templates expose for global targeting

The shadcn-style `thread.tsx` template (and the older v0.10-era ones) emit two stable hook surfaces every theme can target:

1. **`aui-*` class names** on every meaningful element. Examples from the current registry:
   - `aui-thread-root`, `aui-thread-viewport-footer`, `aui-thread-welcome-root`
   - `aui-thread-welcome-suggestions`, `aui-thread-welcome-suggestion`
   - `aui-composer-root`, `aui-composer-input`, `aui-composer-send`, `aui-composer-cancel`, `aui-composer-action-wrapper`
   - `aui-assistant-action-bar-root`, `aui-action-bar-more-content`
   - `aui-message-error-root`, `aui-message-error-message`
   These are intentional documentation hooks. You can target them globally from `globals.css`, e.g.:
   ```css
   :root[data-theme="secbot"] .aui-composer-root {
     border-radius: 12px;
     background: hsl(var(--card));
     box-shadow: 0 0 0 1px hsl(var(--border)), 0 0 24px hsl(var(--primary) / 0.18) inset;
   }
   ```

2. **`data-slot` and `data-role` attributes**. Confirmed in the latest template:
   - `data-slot="aui_composer-shell"`, `data-slot="aui_thread-viewport"`
   - `data-slot="aui_assistant-message-root"`, `data-slot="aui_assistant-message-content"`, `data-slot="aui_assistant-message-footer"`
   - `data-slot="aui_chain-of-thought"`, `data-slot="aui_message-group"`
   - `data-role="assistant" | "user"` on `MessagePrimitive.Root`
   - `MessagePrimitive.Root` automatically sets `data-message-id` and tracks hover state for `ActionBarPrimitive` autohide.
   - The `ComposerPrimitive.AttachmentDropzone` sets `data-dragging="true"` while a file is dragged in.

   Style with attribute selectors:
   ```css
   [data-role="assistant"] { /* shared assistant bubble base */ }
   [data-slot="aui_composer-shell"][data-dragging="true"] { /* drop affordance */ }
   ```

3. **CSS custom properties** declared inline on the template. The current template sets `--thread-max-width: 44rem` and `--composer-radius: 24px` on `ThreadPrimitive.Root`. You can change them per-theme by editing the template, or override them by name in your `globals.css`.

### 2.3 What the library does NOT provide

- No global "skin" prop on `<Thread>`. There is no theme runtime; nothing analogous to a `ThemeProvider` for visuals.
- No CSS variable tokens shipped from the library itself. The `--background`, `--foreground`, `--primary`, `--muted`, `--ring`, `--destructive` tokens you currently see in templates come from **shadcn/ui's** `globals.css` baseline. They live in your repo (already at `webui/src/globals.css` per the PRD).
- No Tailwind preset to repaint the whole Thread without touching the template. **Slot-by-slot edits in `components/assistant-ui/*.tsx` are the canonical path** if you want guaranteed v0.10/v0.11 forward-compat.

**Practical answer to Q2**: A "global repaint" in v0.10 is a combination of (i) Tailwind tokens in `globals.css` (already done — 海蓝 `#1E90FF` is wired), (ii) targeting `aui-*` classes / `data-slot` attributes from a `:root[data-theme="secbot"]` scope for HUD-only adjustments, and (iii) editing the user-owned `thread.tsx` / `tool-fallback.tsx` templates for any change that needs new DOM. There is no zero-edit path.

---

## 3) Injecting custom UI into the message stream (e.g., a "thought-chain" panel above the assistant message)

### 3.1 Three integration points in v0.10

1. **Per-role wrapper inside `<ThreadPrimitive.Messages components={{ AssistantMessage }}>`.**  Your `AssistantMessage` component sees the full message scope and can render anything before/after `<MessagePrimitive.Content />`. This is the cleanest way to inject a "thought chain" header that lives outside the bubble.

   ```tsx
   const AssistantMessage: FC = () => {
     const planSteps = usePlanForCurrentMessage(); // your own hook reading runtime state
     return (
       <MessagePrimitive.Root data-role="assistant" className="…">
         {planSteps && <ThoughtChainPanel steps={planSteps} />}
         <MessagePrimitive.Content components={{ Text, tools: { by_name: SKILL_RENDERERS, Fallback: ToolFallback } }} />
       </MessagePrimitive.Root>
     );
   };
   ```

2. **Custom `Reasoning` slot.** v0.10 already supports a `reasoning` content part (e.g. emitted by `o1` / `o4-mini` via the AI SDK's reasoning stream). Provide a `Reasoning` component in `components` to render reasoning text as an inline collapsible — this gives you "thought-chain" styling for free if your runtime emits reasoning parts. The user's secbot runtime currently emits only `text` and `tool-call` parts, so this slot is unused unless you start emitting `reasoning` parts on the WebSocket.

3. **Reserved data parts (`MessagePartPrimitive` `data` parts).** v0.10 supports custom data parts in the message stream. They appear as part of `useContentPart()` and can be rendered via the `Empty` / generic slots, but the dedicated `data.by_name[partName]` slot only landed in v0.11+. For v0.10, you have to dispatch yourself (custom `tools.Override` that switches on `part.type === "data"` is not supported because `Override` only fires for `tool-call` parts). Easiest in v0.10: render the thought chain at the message-component level, not the part level.

### 3.2 Existing Trellis spec constraint

`.trellis/spec/frontend/component-patterns.md §1` already locks the chat bubble to **three** sub-components (`ToolCallCard`, `ScanResultTable`, `PlanTimeline`) and says "any new skill output must extend an existing slot, not introduce a fourth top-level type." A thought-chain panel matches `<PlanTimeline>` (already designated for "plan → invoke → observe → iterate"). So injecting it goes in two layers:

- **Inside `AssistantMessage`** before `<MessagePrimitive.Content />` for the orchestrator's reasoning header.
- **As the `tool-call` renderer for `report-*` skills** (where the chain is part of the tool's structured output), via the existing `SKILL_RENDERERS` map.

No spec amendment needed.

---

## 4) Tool-call rendering — confirming `tools={SKILL_RENDERERS}` and the partial-args streaming contract

### 4.1 `ToolCallContentPartComponent` contract (v0.10)

Verified from `webui/src/secbot/renderers/_shared.tsx` and the v0.10.0 tarball:

```ts
type ToolCallContentPartProps<TArgs = unknown, TResult = unknown> = {
  type: "tool-call";
  toolCallId: string;
  toolName: string;
  args: TArgs;
  argsText: string;          // partial JSON during streaming
  result?: TResult;          // present once the tool returns
  status: { type: "running" | "complete" | "incomplete" | "requires-action" };
  addResult: (result: TResult) => void;  // for human-in-the-loop / runs that yield back
};

type ToolCallContentPartComponent<TArgs = unknown, TResult = unknown> =
  ComponentType<ToolCallContentPartProps<TArgs, TResult>>;
```

The v0.10 dist also re-exports `ToolCallContentPartComponent` as `ToolCallMessagePartComponent` (the new name). Both work in v0.10; the alias is officially marked "TODO remove in v0.11" inside the source.

### 4.2 Three valid registration paths in v0.10

| Path | When to use | API surface |
|---|---|---|
| **(A) `MessagePrimitive.Content components={{ tools: { by_name, Fallback } }}`** | Per-message inline override — what the user's existing `<Thread tools=… />` mock-up tries to use. The actual prop lives on `MessagePrimitive.Content`, not on `<Thread>`. | Local to the assistant message component. |
| **(B) `makeAssistantToolUI({ toolName, render })` mounted under `AssistantRuntimeProvider`** | Global registry, fits the existing `SKILL_RENDERERS` registry pattern. The renderer receives the same `ToolCallContentPartProps`. | Returns a "null component" you mount once near the runtime provider; lookup is by `toolName` at render time. |
| **(C) `MessagePrimitive.Content components={{ tools: { Override } }}`** | One renderer for ALL tool calls. Use only if you want a uniform "tech HUD card" wrapper that internally switches on `toolName`. | Mutually exclusive with `by_name` / `Fallback`. |

The current secbot code uses path (A) shape but on the wrong component. The minimum-change fix is to keep `SKILL_RENDERERS` and pass it to `MessagePrimitive.Content` inside the user-owned `AssistantMessage` component (see §9 below).

### 4.3 Partial-streaming behavior

`argsText` is updated incrementally as the model streams tokens. The renderer is re-mounted on every parse — but `args` is only repopulated once the parser sees a complete JSON object for that field. For partial-state UI you have two options:

- Use `argsText` directly (e.g., show the raw command string as it streams).
- Use the v0.10 helper `INTERNAL.unstable_useToolArgsFieldStatus` (exported as `unstable_useToolArgsFieldStatus` from v0.8+, available in 0.10) which yields `{ status: "running" | "complete", value }` per top-level field. This is what nuclei / nmap renderers want when they need to show "scanning host X" mid-stream.

Status transitions (`status.type`):
1. `"running"` — tool is executing; `result` is undefined.
2. `"complete"` — `result` is fully populated.
3. `"incomplete"` — model produced a tool call but the run was aborted.
4. `"requires-action"` — human-in-the-loop; the renderer can call `addResult({ status: "user_denied" })` to satisfy the spec's destructive-confirmation contract (`.trellis/spec/frontend/component-patterns.md §3.2`).

### 4.4 Confirmation: is `tools={SKILL_RENDERERS}` v0.10-blessed?

**Yes for the prop shape, no for the prop location.** The shape `Record<toolName, ToolCallContentPartComponent>` matches `tools.by_name`. The location must be `MessagePrimitive.Content` (path A) or registered via `makeAssistantToolUI` (path B). The `<Thread>` styled component in v0.10 has no `tools` prop in any version actually shipped on npm. So:

- Keep `webui/src/secbot/tool-ui.tsx` (the registry) as-is — its type `Record<string, ToolCallContentPartComponent>` is correct.
- Move the consumption from `<Thread tools={SKILL_RENDERERS}>` into a user-owned `AssistantMessage` that calls `<MessagePrimitive.Content components={{ tools: { by_name: SKILL_RENDERERS, Fallback: ToolCallCard } }} />`.

---

## 5) Composer customization with TechInput / TechFrame styling

### 5.1 The `asChild` pattern is the golden path

`ComposerPrimitive.{Root, Input, Send, Cancel, AddAttachment, AttachmentDropzone, Dictate, StopDictation}` all accept `asChild`. With `asChild`, the primitive merges its props/refs/keyboard handling onto your child element instead of rendering its own. This is exactly what you want for `@prompt-or-die/tech-ui`'s `TechInput` and `TechFrame`:

```tsx
import { ComposerPrimitive } from "@assistant-ui/react";
import { TechFrame, TechInput, TechIconButton } from "@prompt-or-die/tech-ui";

const TechComposer: FC = () => (
  <ComposerPrimitive.Root asChild>
    <TechFrame variant="composer">
      <ComposerPrimitive.Input asChild>
        <TechInput placeholder="Send a recon directive…" rows={1} />
      </ComposerPrimitive.Input>

      <div className="flex items-center justify-between">
        <ComposerPrimitive.AddAttachment asChild>
          <TechIconButton icon="paperclip" tooltip="Attach evidence" />
        </ComposerPrimitive.AddAttachment>

        <ComposerPrimitive.Send asChild>
          <TechIconButton icon="arrow-up" variant="primary" tooltip="Send" />
        </ComposerPrimitive.Send>
      </div>

      {/* 0.10 has no <AuiIf>, so wire the Send/Cancel toggle via a useThreadIf / useThreadContext check, or render both and rely on the disabled state forwarded by primitives. */}
      <ComposerPrimitive.Cancel asChild>
        <TechIconButton icon="square" tooltip="Stop generating" />
      </ComposerPrimitive.Cancel>
    </TechFrame>
  </ComposerPrimitive.Root>
);
```

What you keep when you swap the look:
- Keyboard shortcuts (Enter to send, Shift+Enter newline, Esc to cancel/edit).
- Disabled-while-running state (`Send` becomes disabled when the runtime reports `isRunning`).
- Attachment file-picker wiring (`AddAttachment`).
- Drop-zone `data-dragging` toggling on `AttachmentDropzone`.

### 5.2 Runtime hooks the secbot code already relies on

`webui/src/secbot/runtime.ts` already uses `useLocalRuntime(buildAdapter(...))` from v0.10. That hook output goes into `<AssistantRuntimeProvider runtime={runtime}>`. Nothing else in the runtime needs to change.

For **streaming-state visibility** in your TechFrame border, read the thread state via the v0.10 hook `useThreadIf` or the lower-level `useThreadContext`/`useThread` with a selector — both exported from v0.10. These return `running: boolean`, which you can forward to a `TechFrame variant={running ? "active" : "idle"}` prop.

---

## 6) Streaming UX — "thinking…" indicators, partial-token shimmer, animated typing cursor

### 6.1 Built-in to v0.10

- **`MessagePartPrimitive.InProgress`** wraps children that should appear only while the part is still streaming. The default `Text` renderer in `MessageContent` shows `" ●"` after the streaming text. To swap the cursor for a TechHUD glyph:
  ```tsx
  const TechText: TextContentPartComponent = () => (
    <p className="whitespace-pre-line text-foreground">
      <ContentPartPrimitive.Text />
      <ContentPartPrimitive.InProgress>
        <span aria-hidden className="ml-0.5 inline-block size-2 translate-y-px rounded-sm bg-primary shadow-[0_0_8px_hsl(var(--primary))] animate-pulse" />
      </ContentPartPrimitive.InProgress>
    </p>
  );
  ```
  (`ContentPartPrimitive` is the v0.10 namespace; it is aliased to `MessagePartPrimitive` in 0.11+.)

- **Tool-call status** is piped through the `status.type` prop to every `ToolCallContentPartComponent`. Existing renderers (`webui/src/secbot/renderers/nmap-port-scan.tsx:23-72`) already read `result.status` from the structured payload; they should also branch on the `status.type` === `"running"` to show a HUD spinner before any structured result arrives.

- **`useThreadIf({ running: true })`** lets you mount a global "thinking…" footer that lights up while any run is active.

### 6.2 Shimmer for incoming tokens

`tw-shimmer` is the official path but it's Tailwind **v4 only** (the package's `@import "tw-shimmer"` syntax is the v4 plugin form). The webui is on Tailwind 3.4, so:

- Hand-roll the keyframes in `globals.css`:
  ```css
  @keyframes hud-shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  .hud-shimmer {
    background-image: linear-gradient(
      110deg,
      hsl(var(--primary) / 0.06) 0%,
      hsl(var(--primary) / 0.18) 50%,
      hsl(var(--primary) / 0.06) 100%
    );
    background-size: 200% 100%;
    animation: hud-shimmer 1.4s linear infinite;
  }
  ```
  Apply to `<MessagePartPrimitive.InProgress>` wrappers and to running tool cards.

- Or pull `@prompt-or-die/tech-ui`'s `TechShimmerOverlay` if it exists (PRD says `TechAgentWorkbench` includes shimmer effects). The PRD already lists `framer-motion` as a required peer dep for tech-ui — see §8 for compatibility.

### 6.3 Animated typing cursor

The default `●` blinking cursor is built into the v0.10 default Text renderer (line 85 of the inspected `dist/primitives/message/MessageContent.js.map`). To replace it without losing in-progress detection, do not omit `InProgress`; just swap its children to an animated SVG glyph or a `motion.span`.

---

## 7) Light vs dark mode handling

### 7.1 What the library does (and doesn't)

`@assistant-ui/react@0.10` ships **no theme of its own**. The CSS values it uses come from Tailwind utility classes inside the user-owned templates (`bg-background`, `text-foreground`, `border`, `bg-muted`, `text-muted-foreground`, `bg-destructive/10`, `ring-ring/20`, …). All of those are shadcn/ui semantic tokens.

The webui already has the matching tokens defined in `webui/src/globals.css` under `:root[data-theme="secbot"]`. Light mode currently inherits the shadcn defaults (per the PRD it's "中性灰"). Dark vs light switching works the way you've already wired it: the CSS variables under `:root[data-theme="secbot"]` (or a `dark` class — depending on what `@/components/ThemeProvider` does) drive the Tailwind tokens, which the assistant-ui templates consume. **The library never reads color values directly; it only forwards Tailwind classes.**

### 7.2 Forward-compat caveat with the v0.13 thread template

If you bring in the latest `npx assistant-ui add thread`, that template uses Tailwind v4 nested-syntax (`bg-(--composer-radius)`, `text-foreground/80`, `@container @md:` queries). Tailwind 3.4 does not support the `(--var)` shorthand or the `@container` syntax without the JIT plugin. **Stick with a v0.10-compatible custom template** (the legacy registry version) until/unless the webui upgrades Tailwind.

### 7.3 WCAG AA on the secbot palette

Existing Trellis spec `.trellis/spec/frontend/theme-tokens.md` is the binding contract. New aui-targeted styles should:
- Reference tokens via `hsl(var(--token))` rather than hex (already enforced as Hard Rule 1).
- Re-use `--severity-*` tokens for status-coded badges so the contrast review only happens once.

No assistant-ui-specific contrast adjustment is needed beyond what shadcn/ui's defaults give you.

---

## 8) framer-motion compatibility with the assistant-ui scroll/render cycle

### 8.1 What assistant-ui does internally (relevant to motion)

- `ThreadPrimitive.Viewport` runs an auto-scroll loop: on each `thread.runStart` it scrolls to the bottom; on each new message it scrolls to bottom **only if the user was already at the bottom**. This is plain JS scroll math, no Web Animations involved.
- `MessagePrimitive.Root` registers itself as the "top-anchor" target only when `turnAnchor="top"` is set (v0.13+). v0.10's Viewport always anchors to the bottom.
- `ActionBarPrimitive` autohide uses CSS transitions on opacity, not framer-motion.
- No internal use of `requestAnimationFrame` for layout.

### 8.2 Compatibility checklist for `@prompt-or-die/tech-ui` (which depends on `framer-motion@^11`)

- ✅ React 18 (already installed at `webui/package.json:31`) is supported by `framer-motion@^11`.
- ✅ Tailwind 3.4 (already installed) is supported by tech-ui (peer `tailwindcss: >=3.4.0 <5.0.0`).
- ✅ `framer-motion` is a **regular** dependency of `@prompt-or-die/tech-ui@0.0.1` (verified from `npm view @prompt-or-die/tech-ui`), not a peer — so just installing tech-ui pulls it in. No separate decision to bundle it.
- ⚠️ `AnimatePresence` with `mode="popLayout"` around the message list will fight assistant-ui's auto-scroll: when an exit animation delays unmount, the viewport's bottom-detection sees the wrong height and scrolls early. **Fix**: animate per-message with `motion.div` *inside* `AssistantMessage`, not around the whole `ThreadPrimitive.Messages`. Exit animations on individual messages should use `mode="sync"` or be skipped for the latest message.
- ⚠️ `framer-motion`'s `layout` prop on the inner message bubble triggers continuous reflow during streaming text. Set `layout="position"` (only animate position changes, not size) to avoid jitter while tokens stream in.
- ⚠️ Bundle size: `framer-motion@^11` minified+gzip is ~50 kB. The PRD's 200 kB gzip budget can absorb it, but every other tech-ui component (TechAgentWorkbench, TechRadar, TechNeuralMesh) shares this dep and tree-shakes at the page level only — verify with `bun run build && du -sh nanobot/web/dist/assets/*.js`.
- ✅ `framer-motion` does not register globals or affect the React reconciler; safe to mount inside `AssistantRuntimeProvider`.

### 8.3 Safer alternative: `tailwindcss-animate` already on the project

The project already depends on `tailwindcss-animate@^1.0.7` (`webui/package.json:46`). The current shadcn-style assistant-ui template uses its `animate-in fade-in slide-in-from-bottom-1` utilities. For pure entrance/exit animations (no layout), `tailwindcss-animate` is enough and adds zero JS. Reserve framer-motion for tech-ui interactive HUD components (TechRadar sweeps, TechNeuralMesh particles).

---

## 9) Concrete migration path: minimal styling → full tech-HUD chat

Three progressive PR-sized steps. Each is independently shippable; each leaves the runtime contract (`useSecbotRuntime`) untouched.

### Step 1 — Fix the broken import + adopt user-owned thread template (no visual change)

Goal: get to a v0.10-correct baseline that matches `.trellis/spec/frontend/component-patterns.md`.

1. Run `npx assistant-ui@latest add thread tool-fallback markdown-text` against the webui workspace **but** target the legacy v0.10 templates (or hand-port the current registry template, replacing all `AuiIf` / `useAuiState` / `MessagePrimitive.GroupedParts` calls — none of which exist in 0.10).
2. The CLI drops `webui/src/components/assistant-ui/{thread,tool-fallback,markdown-text}.tsx`. Tweak imports to re-use `webui/src/secbot/renderers/tool-call-card.tsx` as the tool fallback.
3. Replace `webui/src/secbot/SecbotThread.tsx` with:
   ```tsx
   import { AssistantRuntimeProvider } from "@assistant-ui/react";
   import { Thread } from "@/components/assistant-ui/thread";
   import { useSecbotRuntime, type SecbotRuntimeOptions } from "./runtime";

   export function SecbotThread(props: SecbotRuntimeOptions = {}) {
     const runtime = useSecbotRuntime(props);
     return (
       <AssistantRuntimeProvider runtime={runtime}>
         <Thread />
       </AssistantRuntimeProvider>
     );
   }
   ```
4. Inside the user-owned `thread.tsx`, the `AssistantMessage` should render `<MessagePrimitive.Content components={{ tools: { by_name: SKILL_RENDERERS, Fallback: ToolCallCard } }} />`.
5. Either delete the unused `tools={SKILL_RENDERERS}` prop everywhere or convert it to inline `MessagePrimitive.Content` slot config (single source of truth in `tool-ui.tsx`).
6. **Tests to add**:
   - `tests/secbot-thread.test.tsx` — render `<SecbotThread />`, push a fake `tool_call_start` + `tool_call_result` event for each registered skill, assert each renderer mounts.
   - `tests/secbot-thread-fallback.test.tsx` — push an unknown `skill` and assert `<ToolCallCard>` renders.
   - Type-check guard: `tsc -p webui/tsconfig.build.json` must pass — the current `Thread` import will fail this if the project is genuinely on v0.10.x.

   **Risk**: if the project is currently building because of a stale `.lockfile` resolving to v0.7, this step will surface real type errors. Plan a follow-up to update `bun.lockb`.

### Step 2 — Tech-HUD chrome on the existing slot map (visible upgrade, low risk)

Goal: ocean-blue HUD aesthetic for the chat surface without changing component contracts. Only edits user-owned files.

1. Edit `webui/src/components/assistant-ui/thread.tsx`:
   - Wrap `ThreadPrimitive.Root` in a `TechFrame` (variant `panel`); pass our `--primary` ocean-blue token as the frame's accent.
   - Replace the welcome screen with `TechAgentWorkbench`'s "ready" state header (no behavior change, just chrome).
   - Add a `:root[data-theme="secbot"] .aui-thread-viewport-footer` rule in `globals.css` that drops a glass-blue bottom gradient.
2. Replace `webui/src/secbot/renderers/tool-call-card.tsx` body with `TechCard` + glow rules driven by `status.type` + a severity dot driven by the existing `<StatusPill>` palette. Keep the current `<details>` collapse semantics.
3. Convert each skill renderer (`nmap-port-scan.tsx`, `nuclei-template-scan.tsx`, `fscan-*.tsx`) to wrap its existing table inside `TechFrame` with a header row using `TechBadge` for severity. **Do not touch the structured payload contract**.
4. Add a custom `Text` slot (`webui/src/components/assistant-ui/tech-text.tsx`) that:
   - Renders `<MessagePartPrimitive.Text />` inside a `prose prose-sm dark:prose-invert` block.
   - Replaces the default `●` cursor with a glowing primary-color square (see §6.1).
5. Mount it via `<MessagePrimitive.Content components={{ Text: TechText, tools: { by_name, Fallback } }} />`.
6. **Tests to add**:
   - `tests/secbot-tech-hud.test.tsx` — assert `aui-thread-root` element has `data-theme="secbot"` ancestor; assert the running tool-call card has class `hud-shimmer`; snapshot the tool-call card empty/running/complete states.
   - Visual regression: capture before/after screenshots in CI (Vitest + happy-dom doesn't render real CSS, so document this as a manual checklist item gated on the PRD's screenshot-comparison acceptance criterion).

   **Risk**: framer-motion entrance animations on individual messages. Mitigation: per-message `motion.div` only, never wrap `ThreadPrimitive.Messages`.

### Step 3 — Workbench chat (thought chain + neural mesh, full HUD)

Goal: PRD's "S3 重度 HUD 化" — orchestrator reasoning visible, tool tree, optional `TechNeuralMesh` background.

1. Have the secbot orchestrator emit `plan` events that surface as a `data` content part. In v0.10, `data` parts are rendered through the `Empty` / your-own-namespace mechanism — easiest is to keep them out of the message stream and store them on a side-channel (e.g., a Zustand store hydrated by the same WebSocket adapter), so the rendering path doesn't depend on a v0.10-only data-slot.
2. Inside `AssistantMessage`, render `<TechThoughtChain steps={planSteps} />` above `<MessagePrimitive.Content />`.
3. Add `TechNeuralMesh` as a `position: fixed` background layer on `SecbotShell` — it is purely decorative and uses framer-motion. Confine it to the chat tab, keep `pointer-events: none`.
4. Inside `AssistantMessage`, render `<BranchPickerPrimitive>` with `<TechHoloProjector>` styling at the message footer (replaces the default `<>` arrows).
5. Inside the composer, swap the textarea for `<TechInput>` (already covered in §5).
6. Make running-state visible at the frame level via `useThreadIf({ running: true })` to toggle a `TechFrame variant="alert"` on the outer `ThreadPrimitive.Root`.
7. **Tests to add**:
   - `tests/secbot-thought-chain.test.tsx` — push a synthetic `plan` event; assert the `<TechThoughtChain>` renders the expected step labels in order; assert it stays in the assistant-message scope (i.e., disappears when the run completes).
   - `tests/secbot-streaming-cursor.test.tsx` — assert the `<MessagePartPrimitive.InProgress>` wrapper unmounts when a `tool_call_result` arrives mid-token-stream.
   - Bundle size guard: add a `vite build`-driven check to CI that fails if `nanobot/web/dist/assets/*.js` gzip total grows by more than 200 kB compared to main (matches PRD acceptance criterion).

   **Risk**: framer-motion + assistant-ui's auto-scroll. Mitigation already in §8.2 — animate individual message components, not the list. **Risk**: `TechNeuralMesh` can dominate paint time on low-end machines; gate behind a "performance mode" preference in `webui/src/SettingsView` or feature-flag it.

### Cross-cutting tests (needed before any of the steps lands)

- A `tests/assistant-ui-export-guard.test.ts` that imports every name the codebase consumes from `@assistant-ui/react` and asserts the import succeeds at runtime. Today this would catch the `Thread` regression. Cheap insurance against future v0.10→v0.11 upgrades that rename the `*ContentPart*` aliases.
- Ensure the `tool-ui.tsx` registry stays the single source of truth: any new skill MUST register here. Add an ESLint rule (or simple `vitest` check) that scans `webui/src/secbot/renderers/*.tsx` and asserts each exported renderer is keyed in `SKILL_RENDERERS`.

---

## Files Found

### Internal (`webui/src/secbot/**`)

| File Path | Description |
|---|---|
| `webui/src/secbot/SecbotThread.tsx` | Top-level chat surface; **contains the broken `Thread` import + non-v0.10 `tools` / `components.ToolFallback` props**. |
| `webui/src/secbot/runtime.ts` | `useLocalRuntime` adapter over `/api/ws`. v0.10-correct. Emits `text` parts + `tool-call` parts (no `reasoning` or `data` parts yet). |
| `webui/src/secbot/tool-ui.tsx` | `SKILL_RENDERERS` registry — type matches `ToolCallContentPartComponent`. v0.10-correct. |
| `webui/src/secbot/renderers/tool-call-card.tsx` | Generic tool fallback. Renders `result.status` via `<StatusPill>`. |
| `webui/src/secbot/renderers/_shared.tsx` | Severity badges + `RawLogLink` (used by skill renderers). |
| `webui/src/secbot/renderers/nmap-port-scan.tsx` | Skill renderer, plain HTML table; first candidate for `TechFrame` wrapping in Step 2. |
| `webui/src/secbot/renderers/nuclei-template-scan.tsx` | Same pattern as nmap. |
| `webui/src/secbot/renderers/fscan-{asset-discovery,vuln-scan}.tsx` | Same pattern. |
| `webui/src/secbot/renderers/cmdb-query.tsx` | Same pattern. |
| `webui/src/secbot/renderers/report.tsx` | Skill renderer for `report-{markdown,docx,pdf}`. |
| `webui/src/secbot/SecbotShell.tsx` | 4-tab shell; chat tab mounts `<SecbotThread />`. Untouched by this work. |

### Internal — existing (non-secbot) thread surface (kept as-is per PRD §Out of Scope)

| File Path | Description |
|---|---|
| `webui/src/components/thread/ThreadShell.tsx` | nanobot's main chat shell — uses its own `useNanobotStream`, NOT assistant-ui. Not part of this migration. |
| `webui/src/components/thread/ThreadComposer.tsx` | nanobot composer with attachment support. |
| `webui/src/components/thread/ThreadViewport.tsx`, `ThreadMessages.tsx` | nanobot message rendering. |

### Spec

| File Path | Description |
|---|---|
| `.trellis/spec/frontend/index.md` | Hard rules — `@assistant-ui/react@^0.10.0` non-negotiable, tool-call rendering must go through assistant-ui registry. |
| `.trellis/spec/frontend/component-patterns.md` | MessageBubble triplet (`ToolCallCard` / `ScanResultTable` / `PlanTimeline`); §5 forbids "branching renderer selection inside a single component" — affirms `tools.by_name` registry path. |
| `.trellis/spec/frontend/webui-design.md` | View hierarchy; §3 documents the `useExternalStoreRuntime` integration approach (note: secbot uses `useLocalRuntime` instead, slightly different than the spec — flag for future spec amendment if relevant). |
| `.trellis/spec/frontend/theme-tokens.md` | Token contract for `:root[data-theme="secbot"]`. |

### External docs (verified URLs)

- Thread primitive (slots, components prop, render-fn) — <https://www.assistant-ui.com/docs/primitives/thread>
- Message primitive (Content slots — the actual home of `tools.by_name`) — <https://www.assistant-ui.com/docs/primitives/message>
- Composer primitive (`asChild` pattern) — <https://www.assistant-ui.com/docs/primitives/composer>
- Generative UI / `makeAssistantToolUI` — <https://www.assistant-ui.com/docs/guides/tool-ui>
- ToolFallback shadcn template — <https://www.assistant-ui.com/docs/ui/tool-fallback>
- Chain of Thought guide (note: requires `MessagePrimitive.GroupedParts`, **0.13+** only — not available in 0.10) — <https://www.assistant-ui.com/docs/guides/chain-of-thought>
- Custom Scrollbar pattern — <https://www.assistant-ui.com/docs/ui/scrollbar>
- Architecture overview — <https://www.assistant-ui.com/docs/architecture>
- LLM-friendly aggregated docs (used for this research) — <https://www.assistant-ui.com/llms-full.txt>
- Source repo (v0.10.50 tag) — <https://github.com/assistant-ui/assistant-ui/tree/@assistant-ui/react@0.10.50/packages/react>
- Component registry — <https://r.assistant-ui.com/registry.json> (note: serves the latest template; not version-pinned)

---

## Caveats / Not Found

1. **The user's existing `<Thread tools={SKILL_RENDERERS} components={{ ToolFallback: ToolCallCard }} />` does not match any officially-released `@assistant-ui/react` API.** Either the file currently fails to type-check or the project is still on a stale lockfile resolving to v0.7-or-earlier. Confirm before assuming Step 1 is "no behavior change" — surfacing this is itself the contract fix.

2. The current shadcn registry (`r.assistant-ui.com/thread.json`) serves a v0.13-flavoured template that uses `AuiIf` (introduced in 0.11) and `useAuiState` and `MessagePrimitive.GroupedParts` (introduced in 0.13). **None of these exist in v0.10.x.** Running `npx assistant-ui add thread` against the project today will produce a file that fails to compile under v0.10.x. You must hand-port a v0.10-compatible version, or upgrade to v0.13+ first. Alternatively, freeze on a `git` snapshot of the registry circa August-September 2025.

3. `tw-shimmer` is Tailwind v4 only (the `@import "tw-shimmer"` form is the v4 plugin syntax). Until the webui upgrades Tailwind, the shimmer effect must be hand-rolled (see §6.2).

4. `MessagePrimitive.Parts` (the render-fn variant of `Content` that uses `({ part }) => part.toolUI ?? <Fallback />`) does NOT exist in v0.10. The v0.10 equivalent is `MessagePrimitive.Content` with the `components` slot map. Lots of public docs / example repos on GitHub use the newer `Parts` API and will mislead you.

5. The v0.10 source code has `// TODO remove in v0.11` markers on every `*ContentPart*` alias. The webui currently imports `ToolCallContentPartComponent` (the deprecated alias). It still works, but for forward-compat with 0.11+, add a follow-up to migrate to `ToolCallMessagePartComponent`.

6. `framer-motion@^11` ships `~50 kB` gzip; the PRD's `+200 kB` budget covers it but only barely if `@prompt-or-die/tech-ui` lights up multiple HUD components (TechRadar, TechNeuralMesh, TechHoloProjector each ship their own SVG/canvas weight). Recommend adding a CI bundle-size check in Step 1 before the visual work lands.

7. The PRD references `TechAgentWorkbench`, `TechThoughtChain`, `TechRadar`, `TechNeuralMesh`, `TechBiometrics`, `TechHoloProjector`. The npm release `@prompt-or-die/tech-ui@0.0.1` only had a partial component set as of the install metadata (3 tech-* docs found by `npm view`). Audit the actual export list before designing Step 3 — some HUD components in the PRD may not yet ship.

8. Not investigated: assistant-ui's i18n story for the Composer / Thread placeholder strings (the spec says i18next must wrap them). The `<ComposerPrimitive.Input placeholder="…" />` placeholder is a plain prop you can localize at the call site. No deeper contract discovered.
