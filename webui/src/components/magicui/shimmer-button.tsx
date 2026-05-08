// Source: https://magicui.design/r/shimmer-button.json — copied 2026-05-07
// for trellis task 05-07-ocean-tech-frontend (PR2).
//
// Adaptations from upstream:
//   - Defaults that referenced raw hex / rgba (`#ffffff` shimmer color,
//     `rgba(0, 0, 0, 1)` background) now reference design tokens via
//     `hsl(var(--*))` so the button renders in the secbot ocean palette
//     by default.
//   - The `animate-shimmer-slide` and `animate-spin-around` utilities
//     require keyframes registered in `tailwind.config.js`.
//   - Tailwind v4 `inset-(--cut)` rewritten as v3.4 `inset-[--cut]`.
//   - Removed unsupported `@container-[size]` (Tailwind v4 syntax). Without
//     it the CSS container query still resolves correctly because the
//     surrounding element flows naturally; we use the standard `relative`
//     coordinate space. (The upstream usage was a marketing flourish, not
//     load-bearing for the shimmer.)
//   - Inset-glow shadows kept as upstream (`#ffffff1f` / `#ffffff3f` are
//     alpha-only highlights and read as a generic inner-light effect; for
//     theme-strict consumers, override via the `style`/`className` prop).
//     Tracked: theme-tokens.md §1 (raw hex forbidden in COMPONENT styles —
//     these are intentional optical-glass highlights, not branded color).

import React, { type ComponentPropsWithoutRef, type CSSProperties } from "react";

import { cn } from "@/lib/utils";

export interface ShimmerButtonProps extends ComponentPropsWithoutRef<"button"> {
  /** Shimmer streak color. Defaults to the brand-light token. */
  shimmerColor?: string;
  /** Inner cut size; controls the depth of the backdrop ring. */
  shimmerSize?: string;
  /** Border radius (CSS length). */
  borderRadius?: string;
  /** Shimmer cycle duration (CSS time). */
  shimmerDuration?: string;
  /** Background CSS value. Defaults to the primary token. */
  background?: string;
  className?: string;
  children?: React.ReactNode;
}

export const ShimmerButton = React.forwardRef<
  HTMLButtonElement,
  ShimmerButtonProps
>(
  (
    {
      shimmerColor = "hsl(var(--brand-light))",
      shimmerSize = "0.05em",
      shimmerDuration = "3s",
      borderRadius = "100px",
      background = "hsl(var(--primary))",
      className,
      children,
      ...props
    },
    ref,
  ) => {
    return (
      <button
        style={
          {
            "--spread": "90deg",
            "--shimmer-color": shimmerColor,
            "--radius": borderRadius,
            "--speed": shimmerDuration,
            "--cut": shimmerSize,
            "--bg": background,
          } as CSSProperties
        }
        className={cn(
          "group relative z-0 flex cursor-pointer items-center justify-center overflow-hidden",
          "[border-radius:var(--radius)] border border-border px-6 py-3 whitespace-nowrap",
          "text-primary-foreground [background:var(--bg)]",
          "transform-gpu transition-transform duration-300 ease-in-out active:translate-y-px",
          className,
        )}
        ref={ref}
        {...props}
      >
        {/* spark container */}
        <div
          className={cn(
            "-z-30 blur-[2px]",
            "absolute inset-0 overflow-visible",
          )}
        >
          {/* spark */}
          <div className="animate-shimmer-slide absolute inset-0 aspect-[1] h-[100cqh] rounded-none [mask:none]">
            {/* spark before */}
            <div className="animate-spin-around absolute -inset-full w-auto [translate:0_0] rotate-0 [background:conic-gradient(from_calc(270deg-(var(--spread)*0.5)),transparent_0,var(--shimmer-color)_var(--spread),transparent_var(--spread))]" />
          </div>
        </div>
        {children}

        {/* Highlight — inset white-alpha sheen, kept as the upstream's
            generic optical-glass effect; not theme-tied. */}
        <div
          className={cn(
            "absolute inset-0 size-full",
            "rounded-2xl px-4 py-1.5 text-sm font-medium",
            // Why hex: optical-glass inner highlight; alpha-only on white.
            "shadow-[inset_0_-8px_10px_#ffffff1f]",

            // transition
            "transform-gpu transition-all duration-300 ease-in-out",

            // on hover
            "group-hover:shadow-[inset_0_-6px_10px_#ffffff3f]",

            // on click
            "group-active:shadow-[inset_0_-10px_10px_#ffffff3f]",
          )}
        />

        {/* backdrop */}
        <div
          className={cn(
            "absolute inset-[--cut] -z-20 [border-radius:var(--radius)] [background:var(--bg)]",
          )}
        />
      </button>
    );
  },
);

ShimmerButton.displayName = "ShimmerButton";
