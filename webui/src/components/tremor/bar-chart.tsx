// Source: https://github.com/tremorlabs/tremor/blob/main/src/components/BarChart/BarChart.tsx
// Copied 2026-05-07 for trellis task 05-07-ocean-tech-frontend (PR2).
//
// Adaptations from upstream:
//   - `cx` (Tremor's helper) replaced with the project-local `cn` from
//     `@/lib/utils`.
//   - `chartColors` / `getYAxisDomain` / `useOnWindowResize` imports point
//     at the local `_shared/*` modules.
//   - Legend / ScrollButton / ChartLegend / ChartTooltip extracted into
//     `./_shared/chart-legend.tsx` (also used by AreaChart) per the
//     code-reuse-thinking-guide; those replace the inline upstream copies.
//   - All Tailwind palette literals (gray-200/gray-500/gray-800/gray-50/
//     white/gray-950) substituted with secbot tokens (border / muted /
//     muted-foreground / foreground / popover) in the chart chrome below.
//   - Cursor fill literal `#d1d5db` swept to `hsl(var(--border))` (PR1
//     token) — see Tooltip cursor below.
//   - Removed the upstream `tremor-id="tremor-raw"` attribute (used only
//     for upstream registry filtering).
/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import React from "react";
import {
  Bar,
  CartesianGrid,
  Label,
  BarChart as RechartsBarChart,
  Legend as RechartsLegend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AxisDomain } from "recharts/types/util/types";

import { cn } from "@/lib/utils";

import {
  AvailableChartColors,
  type AvailableChartColorsKeys,
  constructCategoryColors,
  getColorClassName,
} from "./_shared/chart-colors";
import {
  ChartLegend,
  ChartTooltip,
  type SeriesTooltipProps,
} from "./_shared/chart-legend";
import { getYAxisDomain } from "./_shared/chart-utils";

//#region Shape

function deepEqual<T>(obj1: T, obj2: T): boolean {
  if (obj1 === obj2) return true;

  if (
    typeof obj1 !== "object" ||
    typeof obj2 !== "object" ||
    obj1 === null ||
    obj2 === null
  ) {
    return false;
  }

  const keys1 = Object.keys(obj1) as Array<keyof T>;
  const keys2 = Object.keys(obj2) as Array<keyof T>;

  if (keys1.length !== keys2.length) return false;

  for (const key of keys1) {
    if (!keys2.includes(key) || !deepEqual(obj1[key], obj2[key])) return false;
  }

  return true;
}

const renderShape = (
  props: any,
  activeBar: any | undefined,
  activeLegend: string | undefined,
  layout: string,
) => {
  const { fillOpacity, name, payload, value } = props;
  let { x, width, y, height } = props;

  if (layout === "horizontal" && height < 0) {
    y += height;
    height = Math.abs(height);
  } else if (layout === "vertical" && width < 0) {
    x += width;
    width = Math.abs(width);
  }

  return (
    <rect
      x={x}
      y={y}
      width={width}
      height={height}
      opacity={
        activeBar || (activeLegend && activeLegend !== name)
          ? deepEqual(activeBar, { ...payload, value })
            ? fillOpacity
            : 0.3
          : fillOpacity
      }
    />
  );
};

//#region BarChart

type BaseEventProps = {
  eventType: "category" | "bar";
  categoryClicked: string;
  [key: string]: number | string;
};

type BarChartEventProps = BaseEventProps | null | undefined;

type TooltipProps = SeriesTooltipProps;

interface BarChartProps extends React.HTMLAttributes<HTMLDivElement> {
  data: Record<string, any>[];
  index: string;
  categories: string[];
  colors?: AvailableChartColorsKeys[];
  valueFormatter?: (value: number) => string;
  startEndOnly?: boolean;
  showXAxis?: boolean;
  showYAxis?: boolean;
  showGridLines?: boolean;
  yAxisWidth?: number;
  intervalType?: "preserveStartEnd" | "equidistantPreserveStart";
  showTooltip?: boolean;
  showLegend?: boolean;
  autoMinValue?: boolean;
  minValue?: number;
  maxValue?: number;
  allowDecimals?: boolean;
  onValueChange?: (value: BarChartEventProps) => void;
  enableLegendSlider?: boolean;
  tickGap?: number;
  barCategoryGap?: string | number;
  xAxisLabel?: string;
  yAxisLabel?: string;
  layout?: "vertical" | "horizontal";
  type?: "default" | "stacked" | "percent";
  legendPosition?: "left" | "center" | "right";
  tooltipCallback?: (tooltipCallbackContent: TooltipProps) => void;
  customTooltip?: React.ComponentType<TooltipProps>;
}

const BarChart = React.forwardRef<HTMLDivElement, BarChartProps>(
  (props, forwardedRef) => {
    const {
      data = [],
      categories = [],
      index,
      colors = AvailableChartColors,
      valueFormatter = (value: number) => value.toString(),
      startEndOnly = false,
      showXAxis = true,
      showYAxis = true,
      showGridLines = true,
      yAxisWidth = 56,
      intervalType = "equidistantPreserveStart",
      showTooltip = true,
      showLegend = true,
      autoMinValue = false,
      minValue,
      maxValue,
      allowDecimals = true,
      className,
      onValueChange,
      enableLegendSlider = false,
      barCategoryGap,
      tickGap = 5,
      xAxisLabel,
      yAxisLabel,
      layout = "horizontal",
      type = "default",
      legendPosition = "right",
      tooltipCallback,
      customTooltip,
      ...other
    } = props;
    const CustomTooltip = customTooltip;
    const paddingValue =
      (!showXAxis && !showYAxis) || (startEndOnly && !showYAxis) ? 0 : 20;
    const [legendHeight, setLegendHeight] = React.useState(60);
    const [activeLegend, setActiveLegend] = React.useState<string | undefined>(
      undefined,
    );
    const categoryColors = constructCategoryColors(categories, colors);
    const [activeBar, setActiveBar] = React.useState<any | undefined>(undefined);
    const yAxisDomain = getYAxisDomain(autoMinValue, minValue, maxValue);
    const hasOnValueChange = !!onValueChange;
    const stacked = type === "stacked" || type === "percent";

    const prevActiveRef = React.useRef<boolean | undefined>(undefined);
    const prevLabelRef = React.useRef<string | undefined>(undefined);

    function valueToPercent(value: number) {
      return `${(value * 100).toFixed(0)}%`;
    }

    function onBarClick(barData: any, _: any, event: React.MouseEvent) {
      event.stopPropagation();
      if (!onValueChange) return;
      if (deepEqual(activeBar, { ...barData.payload, value: barData.value })) {
        setActiveLegend(undefined);
        setActiveBar(undefined);
        onValueChange?.(null);
      } else {
        setActiveLegend(barData.tooltipPayload?.[0]?.dataKey);
        setActiveBar({
          ...barData.payload,
          value: barData.value,
        });
        onValueChange?.({
          eventType: "bar",
          categoryClicked: barData.tooltipPayload?.[0]?.dataKey,
          ...barData.payload,
        });
      }
    }

    function onCategoryClick(dataKey: string) {
      if (!hasOnValueChange) return;
      if (dataKey === activeLegend && !activeBar) {
        setActiveLegend(undefined);
        onValueChange?.(null);
      } else {
        setActiveLegend(dataKey);
        onValueChange?.({
          eventType: "category",
          categoryClicked: dataKey,
        });
      }
      setActiveBar(undefined);
    }

    return (
      <div
        ref={forwardedRef}
        className={cn("h-80 w-full", className)}
        {...other}
      >
        <ResponsiveContainer>
          <RechartsBarChart
            data={data}
            onClick={
              hasOnValueChange && (activeLegend || activeBar)
                ? () => {
                    setActiveBar(undefined);
                    setActiveLegend(undefined);
                    onValueChange?.(null);
                  }
                : undefined
            }
            margin={{
              bottom: xAxisLabel ? 30 : undefined,
              left: yAxisLabel ? 20 : undefined,
              right: yAxisLabel ? 5 : undefined,
              top: 5,
            }}
            stackOffset={type === "percent" ? "expand" : undefined}
            layout={layout}
            barCategoryGap={barCategoryGap}
          >
            {showGridLines ? (
              <CartesianGrid
                className="stroke-border stroke-1"
                horizontal={layout !== "vertical"}
                vertical={layout === "vertical"}
              />
            ) : null}
            <XAxis
              hide={!showXAxis}
              tick={{
                transform:
                  layout !== "vertical" ? "translate(0, 6)" : undefined,
              }}
              fill=""
              stroke=""
              className={cn(
                "text-xs fill-muted-foreground",
                { "mt-4": layout !== "vertical" },
              )}
              tickLine={false}
              axisLine={false}
              minTickGap={tickGap}
              {...(layout !== "vertical"
                ? {
                    padding: {
                      left: paddingValue,
                      right: paddingValue,
                    },
                    dataKey: index,
                    interval: startEndOnly ? "preserveStartEnd" : intervalType,
                    ticks: startEndOnly
                      ? [data[0]?.[index], data[data.length - 1]?.[index]]
                      : undefined,
                  }
                : {
                    type: "number",
                    domain: yAxisDomain as AxisDomain,
                    tickFormatter:
                      type === "percent" ? valueToPercent : valueFormatter,
                    allowDecimals: allowDecimals,
                  })}
            >
              {xAxisLabel && (
                <Label
                  position="insideBottom"
                  offset={-20}
                  className="fill-foreground text-sm font-medium"
                >
                  {xAxisLabel}
                </Label>
              )}
            </XAxis>
            <YAxis
              width={yAxisWidth}
              hide={!showYAxis}
              axisLine={false}
              tickLine={false}
              fill=""
              stroke=""
              className="text-xs fill-muted-foreground"
              tick={{
                transform:
                  layout !== "vertical"
                    ? "translate(-3, 0)"
                    : "translate(0, 0)",
              }}
              {...(layout !== "vertical"
                ? {
                    type: "number",
                    domain: yAxisDomain as AxisDomain,
                    tickFormatter:
                      type === "percent" ? valueToPercent : valueFormatter,
                    allowDecimals: allowDecimals,
                  }
                : {
                    dataKey: index,
                    ticks: startEndOnly
                      ? [data[0]?.[index], data[data.length - 1]?.[index]]
                      : undefined,
                    type: "category",
                    interval: "equidistantPreserveStart",
                  })}
            >
              {yAxisLabel && (
                <Label
                  position="insideLeft"
                  style={{ textAnchor: "middle" }}
                  angle={-90}
                  offset={-15}
                  className="fill-foreground text-sm font-medium"
                >
                  {yAxisLabel}
                </Label>
              )}
            </YAxis>
            <Tooltip
              wrapperStyle={{ outline: "none" }}
              isAnimationActive={true}
              animationDuration={100}
              cursor={{ fill: "hsl(var(--border))", opacity: "0.15" }}
              offset={20}
              position={{
                y: layout === "horizontal" ? 0 : undefined,
                x: layout === "horizontal" ? undefined : yAxisWidth + 20,
              }}
              content={({ active, payload, label }) => {
                const cleanPayload = payload
                  ? payload.map((item: any) => ({
                      category: item.dataKey,
                      value: item.value,
                      index: item.payload[index],
                      color: categoryColors.get(
                        item.dataKey,
                      ) as AvailableChartColorsKeys,
                      type: item.type,
                      payload: item.payload,
                    }))
                  : [];

                if (
                  tooltipCallback &&
                  (active !== prevActiveRef.current ||
                    label !== prevLabelRef.current)
                ) {
                  tooltipCallback({ active, payload: cleanPayload, label });
                  prevActiveRef.current = active;
                  prevLabelRef.current = label;
                }

                return showTooltip && active ? (
                  CustomTooltip ? (
                    <CustomTooltip
                      active={active}
                      payload={cleanPayload}
                      label={label}
                    />
                  ) : (
                    <ChartTooltip
                      active={active}
                      payload={cleanPayload}
                      label={label}
                      valueFormatter={valueFormatter}
                    />
                  )
                ) : null;
              }}
            />
            {showLegend ? (
              <RechartsLegend
                verticalAlign="top"
                height={legendHeight}
                content={({ payload }) =>
                  ChartLegend(
                    { payload },
                    categoryColors,
                    setLegendHeight,
                    activeLegend,
                    hasOnValueChange
                      ? (clickedLegendItem: string) =>
                          onCategoryClick(clickedLegendItem)
                      : undefined,
                    enableLegendSlider,
                    legendPosition,
                    yAxisWidth,
                  )
                }
              />
            ) : null}
            {categories.map((category) => (
              <Bar
                className={cn(
                  getColorClassName(
                    categoryColors.get(category) as AvailableChartColorsKeys,
                    "fill",
                  ),
                  onValueChange ? "cursor-pointer" : "",
                )}
                key={category}
                name={category}
                type="linear"
                dataKey={category}
                stackId={stacked ? "stack" : undefined}
                isAnimationActive={false}
                fill=""
                shape={(barShapeProps: any) =>
                  renderShape(barShapeProps, activeBar, activeLegend, layout)
                }
                onClick={onBarClick}
              />
            ))}
          </RechartsBarChart>
        </ResponsiveContainer>
      </div>
    );
  },
);

BarChart.displayName = "BarChart";

export {
  BarChart,
  type BarChartEventProps,
  type BarChartProps,
  type TooltipProps,
};
