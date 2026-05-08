// Source: https://magicui.design/r/border-beam.json — copied 2026-05-07
// for trellis task 05-07-ocean-tech-frontend (PR2).
//
// Adaptations from upstream:
//   - Imports `motion` from `framer-motion` (we are on framer-motion@^11)
//     instead of `motion/react` (v12-only package alias).
//   - Tailwind v4 utilities (`border-(length:--var)`, `bg-linear-to-l`,
//     `mask-intersect`, `mask-[...]`) are rewritten as Tailwind v3.4
//     bracket utilities so the JIT picks them up under our config.
//   - Default `colorFrom` / `colorTo` now reference design tokens
//     (`--brand-deep` / `--primary`) so the beam stays on-brand without
//     a per-call-site override (theme-tokens.md §2.2).
"use client";

import { motion, type MotionStyle, type Transition } from "framer-motion";

import { cn } from "@/lib/utils";

interface BorderBeamProps {
  /** The size (px) of the moving beam. */
  size?: number;
  /** The duration of one full lap, in seconds. */
  duration?: number;
  /** Animation start delay, in seconds. */
  delay?: number;
  /** Gradient start color (CSS color string). Default = brand-deep token. */
  colorFrom?: string;
  /** Gradient end color (CSS color string). Default = primary token. */
  colorTo?: string;
  /** Optional framer-motion transition override. */
  transition?: Transition;
  className?: string;
  style?: React.CSSProperties;
  /** Reverse the lap direction. */
  reverse?: boolean;
  /** Initial offset along the path, 0-100. */
  initialOffset?: number;
  /** Border width in px. */
  borderWidth?: number;
}

export const BorderBeam = ({
  className,
  size = 50,
  delay = 0,
  duration = 6,
  colorFrom = "hsl(var(--brand-deep))",
  colorTo = "hsl(var(--primary))",
  transition,
  style,
  reverse = false,
  initialOffset = 0,
  borderWidth = 1,
}: BorderBeamProps) => {
  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 rounded-[inherit]",
        "border-[length:var(--border-beam-width)] border-transparent",
        // Two-layer mask: paint the beam between the padding-box and the
        // border-box only. Using bracketed utilities keeps Tailwind v3.4 JIT
        // happy.
        "[mask-clip:padding-box,border-box]",
        "[mask-composite:intersect]",
        // Why hex: pure CSS mask machinery — only the alpha channel matters,
        // the literal `#000` is the canonical opaque-stop value for
        // `linear-gradient` in masks. Swapping in a token would not change
        // rendering and adds indirection.
        "[mask-image:linear-gradient(transparent,transparent),linear-gradient(#000,#000)]",
      )}
      style={
        {
          "--border-beam-width": `${borderWidth}px`,
        } as React.CSSProperties
      }
    >
      <motion.div
        className={cn(
          "absolute aspect-square",
          "bg-gradient-to-l from-[var(--color-from)] via-[var(--color-to)] to-transparent",
          className,
        )}
        style={
          {
            width: size,
            offsetPath: `rect(0 auto auto 0 round ${size}px)`,
            "--color-from": colorFrom,
            "--color-to": colorTo,
            ...style,
          } as MotionStyle
        }
        initial={{ offsetDistance: `${initialOffset}%` }}
        animate={{
          offsetDistance: reverse
            ? [`${100 - initialOffset}%`, `${-initialOffset}%`]
            : [`${initialOffset}%`, `${100 + initialOffset}%`],
        }}
        transition={{
          repeat: Infinity,
          ease: "linear",
          duration,
          delay: -delay,
          ...transition,
        }}
      />
    </div>
  );
};
