# Theme Tokens

> Authoritative source for color tokens used by `webui/`. Components MUST reference these via Tailwind semantic classes (`bg-primary`, `text-severity-critical`, …) or `hsl(var(--token))`. Raw hex literals in component code are forbidden.
>
> Origin: research/cybersec-ui-patterns.md §3.

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

> Light theme is intentionally not specified for the secbot console (operator workflow assumes dark). If a light theme is later required, mirror these tokens with HSL inversion before introducing new components.

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

## 4. `globals.css` Contract

`webui/src/styles/globals.css` (or current equivalent) MUST publish the tokens below in HSL form. Components consume them via Tailwind `theme.extend.colors.severity = { critical: 'hsl(var(--sev-critical))', ... }`.

```css
@layer base {
  :root[data-theme="dark"] {
    --background: 230 20% 5%;          /* #0A0B10 */
    --foreground: 220 10% 92%;         /* #E6E8EE */

    --card: 230 18% 9%;                /* #13141B */
    --card-foreground: 220 10% 92%;

    --popover: 230 16% 12%;            /* #1A1C25 */
    --border: 230 12% 18%;             /* #262833 */

    --primary: 210 100% 56%;           /* #1E90FF 海蓝 */
    --primary-foreground: 230 20% 5%;

    --destructive: 0 100% 65%;         /* #FF4D4F = sev-critical */
    --destructive-foreground: 0 0% 100%;

    --sev-critical: 0 100% 65%;        /* #FF4D4F */
    --sev-high:     22 100% 62%;       /* #FF8A3D */
    --sev-medium:   48 96% 53%;        /* #FACC15 */
    --sev-low:      203 100% 62%;      /* #3FB6FF */
    --sev-info:     220 7% 64%;        /* #9AA0AC */
  }
}
```

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
