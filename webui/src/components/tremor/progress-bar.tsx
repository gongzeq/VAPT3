// Source: https://github.com/tremorlabs/tremor/blob/main/src/components/ProgressBar/ProgressBar.tsx
// Copied 2026-05-07 for trellis task 05-07-ocean-tech-frontend (PR2).
//
// Adaptations from upstream:
//   - `tv` slot variants replaced with two parallel `cva`s (one for the
//     background track, one for the bar) — keeps the same per-variant
//     pairing without adding tailwind-variants.
//   - Variant colors switched from raw Tailwind palette literals
//     (blue/yellow/red/emerald) to our PR1 token-backed semantic colors
//     (primary / warning / error / success / muted) so the bar renders in
//     the secbot ocean theme.
//   - `cx` replaced with the project-local `cn` from `@/lib/utils`.

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const progressBarTrack = cva("relative flex h-2 w-full items-center rounded-full", {
  variants: {
    variant: {
      default: "bg-primary/20",
      neutral: "bg-muted",
      warning: "bg-warning/20",
      error: "bg-error/20",
      success: "bg-success/20",
    },
  },
  defaultVariants: {
    variant: "default",
  },
});

const progressBarFill = cva("h-full flex-col rounded-full", {
  variants: {
    variant: {
      default: "bg-primary",
      neutral: "bg-muted-foreground",
      warning: "bg-warning",
      error: "bg-error",
      success: "bg-success",
    },
  },
  defaultVariants: {
    variant: "default",
  },
});

interface ProgressBarProps
  extends React.HTMLProps<HTMLDivElement>,
    VariantProps<typeof progressBarTrack> {
  value?: number;
  max?: number;
  showAnimation?: boolean;
  label?: string;
}

const ProgressBar = React.forwardRef<HTMLDivElement, ProgressBarProps>(
  (
    {
      value = 0,
      max = 100,
      label,
      showAnimation = false,
      variant,
      className,
      ...props
    }: ProgressBarProps,
    forwardedRef,
  ) => {
    const safeValue = Math.min(max, Math.max(value, 0));
    return (
      <div
        ref={forwardedRef}
        className={cn("flex w-full items-center", className)}
        role="progressbar"
        aria-label="Progress bar"
        aria-valuenow={value}
        aria-valuemax={max}
        {...props}
      >
        <div className={progressBarTrack({ variant })}>
          <div
            className={cn(
              progressBarFill({ variant }),
              showAnimation &&
                "transform-gpu transition-all duration-300 ease-in-out",
            )}
            style={{
              width: max ? `${(safeValue / max) * 100}%` : `${safeValue}%`,
            }}
          />
        </div>
        {label ? (
          <span className="ml-2 whitespace-nowrap text-sm font-medium leading-none text-foreground">
            {label}
          </span>
        ) : null}
      </div>
    );
  },
);

ProgressBar.displayName = "ProgressBar";

export { ProgressBar, progressBarTrack, progressBarFill, type ProgressBarProps };
