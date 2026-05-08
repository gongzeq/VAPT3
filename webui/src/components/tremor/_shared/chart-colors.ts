// Source: https://github.com/tremorlabs/tremor/blob/main/src/utils/chartColors.ts
// Copied 2026-05-07 for trellis task 05-07-ocean-tech-frontend (PR2).
//
// Adaptations from upstream:
//   - First palette key is `primary`, mapped to our ocean-blue token via the
//     `bg-primary / fill-primary / stroke-primary / text-primary` Tailwind
//     classes already wired in `tailwind.config.js`. This means default
//     chart series colors stay on-brand without a per-call-site override.
//   - The remaining keys reuse our existing severity / state tokens
//     (success / warning / sev-high / sev-medium / sev-info) so chart series
//     map cleanly onto the palette already used by skill renderers.
//   - The ALL upstream Tailwind palette literals (blue/emerald/violet/...)
//     are replaced with our token-backed Tailwind colors; no raw hex.

export type ColorUtility = "bg" | "stroke" | "fill" | "text";

/**
 * Chart palette for Tremor Raw components. Uses semantic tokens from
 * `tailwind.config.js → theme.extend.colors` so charts respond to the
 * secbot dark + light theme variants (theme-tokens.md §1, §3, §3.5).
 */
export const chartColors = {
  primary: {
    bg: "bg-primary",
    stroke: "stroke-primary",
    fill: "fill-primary",
    text: "text-primary",
  },
  success: {
    bg: "bg-success",
    stroke: "stroke-success",
    fill: "fill-success",
    text: "text-success",
  },
  warning: {
    bg: "bg-warning",
    stroke: "stroke-warning",
    fill: "fill-warning",
    text: "text-warning",
  },
  high: {
    bg: "bg-severity-high",
    stroke: "stroke-severity-high",
    fill: "fill-severity-high",
    text: "text-severity-high",
  },
  medium: {
    bg: "bg-severity-medium",
    stroke: "stroke-severity-medium",
    fill: "fill-severity-medium",
    text: "text-severity-medium",
  },
  low: {
    bg: "bg-severity-low",
    stroke: "stroke-severity-low",
    fill: "fill-severity-low",
    text: "text-severity-low",
  },
  critical: {
    bg: "bg-severity-critical",
    stroke: "stroke-severity-critical",
    fill: "fill-severity-critical",
    text: "text-severity-critical",
  },
  info: {
    bg: "bg-info",
    stroke: "stroke-info",
    fill: "fill-info",
    text: "text-info",
  },
  muted: {
    bg: "bg-muted-foreground",
    stroke: "stroke-muted-foreground",
    fill: "fill-muted-foreground",
    text: "text-muted-foreground",
  },
} as const satisfies {
  [color: string]: {
    [key in ColorUtility]: string;
  };
};

export type AvailableChartColorsKeys = keyof typeof chartColors;

export const AvailableChartColors: AvailableChartColorsKeys[] = Object.keys(
  chartColors,
) as Array<AvailableChartColorsKeys>;

export const constructCategoryColors = (
  categories: string[],
  colors: AvailableChartColorsKeys[],
): Map<string, AvailableChartColorsKeys> => {
  const categoryColors = new Map<string, AvailableChartColorsKeys>();
  categories.forEach((category, index) => {
    categoryColors.set(category, colors[index % colors.length]);
  });
  return categoryColors;
};

export const getColorClassName = (
  color: AvailableChartColorsKeys,
  type: ColorUtility,
): string => {
  const fallbackColor = {
    bg: "bg-muted-foreground",
    stroke: "stroke-muted-foreground",
    fill: "fill-muted-foreground",
    text: "text-muted-foreground",
  };
  return chartColors[color]?.[type] ?? fallbackColor[type];
};
