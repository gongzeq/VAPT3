import MarkdownTextRenderer from "@/components/MarkdownTextRenderer";

interface MarkdownTextProps {
  children: string;
  className?: string;
}

/**
 * Markdown renderer entry. Historically this was ``Suspense + lazy`` to
 * split the heavy markdown stack into its own chunk, but that caused a
 * visible flash on first paint: the fallback rendered the raw markdown
 * source (with ``#``/``*`` symbols) at the parent font size, and ~0.5s
 * later the real renderer swapped in with ``prose`` typography at a
 * different size. Markdown is core to every assistant turn, so we now
 * import the renderer statically and drop the fallback altogether.
 */
export function preloadMarkdownText(): void {
  // no-op: renderer is bundled with the main chunk now.
}

export function MarkdownText({ children, className }: MarkdownTextProps) {
  return <MarkdownTextRenderer className={className}>{children}</MarkdownTextRenderer>;
}
