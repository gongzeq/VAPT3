import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * shadcn/ui (new-york) Badge. Unifies the 23+ hand-written status pills that
 * previously mixed text-[10px]/[11px]/xs sizes and raw emerald/rose/white
 * colors. All variants are token-driven (no raw hex) per the project red-line.
 *
 * Solid variants (default/secondary/destructive/outline) mirror upstream
 * shadcn; soft state variants (success/warning/info) match the security
 * dashboard's tinted-pill convention (bg-x/10 border-x/30 text-x).
 */
const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground",
        outline: "border-border text-foreground",
        success:
          "border-alert-success/30 bg-alert-success/10 text-alert-success",
        warning:
          "border-alert-warning/30 bg-alert-warning/10 text-alert-warning",
        info: "border-primary/30 bg-primary/10 text-primary",
        muted:
          "border-border/60 bg-muted/40 text-muted-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
