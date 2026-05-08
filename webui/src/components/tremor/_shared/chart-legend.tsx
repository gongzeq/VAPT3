// Shared Tremor Raw chart UI primitives (Legend + Tooltip) used by both
// AreaChart and BarChart. Extracted 2026-05-07 from the upstream copies
// for trellis task 05-07-ocean-tech-frontend (PR2) — both charts share
// identical Legend / ScrollButton / ChartTooltip definitions; consolidating
// here follows the code-reuse-thinking-guide and keeps the per-chart files
// focused on chart-type-specific recharts plumbing.
//
// Adaptations from upstream (same set as the per-chart files):
//   - `cx` replaced with the project-local `cn` from `@/lib/utils`.
//   - `@remixicon/react` icons replaced with `lucide-react` equivalents.
//   - All Tailwind palette literals (gray-100/gray-200/gray-300/gray-500/
//     gray-700/gray-800/gray-900/gray-50/gray-950/white) substituted with
//     PR1 secbot tokens (border / muted / muted-foreground / foreground /
//     popover).
/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

import {
  AvailableChartColors,
  type AvailableChartColorsKeys,
  getColorClassName,
} from "./chart-colors";
import { useOnWindowResize } from "./use-on-window-resize";

interface LegendItemProps {
  name: string;
  color: AvailableChartColorsKeys;
  onClick?: (name: string, color: AvailableChartColorsKeys) => void;
  activeLegend?: string;
}

const LegendItem = ({
  name,
  color,
  onClick,
  activeLegend,
}: LegendItemProps) => {
  const hasOnValueChange = !!onClick;
  return (
    <li
      className={cn(
        "group inline-flex flex-nowrap items-center gap-1.5 rounded-sm px-2 py-1 whitespace-nowrap transition",
        hasOnValueChange
          ? "cursor-pointer hover:bg-muted"
          : "cursor-default",
      )}
      onClick={(e) => {
        e.stopPropagation();
        onClick?.(name, color);
      }}
    >
      <span
        className={cn(
          "h-[3px] w-3.5 shrink-0 rounded-full",
          getColorClassName(color, "bg"),
          activeLegend && activeLegend !== name ? "opacity-40" : "opacity-100",
        )}
        aria-hidden={true}
      />
      <p
        className={cn(
          "truncate text-xs whitespace-nowrap text-muted-foreground",
          hasOnValueChange && "group-hover:text-foreground",
          activeLegend && activeLegend !== name ? "opacity-40" : "opacity-100",
        )}
      >
        {name}
      </p>
    </li>
  );
};

interface ScrollButtonProps {
  icon: React.ElementType;
  onClick?: () => void;
  disabled?: boolean;
}

const ScrollButton = ({ icon, onClick, disabled }: ScrollButtonProps) => {
  const Icon = icon;
  const [isPressed, setIsPressed] = React.useState(false);
  const intervalRef = React.useRef<ReturnType<typeof setInterval> | null>(null);

  React.useEffect(() => {
    if (isPressed) {
      intervalRef.current = setInterval(() => {
        onClick?.();
      }, 300);
    } else if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isPressed, onClick]);

  React.useEffect(() => {
    if (disabled && intervalRef.current) {
      clearInterval(intervalRef.current);
      setIsPressed(false);
    }
  }, [disabled]);

  return (
    <button
      type="button"
      className={cn(
        "group inline-flex size-5 items-center truncate rounded-sm transition",
        disabled
          ? "cursor-not-allowed text-muted-foreground/50"
          : "cursor-pointer text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
      onMouseDown={(e) => {
        e.stopPropagation();
        setIsPressed(true);
      }}
      onMouseUp={(e) => {
        e.stopPropagation();
        setIsPressed(false);
      }}
    >
      <Icon className="size-full" aria-hidden="true" />
    </button>
  );
};

export interface LegendProps extends React.OlHTMLAttributes<HTMLOListElement> {
  categories: string[];
  colors?: AvailableChartColorsKeys[];
  onClickLegendItem?: (category: string, color: string) => void;
  activeLegend?: string;
  enableLegendSlider?: boolean;
}

type HasScrollProps = {
  left: boolean;
  right: boolean;
};

export const Legend = React.forwardRef<HTMLOListElement, LegendProps>(
  (props, ref) => {
    const {
      categories,
      colors = AvailableChartColors,
      className,
      onClickLegendItem,
      activeLegend,
      enableLegendSlider = false,
      ...other
    } = props;
    const scrollableRef = React.useRef<HTMLDivElement>(null);
    const scrollButtonsRef = React.useRef<HTMLDivElement>(null);
    const [hasScroll, setHasScroll] = React.useState<HasScrollProps | null>(
      null,
    );
    const [isKeyDowned, setIsKeyDowned] = React.useState<string | null>(null);
    const intervalRef = React.useRef<ReturnType<typeof setInterval> | null>(
      null,
    );

    const checkScroll = React.useCallback(() => {
      const scrollable = scrollableRef?.current;
      if (!scrollable) return;

      const hasLeftScroll = scrollable.scrollLeft > 0;
      const hasRightScroll =
        scrollable.scrollWidth - scrollable.clientWidth > scrollable.scrollLeft;

      setHasScroll({ left: hasLeftScroll, right: hasRightScroll });
    }, []);

    const scrollToTest = React.useCallback(
      (direction: "left" | "right") => {
        const element = scrollableRef?.current;
        const scrollButtons = scrollButtonsRef?.current;
        const scrollButtonsWith = scrollButtons?.clientWidth ?? 0;
        const width = element?.clientWidth ?? 0;

        if (element && enableLegendSlider) {
          element.scrollTo({
            left:
              direction === "left"
                ? element.scrollLeft - width + scrollButtonsWith
                : element.scrollLeft + width - scrollButtonsWith,
            behavior: "smooth",
          });
          setTimeout(() => {
            checkScroll();
          }, 400);
        }
      },
      [enableLegendSlider, checkScroll],
    );

    React.useEffect(() => {
      const keyDownHandler = (key: string) => {
        if (key === "ArrowLeft") {
          scrollToTest("left");
        } else if (key === "ArrowRight") {
          scrollToTest("right");
        }
      };
      if (isKeyDowned) {
        keyDownHandler(isKeyDowned);
        intervalRef.current = setInterval(() => {
          keyDownHandler(isKeyDowned);
        }, 300);
      } else if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
      return () => {
        if (intervalRef.current) clearInterval(intervalRef.current);
      };
    }, [isKeyDowned, scrollToTest]);

    React.useEffect(() => {
      const scrollable = scrollableRef?.current;
      const keyDown = (e: KeyboardEvent) => {
        e.stopPropagation();
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          setIsKeyDowned(e.key);
        }
      };
      const keyUp = (e: KeyboardEvent) => {
        e.stopPropagation();
        setIsKeyDowned(null);
      };
      if (enableLegendSlider) {
        checkScroll();
        scrollable?.addEventListener("keydown", keyDown);
        scrollable?.addEventListener("keyup", keyUp);
      }

      return () => {
        scrollable?.removeEventListener("keydown", keyDown);
        scrollable?.removeEventListener("keyup", keyUp);
      };
    }, [checkScroll, enableLegendSlider]);

    return (
      <ol
        ref={ref}
        className={cn("relative overflow-hidden", className)}
        {...other}
      >
        <div
          ref={scrollableRef}
          tabIndex={0}
          className={cn(
            "flex h-full",
            enableLegendSlider
              ? hasScroll?.right || hasScroll?.left
                ? "snap-mandatory items-center overflow-auto pr-12 pl-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
                : ""
              : "flex-wrap",
          )}
        >
          {categories.map((category, index) => (
            <LegendItem
              key={`item-${index}`}
              name={category}
              color={colors[index] as AvailableChartColorsKeys}
              onClick={onClickLegendItem}
              activeLegend={activeLegend}
            />
          ))}
        </div>
        {enableLegendSlider && (hasScroll?.right || hasScroll?.left) ? (
          <div
            ref={scrollButtonsRef}
            className="absolute top-0 right-0 bottom-0 flex h-full items-center justify-center pr-1 bg-popover"
          >
            <ScrollButton
              icon={ChevronLeft}
              onClick={() => {
                setIsKeyDowned(null);
                scrollToTest("left");
              }}
              disabled={!hasScroll?.left}
            />
            <ScrollButton
              icon={ChevronRight}
              onClick={() => {
                setIsKeyDowned(null);
                scrollToTest("right");
              }}
              disabled={!hasScroll?.right}
            />
          </div>
        ) : null}
      </ol>
    );
  },
);

Legend.displayName = "Legend";

export const ChartLegend = (
  { payload }: any,
  categoryColors: Map<string, AvailableChartColorsKeys>,
  setLegendHeight: React.Dispatch<React.SetStateAction<number>>,
  activeLegend: string | undefined,
  onClick?: (category: string, color: string) => void,
  enableLegendSlider?: boolean,
  legendPosition?: "left" | "center" | "right",
  yAxisWidth?: number,
) => {
  const legendRef = React.useRef<HTMLDivElement>(null);

  useOnWindowResize(() => {
    const calculateHeight = (height: number | undefined) =>
      height ? Number(height) + 15 : 60;
    setLegendHeight(calculateHeight(legendRef.current?.clientHeight));
  });

  const legendPayload = payload.filter((item: any) => item.type !== "none");

  const paddingLeft =
    legendPosition === "left" && yAxisWidth ? yAxisWidth - 8 : 0;

  return (
    <div
      ref={legendRef}
      style={{ paddingLeft: paddingLeft }}
      className={cn(
        "flex items-center",
        { "justify-center": legendPosition === "center" },
        { "justify-start": legendPosition === "left" },
        { "justify-end": legendPosition === "right" },
      )}
    >
      <Legend
        categories={legendPayload.map((entry: any) => entry.value)}
        colors={legendPayload.map((entry: any) =>
          categoryColors.get(entry.value),
        )}
        onClickLegendItem={onClick}
        activeLegend={activeLegend}
        enableLegendSlider={enableLegendSlider}
      />
    </div>
  );
};

//#region Tooltip

export type SeriesTooltipPayloadItem = {
  category: string;
  value: number;
  index: string;
  color: AvailableChartColorsKeys;
  type?: string;
  payload: any;
};

export interface ChartTooltipProps {
  active: boolean | undefined;
  payload: SeriesTooltipPayloadItem[];
  label: string;
  valueFormatter: (value: number) => string;
}

export type SeriesTooltipProps = Pick<
  ChartTooltipProps,
  "active" | "payload" | "label"
>;

export const ChartTooltip = ({
  active,
  payload,
  label,
  valueFormatter,
}: ChartTooltipProps) => {
  if (active && payload && payload.length) {
    return (
      <div className="rounded-md border border-border bg-popover text-sm shadow-md">
        <div className="border-b border-inherit px-4 py-2">
          <p className="font-medium text-foreground">{label}</p>
        </div>
        <div className="space-y-1 px-4 py-2">
          {payload.map(({ value, category, color }, index) => (
            <div
              key={`id-${index}`}
              className="flex items-center justify-between space-x-8"
            >
              <div className="flex items-center space-x-2">
                <span
                  aria-hidden="true"
                  className={cn(
                    "h-[3px] w-3.5 shrink-0 rounded-full",
                    getColorClassName(color, "bg"),
                  )}
                />
                <p className="text-right whitespace-nowrap text-muted-foreground">
                  {category}
                </p>
              </div>
              <p className="text-right font-medium whitespace-nowrap tabular-nums text-foreground">
                {valueFormatter(value)}
              </p>
            </div>
          ))}
        </div>
      </div>
    );
  }
  return null;
};
