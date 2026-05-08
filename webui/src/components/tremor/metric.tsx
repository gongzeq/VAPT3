// Source: https://github.com/tremorlabs/tremor-npm/blob/main/src/components/text-elements/Metric/Metric.tsx
// Copied 2026-05-07 for trellis task 05-07-ocean-tech-frontend (PR2).
//
// Adaptations from upstream:
//   - The upstream component pulls a Tremor color helper to map a `color`
//     prop to a Tailwind text-color class. Since our chart palette already
//     uses our PR1 tokens, the slimmed-down version accepts a className
//     instead — call sites should pass `text-primary`, `text-severity-critical`,
//     etc. when they want a non-default color. Default text uses
//     `text-foreground` so the metric stays legible in both modes.
//   - The font size mirrors Tremor's `text-tremor-metric` (~30px / `text-3xl`
//     in standard Tailwind scale). Adjust via `className` for layout-specific
//     overrides.

import * as React from "react";

import { cn } from "@/lib/utils";

export interface MetricProps
  extends React.HTMLAttributes<HTMLParagraphElement> {
  /**
   * Optional Tailwind text-color utility (e.g. `"text-primary"`) to override
   * the default `text-foreground`. Pass through `className` for compound
   * overrides (size, weight).
   */
  color?: string;
}

/**
 * Metric — large emphasized number, typically used as the value of a KPI
 * card. Compose with our shadcn `Card` (or any container) for the full KPI
 * surface; the component itself is just the styled paragraph.
 */
const Metric = React.forwardRef<HTMLParagraphElement, MetricProps>(
  (props, ref) => {
    const { color, children, className, ...other } = props;
    return (
      <p
        ref={ref}
        className={cn(
          "text-3xl font-semibold tracking-tight tabular-nums",
          color ?? "text-foreground",
          className,
        )}
        {...other}
      >
        {children}
      </p>
    );
  },
);

Metric.displayName = "Metric";

export { Metric };
