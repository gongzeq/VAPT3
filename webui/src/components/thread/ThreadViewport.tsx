import {
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { ArrowDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { UIMessage } from "@/lib/types";

interface ThreadViewportProps {
  messages: UIMessage[];
  isStreaming: boolean;
  composer: ReactNode;
  emptyState?: ReactNode;
  /** Opaque identifier for the active conversation. Whenever it changes, the
   * viewport snaps to the latest message so opening an existing chat always
   * lands the user on the most recent turn instead of wherever the previous
   * chat was scrolled to. */
  resetKey?: string | null;
}

const NEAR_BOTTOM_PX = 48;
/** Hard cap on how long we keep auto-pinning to the bottom while the content
 * column is still expanding (e.g. huge images decoding). After this the user
 * regains full scroll control. */
const ARM_RELEASE_MS = 1500;

export function ThreadViewport({
  messages,
  isStreaming,
  composer,
  emptyState,
  resetKey = null,
}: ThreadViewportProps) {
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const hasMessages = messages.length > 0;
  /** While ``armed`` is true the viewport keeps pinning itself to the bottom
   * as the inner content column grows. Markdown, code blocks, images and fonts
   * keep expanding ``scrollHeight`` for several frames after messages first
   * mount, which is exactly what made a naive ``scrollTo(bottom)`` land at the
   * top of the chat on first open. Cleared on manual scroll or after a short
   * safety window. */
  const armedRef = useRef(true);
  const armTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Mirror of ``atBottom`` so the ResizeObserver callback can read the
   * latest value without being re-subscribed on every state change. */
  const atBottomRef = useRef(true);

  /** Jump (never animate) the scroll container to the very bottom. The user
   * explicitly asked for no smooth scroll \u2014 it was visually distracting on
   * already-long conversations. */
  const jumpToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, []);

  const releaseArm = useCallback(() => {
    armedRef.current = false;
    if (armTimerRef.current !== null) {
      clearTimeout(armTimerRef.current);
      armTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    atBottomRef.current = atBottom;
  }, [atBottom]);

  // Re-arm on every chat switch so opening any conversation \u2014 even one that
  // hits the cached-messages fast path and renders synchronously \u2014 lands on
  // the latest turn.
  useLayoutEffect(() => {
    armedRef.current = true;
    setAtBottom(true);
    jumpToBottom();
    if (armTimerRef.current !== null) clearTimeout(armTimerRef.current);
    armTimerRef.current = setTimeout(() => {
      armedRef.current = false;
      armTimerRef.current = null;
    }, ARM_RELEASE_MS);
    return () => {
      if (armTimerRef.current !== null) {
        clearTimeout(armTimerRef.current);
        armTimerRef.current = null;
      }
    };
  }, [resetKey, jumpToBottom]);

  // Observe the inner content column. While armed, any growth (late-arriving
  // markdown, images, code highlight) immediately re-pins to the bottom. After
  // the arm has been released, we only pin when the user was already at the
  // bottom (classic \"stay pinned while streaming\" behavior).
  useEffect(() => {
    if (!hasMessages) return;
    const content = contentRef.current;
    if (!content) return;
    jumpToBottom();
    const ro = new ResizeObserver(() => {
      if (armedRef.current || atBottomRef.current) jumpToBottom();
    });
    ro.observe(content);
    return () => ro.disconnect();
  }, [hasMessages, resetKey, jumpToBottom]);

  // On ``messages`` updates outside the armed window, keep pinning while the
  // user is already near the bottom. No smooth animation here either.
  useEffect(() => {
    if (armedRef.current) return;
    if (!atBottom) return;
    jumpToBottom();
  }, [messages, isStreaming, atBottom, jumpToBottom]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onScroll = () => {
      // Any manual scroll releases the auto-pin so the user is in control.
      releaseArm();
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      setAtBottom(distance < NEAR_BOTTOM_PX);
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [releaseArm]);

  return (
    <div className="relative flex min-h-0 flex-1 overflow-hidden">
      <div
        ref={scrollRef}
        className={cn(
          "absolute inset-0 overflow-y-auto scrollbar-thin",
          "[&::-webkit-scrollbar]:w-1.5",
          "[&::-webkit-scrollbar-thumb]:rounded-full",
          "[&::-webkit-scrollbar-thumb]:bg-muted-foreground/30",
          "[&::-webkit-scrollbar-track]:bg-transparent",
        )}
      >
        {hasMessages ? (
          <div
            ref={contentRef}
            className="mx-auto flex min-h-full w-full max-w-[64rem] flex-col"
          >
            <div className="flex-1 px-4 pb-20 pt-4">
              <div className="mx-auto w-full max-w-[49.5rem]">
                <ThreadMessages messages={messages} />
              </div>
            </div>

            <div className="sticky bottom-0 z-10 mt-auto bg-gradient-to-b from-transparent via-background/80 to-background/95 backdrop-blur-sm">
              <div className="px-4 pb-3">
                {composer}
              </div>
            </div>
          </div>
        ) : (
          <div className="mx-auto flex min-h-full w-full max-w-[72rem] flex-col px-4">
            <div className="flex w-full flex-1 items-center justify-center pb-[7vh] pt-8">
              <div className="flex w-full max-w-[58rem] flex-col gap-6">
                {emptyState}
                <div className="w-full">{composer}</div>
              </div>
            </div>
          </div>
        )}
      </div>

      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-3 bg-gradient-to-b from-background/60 to-transparent"
      />

      {!atBottom && (
        <Button
          variant="outline"
          size="icon"
          onClick={() => {
            releaseArm();
            jumpToBottom();
          }}
          className={cn(
            "absolute bottom-28 left-1/2 h-8 w-8 -translate-x-1/2 rounded-full shadow-md",
            "bg-background/90 backdrop-blur",
            "animate-in fade-in-0 zoom-in-95",
          )}
          aria-label={t("thread.scrollToBottom")}
        >
          <ArrowDown className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}
