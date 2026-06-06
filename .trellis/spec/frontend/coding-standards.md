# Coding Standards

> Authoritative coding standards for every file under `webui/src/**`.
> These rules are **non-negotiable** and enforced at PR review + CI lint level. They complement the domain-specific specs ([theme-tokens.md](./theme-tokens.md), [component-patterns.md](./component-patterns.md), etc.) — when both apply, the stricter constraint wins.

---

## 1. Core Principles (always prioritise in this order)

1. **TypeScript strict mode.** `tsconfig.json` MUST keep `"strict": true`. No opt-out per file.
2. **Functional components + hooks.** Class components are permitted ONLY when a lifecycle method has no hook equivalent (extremely rare — document the reason in the component header).
3. **Small & pure.** Each component file ≤ 400 lines (target ≤ 300). Single responsibility: one component + its helpers per file. If a file grows past the limit, decompose before merging.
4. **Composable atoms.** UI is built from reusable atomic components + composition, NOT monolithic page-components. Prefer `children` / render-props / slot patterns over prop-drilling.
5. **Minimal state management.** `useState` + `useReducer` first. Introduce Zustand / Jotai / Redux ONLY when:
   - The state is shared across ≥ 3 unrelated components, AND
   - Prop-drilling or Context causes measurable re-render issues.
   Any new global-state dependency requires a spec PR with rationale.
6. **Tailwind + shadcn / Radix / Headless UI.** These are the default styling and primitive layers. Do NOT add another CSS framework or component library without a spec amendment.
7. **ESLint + Prettier + typescript-eslint.** `.eslintrc` / `prettier` config is the source of truth for formatting. No manual overrides. CI MUST pass `eslint --max-warnings 0`.
8. **JSDoc / TSDoc on every export.** Every public function, hook, component, and utility MUST have a TSDoc block (at minimum: one-line summary + `@param` / `@returns` for non-trivial signatures). Private helpers inside a file should have `/** */` when the intent is not obvious from the name.
9. **Modern syntax.** Prefer optional chaining (`?.`), nullish coalescing (`??`), top-level `await`, `structuredClone`, `Object.groupBy`, etc. over legacy equivalents.

---

## 2. File & Directory Naming

| Category | Convention | Example |
|----------|-----------|---------|
| Component | `PascalCase.tsx` | `UserProfileCard.tsx` |
| Hook | `camelCase.ts` starting with `use` | `useDebounce.ts` |
| Utility / helper | `camelCase.ts` | `formatCurrency.ts` |
| Constant | `UPPER_SNAKE_CASE` or `camelCase` (by semantics) | `MAX_RETRY_COUNT`, `defaultTheme` |
| Type / interface | Co-located in the same file, or in `types/` with `I` / `T` / type alias prefix | `types.ts`, `ButtonProps` |
| Test | Same name + `.test.tsx` / `.spec.tsx` | `UserProfileCard.test.tsx` |
| Storybook | Same name + `.stories.tsx` | `UserProfileCard.stories.tsx` |
| Page (route target) | `PascalCase.tsx` under `pages/` | `pages/DashboardPage.tsx` |
| Barrel (re-export) | `index.ts` per directory | `components/ui/index.ts` |

### Directory structure (recommended)

```
webui/src/
├── components/          # Reusable UI components (atomic + composed)
│   ├── ui/              # shadcn primitives (button, input, dialog …)
│   ├── thread/          # Chat-thread-specific components
│   └── …                # Domain groupings (agents/, workflow/, settings/)
├── hooks/               # Custom hooks (useXxx.ts)
├── lib/                 # Utilities, API clients, parsers
├── pages/               # Route-target page components
├── providers/           # React context providers
├── i18n/                # Internationalisation config
├── data/                # Mock data / static datasets
└── styles/              # globals.css, Tailwind config overrides
```

---

## 3. Component Writing Rules

### 3.1 Props contract

1. Every component MUST export its props type as `interface XxxProps` or `type XxxProps`.
2. Prefer destructuring with defaults in the function signature:

```tsx
interface CardProps {
  title: string
  subtitle?: string
  children?: React.ReactNode
  className?: string
}

const Card = ({ title, subtitle, children, className }: CardProps) => { … }
```

3. `children` MUST be explicitly declared as `React.ReactNode` (optional) when the component accepts children.
4. Dynamic `className` composition uses `cn()` (the project's `clsx` + `tailwind-merge` helper) or `cva` (class-variance-authority) for variant-driven components.
5. `forwardRef` is required when the component needs to forward a ref (e.g. shadcn primitives). Always set `displayName`:

```tsx
const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'default', children, ...props }, ref) => {
    // …
  }
)
Button.displayName = 'Button'
```

### 3.2 Side-effect discipline

- All side effects MUST live inside `useEffect` with a correct, explicit dependency array.
- **Forbidden**: `setState`, `dispatch`, network calls, or DOM mutations during render.
- `useLayoutEffect` only when the effect must synchronise with the paint (document the reason).

### 3.3 Business logic extraction

- If a component contains > 30 lines of non-JSX business logic (data transformation, validation, state machines), extract it into:
  - A custom hook (`useXxx.ts`) for stateful logic.
  - A utility function (`lib/xxx.ts`) for pure transformations.
- The component file should read as a **view layer**: JSX + minimal glue code.

### 3.4 Custom hooks

- Name MUST start with `use`.
- MUST return a stable API (object or tuple). If returning an object, the shape must not change between renders.
- Document with TSDoc: purpose, params, return value, usage example for complex hooks.

---

## 4. Recommended Component Props Pattern (modern style)

The canonical pattern for variant-driven components. Every new UI primitive SHOULD follow this shape:

```tsx
import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        primary: 'bg-primary text-primary-foreground hover:bg-primary/90',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        outline: 'border border-input bg-transparent hover:bg-accent',
        ghost: 'hover:bg-accent hover:text-accent-foreground',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
      },
      size: {
        sm: 'h-9 px-3',
        default: 'h-10 px-4 py-2',
        lg: 'h-11 px-8',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: { variant: 'primary', size: 'default' },
  }
)

interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
  loading?: boolean
  leftIcon?: React.ReactNode
  rightIcon?: React.ReactNode
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, asChild = false, loading = false, leftIcon, rightIcon, children, ...props },
    ref,
  ) => {
    // …
  },
)
Button.displayName = 'Button'
```

---

## 5. Tailwind + shadcn/ui Usage

| Rule | Detail |
|------|--------|
| **No inline styles** | `style={{}}` is forbidden. All styling via Tailwind classes. Exception: dynamic values that cannot be expressed as classes (e.g. `style={{ height: \`${computed}px\` }}`) — document why. |
| **Complex styles → cva + cn** | Components with ≥ 2 variants MUST use `cva` for variant definitions and `cn` for composition. |
| **Theme variables only** | Colours MUST come from `theme.colors.*` or CSS variables (`hsl(var(--token))`). Raw hex / rgb is forbidden (see [theme-tokens.md §5](./theme-tokens.md#5-forbidden)). |
| **Mobile-first responsive** | Use `sm:` → `md:` → `lg:` → `xl:` → `2xl:` ascending breakpoints. Base styles target mobile. |
| **Dark mode** | `dark:` prefix on classes. The project defaults to dark theme; light theme is not specified but must not break if enabled. |
| **No `@apply` in components** | `@apply` is allowed ONLY in `globals.css` for base-layer resets. Component files use class strings directly. |

---

## 6. Performance & Maintainability Red Lines

| Rule | Detail |
|------|--------|
| **No anonymous functions as props in loops** | `onClick={() => handleClick(item.id)}` inside `.map()` creates a new function per render. Extract to a child component that receives `item.id` and calls `handleClick` internally, or memo the callback. |
| **`useMemo` / `useCallback` — measure first** | Add ONLY when profiling shows a re-render cost. Do NOT preemptively wrap everything. Comment the reason: `// useMemo: avoids re-parsing 10k-row CSV on every render`. |
| **List `key` must be stable** | Use a unique, stable identifier (database ID, hash). `index` as key is forbidden unless the list is static and never reordered. |
| **Images: explicit dimensions** | Every `<img>` MUST set `width` + `height` (or use `aspect-ratio` utility) to prevent layout shift (CLS). |
| **No direct DOM access** | `document.getElementById`, `document.querySelector`, etc. are forbidden. Use `useRef` + `ref` callback. Exception: third-party library initialisation that requires a DOM node (wrap in `useEffect` + `ref`). |
| **No render-phase side effects** | `setState`, `dispatch`, network calls, or subscriptions during render will be rejected. |

---

## 7. Data Fetching (TanStack Query / React Query)

> This section applies when the project adopts TanStack Query. Until then, existing `fetch`-based patterns in `lib/` are acceptable but new features SHOULD migrate to this pattern.

1. **All server data via `useQuery` / `useMutation`.** No raw `fetch` / `axios` in components.
2. **`queryKey` MUST be a stable array.** Example: `['agents', { includeStatus: true }]`. Keys must be referentially stable (no inline object literals that create new references per render).
3. **Global defaults.** Configure `staleTime`, `gcTime`, `retry` at the `QueryClient` level in the app provider. Per-query overrides are allowed with justification.
4. **Error handling.** Unified through `ErrorBoundary` (for render errors) + toast notifications (for mutation errors). No per-component `try/catch` alerting.

---

## 8. Testing

| Scope | Tool | Requirement |
|-------|------|-------------|
| Hooks, pure functions, utilities | `vitest` + `@testing-library/react-hooks` | Unit tests with ≥ 80% line coverage for `hooks/` and `lib/` |
| Components | `vitest` + `@testing-library/react` + `userEvent` | Interaction tests: click, type, submit, navigate. Test **user behaviour**, not internal state. |
| Integration | `vitest` + MSW (mock service worker) | API contract tests for critical flows (login, chat, scan lifecycle) |

### Testing rules

- Test file co-located or mirrored: `components/Foo.tsx` → `components/Foo.test.tsx` (or under `tests/` mirroring `src/` structure).
- **No snapshot tests** for UI components (they break on styling changes and give false confidence). Use `getByRole` / `getByText` queries instead.
- Mock at the boundary: mock API clients (`lib/api.ts`), not `fetch`. Mock hooks only in component tests when the hook has its own test suite.
- CI gate: `vitest run --coverage` MUST pass with ≥ 80% coverage on `hooks/`, `lib/`, and core page components.

---

## 9. Forbidden (Red Lines)

The following are **automatic PR rejection** items. No exceptions without a spec amendment approved by the frontend lead.

| Ban | Alternative |
|-----|-------------|
| `console.log` / `console.error` in production code | Remove, or use a `logger` utility that is tree-shaken in production builds. |
| `any` type | Use `unknown` + type narrowing. If unavoidable: `// @ts-expect-error: <reason>` with a tracking issue. |
| Non-null assertion `!` | Use optional chaining `?.` + nullish coalescing `??` + type guards. |
| Direct CSS import from 3rd-party libs | Import via PostCSS / Tailwind `@import` in `globals.css`, or copy the needed styles into the project. |
| Nesting > 3 levels of conditionals | Extract into early-return guards, separate components, or a state machine. |
| `style={{}}` inline styles | Tailwind classes. Exception documented in §5. |
| `index` as list `key` | Stable unique ID. |
| Direct DOM manipulation | `useRef`. |
| Class components (without documented exception) | Functional component + hooks. |
| Untyped event handlers | Always annotate: `(e: React.ChangeEvent<HTMLInputElement>) => void`. |
| Barrel re-exports that hurt tree-shaking | Prefer direct imports: `import { Button } from '@/components/ui/button'`. |

---

## 10. Pre-Implementation Checklist

Before writing or modifying any frontend file:

- [ ] Read this spec ([coding-standards.md](./coding-standards.md)) — you are here.
- [ ] Pulled latest [theme-tokens.md](./theme-tokens.md); will not introduce raw hex.
- [ ] Confirmed the component fits an existing pattern in [component-patterns.md](./component-patterns.md), or explicitly extending it.
- [ ] Required charts/graphs are achievable with the libraries listed in [visualization-libraries.md](./visualization-libraries.md).
- [ ] File naming follows §2 conventions.
- [ ] Props interface exported per §3.1.
- [ ] No banned patterns from §9 present in the diff.
- [ ] Tests written or updated per §8 for any changed hook / component / utility.
- [ ] TSDoc comments added for every new public export.
- [ ] `eslint --max-warnings 0` passes locally.
