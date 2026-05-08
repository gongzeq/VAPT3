// Source: https://magicui.design/r/animated-shiny-text.json — copied 2026-05-07
// for trellis task 05-07-ocean-tech-frontend (PR2).
//
// Adaptations from upstream:
//   - Tailwind v4 utilities (`bg-size-[...]`, `bg-position-[...]`, `bg-linear-to-r`)
//     rewritten as v3.4 bracketed arbitrary values
//     (`[background-size:...]`, `[background-position:...]`,
//     `bg-gradient-to-r`).
//   - The `animate-shiny-text` utility requires the `shiny-text` keyframe
//     registered in `tailwind.config.js`.
//   - Color stops switched from upstream's `via-black/80 dark:via-white/80`
//     hardcoded blacks/whites to `via-foreground/80` token to follow
//     theme-tokens.md (no raw hex / dark-only colors).

import {
  type ComponentPropsWithoutRef,
  type CSSProperties,
  type FC,
} from "react";

import { cn } from "@/lib/utils";

export interface AnimatedShinyTextProps
  extends ComponentPropsWithoutRef<"span"> {
  shimmerWidth?: number;
}

export const AnimatedShinyText: FC<AnimatedShinyTextProps> = ({
  children,
  className,
  shimmerWidth = 100,
  ...props
}) => {
  return (
    <span
      style={
        {
          "--shiny-width": `${shimmerWidth}px`,
        } as CSSProperties
      }
      className={cn(
        "mx-auto max-w-md text-muted-foreground",

        // Shine effect
        "animate-shiny-text bg-clip-text bg-no-repeat",
        "[background-size:var(--shiny-width)_100%]",
        "[background-position:0_0]",
        "[transition:background-position_1s_cubic-bezier(.6,.6,0,1)_infinite]",

        // Shine gradient — uses the foreground token so the streak inherits
        // theme. The 80% alpha keeps the text legible during the sweep.
        "bg-gradient-to-r from-transparent via-foreground/80 to-transparent",

        className,
      )}
      {...props}
    >
      {children}
    </span>
  );
};
