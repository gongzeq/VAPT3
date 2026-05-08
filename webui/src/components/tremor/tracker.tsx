// Source: https://github.com/tremorlabs/tremor/blob/main/src/components/Tracker/Tracker.tsx
// Copied 2026-05-07 for trellis task 05-07-ocean-tech-frontend (PR2).
//
// Adaptations from upstream:
//   - The upstream HoverCard tooltip uses `@radix-ui/react-hover-card`, which
//     is not in our deps and is not on the PR2 install list. Replaced with a
//     native `title` attribute for accessible tooltip behavior. If a richer
//     hover surface is needed in PR4+, swap to our existing `@radix-ui/react-tooltip`
//     wrapper from `@/components/ui/tooltip` — keeps the dep budget stable.
//   - `cx` replaced with the project-local `cn` from `@/lib/utils`.
//   - Default block background switched from `bg-gray-400 dark:bg-gray-400`
//     literals to `bg-muted-foreground` token so the empty-state phase color
//     reads as "neutral / informational" in both dark and light secbot modes.

import * as React from "react";

import { cn } from "@/lib/utils";

interface TrackerBlockProps {
  key?: string | number;
  /**
   * Tailwind background class for the filled block (e.g. `"bg-primary"`,
   * `"bg-success"`). When omitted, falls back to `defaultBackgroundColor`
   * from the parent `<Tracker>`.
   */
  color?: string;
  /** Native `title` tooltip on hover. */
  tooltip?: string;
  hoverEffect?: boolean;
  defaultBackgroundColor?: string;
}

const Block = ({
  color,
  tooltip,
  defaultBackgroundColor,
  hoverEffect,
}: TrackerBlockProps) => {
  return (
    <div
      title={tooltip}
      className="size-full overflow-hidden px-[0.5px] transition first:rounded-l-[4px] first:pl-0 last:rounded-r-[4px] last:pr-0 sm:px-px"
    >
      <div
        className={cn(
          "size-full rounded-[1px]",
          color || defaultBackgroundColor,
          hoverEffect ? "hover:opacity-50" : "",
        )}
      />
    </div>
  );
};

Block.displayName = "Block";

interface TrackerProps extends React.HTMLAttributes<HTMLDivElement> {
  data: TrackerBlockProps[];
  defaultBackgroundColor?: string;
  hoverEffect?: boolean;
}

const Tracker = React.forwardRef<HTMLDivElement, TrackerProps>(
  (
    {
      data = [],
      defaultBackgroundColor = "bg-muted-foreground",
      className,
      hoverEffect,
      ...props
    },
    forwardedRef,
  ) => {
    return (
      <div
        ref={forwardedRef}
        className={cn("group flex h-8 w-full items-center", className)}
        {...props}
      >
        {data.map((blockProps, index) => (
          <Block
            key={blockProps.key ?? index}
            defaultBackgroundColor={defaultBackgroundColor}
            hoverEffect={hoverEffect}
            {...blockProps}
          />
        ))}
      </div>
    );
  },
);

Tracker.displayName = "Tracker";

export { Tracker, type TrackerBlockProps, type TrackerProps };
