// Source: https://github.com/tremorlabs/tremor/blob/main/src/components/Callout/Callout.tsx
// Copied 2026-05-07 for trellis task 05-07-ocean-tech-frontend (PR2).
//
// Adaptations from upstream:
//   - `tv` (tailwind-variants) replaced with `cva` (class-variance-authority,
//     already in our deps) — same expressive power for non-slot variants.
//   - Variant background/text classes remapped from raw Tailwind palette
//     literals (`text-blue-900 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/70`)
//     to our PR1 semantic state tokens (info / success / error / warning) so
//     the component renders in the secbot ocean theme without bypassing
//     `theme-tokens.md §1` (no raw hex / palette literals that ignore the
//     design system).
//   - `cx` replaced with the project-local `cn` from `@/lib/utils`.

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const calloutVariants = cva(
  "flex flex-col overflow-hidden rounded-md p-4 text-sm",
  {
    variants: {
      variant: {
        default: "bg-info/10 text-info",
        success: "bg-success/10 text-success",
        error: "bg-error/10 text-error",
        warning: "bg-warning/10 text-warning",
        neutral: "bg-muted text-muted-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

interface CalloutProps
  extends React.ComponentPropsWithoutRef<"div">,
    VariantProps<typeof calloutVariants> {
  title: string;
  icon?: React.ElementType | React.ReactElement;
}

const Callout = React.forwardRef<HTMLDivElement, CalloutProps>(
  (
    { title, icon: Icon, className, variant, children, ...props }: CalloutProps,
    forwardedRef,
  ) => {
    return (
      <div
        ref={forwardedRef}
        className={cn(calloutVariants({ variant }), className)}
        {...props}
      >
        <div className="flex items-start">
          {Icon && typeof Icon === "function" ? (
            <Icon className="mr-1.5 h-5 w-5 shrink-0" aria-hidden="true" />
          ) : (
            Icon
          )}
          <span className="font-semibold">{title}</span>
        </div>
        <div className={cn("overflow-y-auto", children ? "mt-2" : "")}>
          {children}
        </div>
      </div>
    );
  },
);

Callout.displayName = "Callout";

export { Callout, calloutVariants, type CalloutProps };
