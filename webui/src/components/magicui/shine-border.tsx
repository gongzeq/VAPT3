// Source: https://magicui.design/r/shine-border.json — copied 2026-05-07
// for trellis task 05-07-ocean-tech-frontend (PR2).
//
// Adaptations from upstream:
//   - Default `shineColor` now references the primary token via `hsl(var(--primary))`
//     so the shine stays on-brand without a per-call-site override
//     (theme-tokens.md §2). Upstream default was `#000000` (black).
//   - `motion-safe:animate-shine` requires the `shine` keyframe registered in
//     `tailwind.config.js` under `keyframes` + `animation`.
"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

interface ShineBorderProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Width of the border in pixels. */
  borderWidth?: number;
  /** Duration of the animation in seconds. */
  duration?: number;
  /** Color of the border. Single color or array; defaults to brand primary. */
  shineColor?: string | string[];
}

/**
 * Shine Border
 *
 * An animated background border effect with configurable color, width, and
 * duration. Renders as an absolutely-positioned overlay; the parent must be
 * `relative` and have a `rounded-*` for the inherit to work.
 */
export function ShineBorder({
  borderWidth = 1,
  duration = 14,
  shineColor = "hsl(var(--primary))",
  className,
  style,
  ...props
}: ShineBorderProps) {
  return (
    <div
      style={
        {
          "--border-width": `${borderWidth}px`,
          "--duration": `${duration}s`,
          backgroundImage: `radial-gradient(transparent,transparent, ${
            Array.isArray(shineColor) ? shineColor.join(",") : shineColor
          },transparent,transparent)`,
          backgroundSize: "300% 300%",
          mask: `linear-gradient(hsl(var(--foreground)) 0 0) content-box, linear-gradient(hsl(var(--foreground)) 0 0)`,
          WebkitMask: `linear-gradient(hsl(var(--foreground)) 0 0) content-box, linear-gradient(hsl(var(--foreground)) 0 0)`,
          WebkitMaskComposite: "xor",
          maskComposite: "exclude",
          padding: "var(--border-width)",
          ...style,
        } as React.CSSProperties
      }
      className={cn(
        "motion-safe:animate-shine pointer-events-none absolute inset-0 size-full rounded-[inherit] will-change-[background-position]",
        className,
      )}
      {...props}
    />
  );
}
