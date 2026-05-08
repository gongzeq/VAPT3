# Theme Tokens

> Authoritative source for color tokens used by `webui/`. Components MUST reference these via Tailwind semantic classes (`bg-primary`, `text-severity-critical`, …) or `hsl(var(--token))`. Raw hex literals in component code are forbidden.
>
> Origin: research/cybersec-ui-patterns.md §3 + 05-07-ocean-tech-frontend PRD §R1 (dual-brand + semantic state extension, PR1).

---

## 1. Dark Theme Base

| Token | Hex | HSL | Use |
|-------|-----|-----|-----|
| `--background` | `#0A0B10` | `230 20% 5%` | App background, near-black with blue tint |
| `--card` | `#13141B` | `230 18% 9%` | Card surface, +3-4% lightness vs background |
| `--popover` | `#1A1C25` | `230 16% 12%` | Dialog / popover elevated surface |
| `--border` | `#262833` | `230 12% 18%` | Standard divider |
| `--border-subtle` | `#1F2029` | `230 12% 14%` | Faint divider |
| `--foreground` | `#E6E8EE` | `220 10% 92%` | Primary text (avoid pure white) |
| `--muted-foreground` | `#9AA0AC` | `220 7% 64%` | Secondary text, timestamps |
| `--placeholder` | `#5C6170` | `225 8% 40%` | Input placeholder |

> Light theme was previously deferred. As of PR1 of the `05-07-ocean-tech-frontend` task it is **specified** — see [§7 Light Theme](#7-light-theme). It activates when the root element carries both `data-theme="secbot"` and `data-mode="light"`.

---

## 2. Primary / Accent — 海蓝

The primary color **MUST** be 海蓝 (deep saturated blue). This replaces the earlier neon-cyan candidate.

| Token | Hex | HSL | Notes |
|-------|-----|-----|-------|
| `--primary` | `#1E90FF` | `210 100% 56%` | Main buttons, active link, focus ring |
| `--primary-hover` | `#4DA8FF` | `210 100% 65%` | Hover state |
| `--primary-foreground` | `#0A0B10` | `230 20% 5%` | Text/icon on primary surface (white on `#1E90FF` fails 4.5:1) |

**Rationale** (do not weaken without spec amendment):
- 海蓝 conveys "稳重 / 专业 / 可信", aligned with secbot's positioning as a **security operations console**.
- Matches the visual mental model of mainstream Chinese security products (奇安信 / 360 / 深信服) and avoids the "creative LLM tool" feel of purple/pink palettes.
- Lower visual fatigue than neon cyan during long operator sessions.

**Deeper variant** (only when explicit contrast tuning is needed): `#0A74DA` / HSL `210 92% 45%`. Document the override in the component's PR description and reference this section.

### 2.1 Severity-vs-primary collision rule

`--primary` (`#1E90FF`) and `--sev-low` (`#3FB6FF`) sit only ~7° apart on the hue wheel. When both appear in the same viewport (e.g. a "Continue scan" button next to a vulnerability list), pick **one** of the following before merging the PR:

1. **Recommended**: Switch the component instance's `--primary` to deep variant `#0A74DA`; keep `--sev-low` at sky-400.
2. **Alternative**: Keep `--primary` at `#1E90FF`; downgrade `--sev-low` to neutral `#9AA0AC` (sacrifices the "blue = info" intuition).

Document which option was applied in the component file header comment.

### 2.2 Dual-Brand Strategy (PR1)

The secbot console intentionally uses **two** ocean-blue tones with distinct roles. This mirrors mature SaaS systems (Linear / Vercel / Splunk) where a deep, saturated brand color anchors identity surfaces (sidebar, hero, brand badge) while a brighter accent owns interaction (focus, primary action, focus ring).

| Token | Hex | HSL | Role | Use cases |
|-------|-----|-----|------|-----------|
| `--brand-deep` | `#0E6BA8` | `204 86% 36%` | **Identity** | Sidebar background, hero gradient, brand badge surface, top-bar accent |
| `--primary` | `#1E90FF` | `210 100% 56%` | **Interaction** | Buttons, focus ring, active link, primary action |
| `--brand-light` | `#7AB8FF` | `210 100% 74%` | **Tint** | Hover overlay, link-visited tint, glow accent halo, subtle highlight |

**Rationale**:
- A single saturated color cannot serve both "wayfinding identity" (calm, trustworthy) and "interaction signal" (bright, attention-grabbing). Splitting the role lets each color stay legible without compromise.
- `--brand-deep` doubles as a high-contrast surface (5.6:1 white-on-deep) usable behind dense navigation labels.
- `--brand-light` is intentionally NOT a text color in normal use; its 9.5:1 against `--background` makes it perfect for glow halos / hover overlays without re-tuning.

**Verified contrast** (against `--background` `#0A0B10` in dark mode):
- `--brand-deep` as background, `--foreground` text on top: **4.61:1** (AA).
- `--brand-deep` as background, white text on top: **5.70:1** (AA).
- `--brand-deep` as text on `--background`: 3.51:1 (passes UI 3:1 only — do NOT use as body text).
- `--brand-light` as text on `--background`: **9.49:1** (AAA).

**Forbidden mixings** (avoid; they create visual ambiguity):
- ❌ `--brand-deep` as a button background (use `--primary` — that is its job).
- ❌ `--primary` as a sidebar background (use `--brand-deep`; primary is reserved for interaction).
- ❌ `--brand-light` as body text (3-4:1 territory; only safe at headline weight ≥ 18.66 px or as non-text glow).

---

## 3. Severity Palette

Severity colors are **functional**, not brand. They MUST stay aligned with OWASP / Burp conventions and pass ≥4.5:1 contrast on `--background`.

| Level | Token | Hex | Tailwind near | Contrast on `#0A0B10` |
|-------|-------|-----|---------------|------------------------|
| Critical | `--sev-critical` | `#FF4D4F` | red-500 | ≥4.5 |
| High | `--sev-high` | `#FF8A3D` | orange-500 | ≥4.5 |
| Medium | `--sev-medium` | `#FACC15` | yellow-400 | ≥7 |
| Low | `--sev-low` | `#3FB6FF` | sky-400 | ≥4.5 |
| Info | `--sev-info` | `#9AA0AC` | slate-400 | ≥4.5 |

`--destructive` is aliased to `--sev-critical` (`#FF4D4F`). The destructive AlertDialog primary action MUST consume this token.

---

## 3.5 Semantic State Palette (PR1)

Severity is for **vulnerability/risk** classification. Semantic state is for **form / toast / status** UI surfaces (validation errors, success toasts, info banners). They have separate tokens because their roles differ — severity colors should stay aligned with OWASP / Burp regardless of brand; state colors track product UI conventions.

| Token | Hex | HSL | Use | Contrast on `#0A0B10` |
|-------|-------|-----|-----|------------------------|
| `--success` | `#21C45D` | `142 71% 45%` | Toast success, validation pass, scan-complete badge | 8.54:1 (AAA) |
| `--warning` | `#F59E0B` | `38 92% 50%` | Toast warning, soft alerts, "rate-limited" banner | 9.22:1 (AAA) |
| `--error` | `#DC2828` | `0 72% 51%` | Form validation error background, toast error bg, input error ring | 4.79:1 white-on-error (AA); see note below |
| `--info` | `#0EA2E7` | `199 89% 48%` | Toast info, "tip" banner, neutral status pill | 6.87:1 (AA) |

**Notes on `--error` vs `--sev-critical`**:
- `--sev-critical` (`#FF4D4F`) is meant to be CONSUMED AS TEXT or a glow on dark — it is brighter to stay legible at small sizes.
- `--error` (`#DC2828`) is meant to be CONSUMED AS A BACKGROUND/BORDER (button bg, toast bar, input ring). White text on `--error` is 4.79:1 (AA). When you need text-as-error in dark mode (e.g. inline validation message), use `--sev-critical` instead.

**Forbidden**:
- ❌ Adding a new semantic state level (Success / Warning / Error / Info is the closed set).
- ❌ Re-mapping `--error` to a different hue family (red-orange spectrum only; matches the global UX expectation).

---

## 4. `globals.css` Contract

`webui/src/styles/globals.css` (or current equivalent) MUST publish the tokens below in HSL form. Components consume them via Tailwind `theme.extend.colors.severity = { critical: 'hsl(var(--sev-critical))', ... }` and `theme.extend.colors.{success,warning,error,info} = 'hsl(var(--<token>))'`.

```css
@layer base {
  :root[data-theme="secbot"] {
    --background: 230 20% 5%;          /* #0A0B10 */
    --foreground: 220 10% 92%;         /* #E6E8EE */

    --card: 230 18% 9%;                /* #13141B */
    --card-foreground: 220 10% 92%;

    --popover: 230 16% 12%;            /* #1A1C25 */
    --border: 230 12% 18%;             /* #262833 */

    /* Dual-brand (PR1, §2.2) */
    --primary: 210 100% 56%;           /* #1E90FF — interaction */
    --primary-foreground: 230 20% 5%;
    --brand-deep: 204 86% 36%;         /* #0E6BA8 — identity */
    --brand-light: 210 100% 74%;       /* #7AB8FF — tint / hover */

    --destructive: 0 100% 65%;         /* #FF4D4F = sev-critical */
    --destructive-foreground: 0 0% 100%;

    --sev-critical: 0 100% 65%;        /* #FF4D4F */
    --sev-high:     22 100% 62%;       /* #FF8A3D */
    --sev-medium:   48 96% 53%;        /* #FACC15 */
    --sev-low:      203 100% 62%;      /* #3FB6FF */
    --sev-info:     220 7% 64%;        /* #9AA0AC */

    /* Semantic state (PR1, §3.5) */
    --success: 142 71% 45%;            /* #21C45D */
    --warning:  38 92% 50%;            /* #F59E0B */
    --error:    0 72% 51%;             /* #DC2828 */
    --info:    199 89% 48%;            /* #0EA2E7 */
  }
}
```

The light theme variant is published in a sibling block — see [§7 Light Theme](#7-light-theme).

---

## 5. Forbidden

- ❌ Inline hex / rgb in `.tsx` / `.css`. Use a token instead.
- ❌ Importing color from a 3rd-party theme that overrides these tokens.
- ❌ Adding a new severity level (Critical / High / Medium / Low / Info is the closed set).
- ❌ Switching primary to neon cyan / purple / green "for fun". Theme changes are a spec amendment, not a styling tweak.

---

## 6. Pre-Modification Checklist

Before changing any token value:

- [ ] `grep -r "old-hex" webui/` to find every consumer.
- [ ] Verify contrast ratio against `--background` (target ≥4.5, ≥7 for Medium yellow).
- [ ] Update this spec **first**, then `globals.css`, then component snapshots if any.
- [ ] If the change touches `--primary`, re-verify the §2.1 collision rule for every screen that surfaces a Low badge.

---

## 7. Light Theme (PR1)

The secbot console is dark-first; light mode is provided for accessibility (operators on glare-prone screens) and brand consistency on print/screenshot exports. It activates ONLY when the root element carries both `data-theme="secbot"` AND `data-mode="light"`. Without `data-mode="light"`, the dark block applies.

### 7.1 Base palette

| Token | Hex | HSL | Use |
|-------|-----|-----|-----|
| `--background` | `#F4F8FD` | `211 56% 97%` | App background, pale ocean tint |
| `--foreground` | `#062E4D` | `205 81% 16%` | Primary text, deep navy ink |
| `--card` | `#FFFFFF` | `0 0% 100%` | Card surface |
| `--popover` | `#FFFFFF` | `0 0% 100%` | Dialog / popover surface |
| `--border` | n/a | `211 32% 86%` | Standard divider, light blue-grey |
| `--border-subtle` | n/a | `211 38% 92%` | Faint divider |

**Verified contrast** (light mode body text):
- `--foreground` `#062E4D` on `--background` `#F4F8FD`: **13.07:1** (AAA).

### 7.2 Brand and interaction

| Token | Hex | HSL | Notes |
|-------|-----|-----|-------|
| `--primary` | `#1E90FF` | `210 100% 56%` | Same as dark — Dodger Blue is the brand interaction color. **Do NOT pair with white text** (only 3.24:1, UI 3:1 only). For text-on-primary, use `--primary-foreground` (dark navy → 6.07:1 AA), or for WHITE-on-primary specifically swap the component instance to deep variant `#0A74DA` per §2 (`210 92% 45%`) which gives 4.64:1 with white. |
| `--primary-foreground` | `#0A0B10` | `230 20% 5%` | Dark navy text on light-mode primary. Mirrors dark-mode value so `bg-primary text-primary-foreground` consumers (e.g. `<Button>` default variant) keep AA across modes (6.07:1). |
| `--brand-deep` | `#0E6BA8` | `204 86% 36%` | Same as dark. As text on light bg: **5.25:1** (AA). As background with white text: 5.70:1 (AA). |
| `--brand-light` | `#7AB8FF` | `210 100% 74%` | Same as dark — used as overlay/tint, not text. Non-text role. |

### 7.3 Severity in light mode

The dark-mode severity tokens inherit by default and stay visually consistent with the OWASP/Burp convention. They are **not redefined** in the light block — current consumers are dark-bg badges and the existing color values still meet the >=3:1 UI threshold on `#F4F8FD`. If a future feature surfaces severity AS BODY TEXT against the light background, the implementing PR must amend this section with darker variants (e.g. `--sev-medium` would need `48 96% 30%` or similar).

### 7.4 Semantic state in light mode

State tokens MUST be darker in light mode to maintain ≥4.5:1 contrast on `#F4F8FD`.

| Token | Hex | HSL | Contrast on `#F4F8FD` |
|-------|-----|-----|------------------------|
| `--success` | `#16833E` | `142 71% 30%` | **4.54:1** (AA) |
| `--warning` | `#925F06` | `38 92% 30%` | **5.07:1** (AA) |
| `--error` | `#C52020` | `0 72% 45%` | **5.45:1** (AA) |
| `--info` | `#0A76A9` | `199 89% 35%` | **4.70:1** (AA) |
| `--destructive` | `#C52020` | `0 72% 45%` | matches `--error` for AA |

### 7.5 Light theme `globals.css` block

```css
@layer base {
  :root[data-theme="secbot"][data-mode="light"] {
    --background: 211 56% 97%;
    --foreground: 205 81% 16%;
    --card: 0 0% 100%;
    --card-foreground: 205 81% 16%;
    --popover: 0 0% 100%;
    --popover-foreground: 205 81% 16%;
    --border: 211 32% 86%;
    --border-subtle: 211 38% 92%;

    --primary: 210 100% 56%;
    --primary-foreground: 230 20% 5%;
    --brand-deep: 204 86% 36%;
    --brand-light: 210 100% 74%;

    --destructive: 0 72% 45%;
    --destructive-foreground: 0 0% 100%;

    --success: 142 71% 30%;
    --warning:  38 92% 30%;
    --error:    0 72% 45%;
    --info:    199 89% 35%;
  }
}
```

### 7.6 Forbidden in light mode

- ❌ Reusing dark-mode state token values verbatim (they fail AA on light bg).
- ❌ Setting `data-mode="light"` without `data-theme="secbot"` (the light block REQUIRES both — it cannot be combined with the legacy nanobot palette).
- ❌ Hard-coding `#F4F8FD` / `#062E4D` in components — always reference `bg-background` / `text-foreground` so the same component renders correctly in both modes.
