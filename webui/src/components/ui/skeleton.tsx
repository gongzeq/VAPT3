import { cn } from "@/lib/utils";

/**
 * shadcn/ui Skeleton — a pulsing placeholder for async content. Replaces the
 * ad-hoc ``animate-pulse rounded-* bg-muted`` blocks scattered across loading
 * states so every skeleton shares one motion + radius contract.
 */
function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-muted/60", className)}
      {...props}
    />
  );
}

export { Skeleton };
