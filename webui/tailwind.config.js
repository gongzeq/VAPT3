import animate from "tailwindcss-animate";
import typography from "@tailwindcss/typography";

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
    // PR2 (05-07-ocean-tech-frontend): copied source for HUD chrome,
    // dataviz, and shadcn blocks. Keep these globs in sync with the
    // directories created by `bun x shadcn add` so JIT picks up
    // class names emitted by the copies.
    "./src/components/magicui/**/*.{ts,tsx}",
    "./src/components/tremor/**/*.{ts,tsx}",
    "./src/blocks/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "1rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      fontFamily: {
        sans: [
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "Roboto",
          '"Helvetica Neue"',
          "Arial",
          '"Noto Sans"',
          '"Noto Sans SC"',
          '"PingFang SC"',
          '"Hiragino Sans GB"',
          '"Microsoft YaHei"',
          "sans-serif",
          '"Apple Color Emoji"',
          '"Segoe UI Emoji"',
        ],
        mono: [
          '"JetBrains Mono"',
          '"Fira Code"',
          '"Cascadia Code"',
          '"Source Code Pro"',
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        border: "hsl(var(--border))",
        "border-subtle": "hsl(var(--border-subtle))",
        "text-primary": "hsl(var(--text-primary))",
        "text-secondary": "hsl(var(--text-secondary))",
        // Dual-brand strategy (theme-tokens.md §2.2). Used together with
        // --primary; see spec for role separation.
        "brand-deep": "hsl(var(--brand-deep))",
        "brand-light": "hsl(var(--brand-light))",
        // Semantic state (theme-tokens.md §3.5).
        success: "hsl(var(--success))",
        warning: "hsl(var(--warning))",
        error: "hsl(var(--error))",
        info: "hsl(var(--info))",
        severity: {
          critical: "hsl(var(--sev-critical))",
          high: "hsl(var(--sev-high))",
          medium: "hsl(var(--sev-medium))",
          low: "hsl(var(--sev-low))",
          info: "hsl(var(--sev-info))",
        },
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        sidebar: {
          // Legacy nanobot Sidebar tokens (kept for backwards compatibility
          // until PR3 reconciles old + new sidebar surfaces).
          DEFAULT: "hsl(var(--sidebar))",
          foreground: "hsl(var(--sidebar-foreground))",
          accent: "hsl(var(--sidebar-accent))",
          "accent-foreground": "hsl(var(--sidebar-accent-foreground))",
          border: "hsl(var(--sidebar-border))",
          // shadcn sidebar block (sidebar-07) tokens — see globals.css :root
          // block for the shadcn-managed CSS variables.
          primary: "hsl(var(--sidebar-primary))",
          "primary-foreground": "hsl(var(--sidebar-primary-foreground))",
          ring: "hsl(var(--sidebar-ring))",
        },
      },
      boxShadow: {
        // Glow accents for HUD surfaces (PR1 / theme-tokens.md §2.2).
        "glow-primary": "0 0 20px hsl(var(--primary) / 0.4)",
        "glow-brand": "0 0 20px hsl(var(--brand-deep) / 0.4)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        // MagicUI animation primitives — required by border-beam, marquee,
        // shine-border, animated-shiny-text, and shimmer-button. The
        // upstream package ships a Tailwind v4 plugin; we replicate the
        // keyframes inline so v3.4 JIT can resolve them. (PR2)
        marquee: {
          from: { transform: "translateX(0)" },
          to: { transform: "translateX(calc(-100% - var(--gap)))" },
        },
        "marquee-vertical": {
          from: { transform: "translateY(0)" },
          to: { transform: "translateY(calc(-100% - var(--gap)))" },
        },
        shine: {
          "0%": { "background-position": "0% 0%" },
          "50%": { "background-position": "100% 100%" },
          to: { "background-position": "0% 0%" },
        },
        "shiny-text": {
          "0%, 90%, 100%": { "background-position": "calc(-100% - var(--shiny-width)) 0" },
          "30%, 60%": { "background-position": "calc(100% + var(--shiny-width)) 0" },
        },
        "shimmer-slide": {
          to: { transform: "translate(calc(100cqw - 100%), 0)" },
        },
        "spin-around": {
          "0%": { transform: "translateZ(0) rotate(0)" },
          "15%, 35%": { transform: "translateZ(0) rotate(90deg)" },
          "65%, 85%": { transform: "translateZ(0) rotate(270deg)" },
          "100%": { transform: "translateZ(0) rotate(360deg)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        // MagicUI: bind the keyframes above to utility classes the
        // copied components rely on. Durations match upstream defaults.
        marquee: "marquee var(--duration, 40s) linear infinite",
        "marquee-vertical": "marquee-vertical var(--duration, 40s) linear infinite",
        shine: "shine var(--duration, 14s) infinite linear",
        "shiny-text": "shiny-text 8s infinite",
        "shimmer-slide": "shimmer-slide var(--speed, 3s) ease-in-out infinite alternate",
        "spin-around": "spin-around calc(var(--speed, 3s) * 2) infinite linear",
      },
    },
  },
  plugins: [animate, typography],
};
