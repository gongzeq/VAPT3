import { useCallback, useEffect, useRef, useState } from "react";
import { BrainCircuit, Check, ChevronRight, Copy, FileIcon, ImageIcon, PlaySquare, User } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AgentAvatar, AgentMeta } from "@/components/AgentAvatar";
import { ImageLightbox } from "@/components/ImageLightbox";
import { MarkdownText } from "@/components/MarkdownText";
import { TurnUsageBadge } from "@/components/TokenUsageBadge";
import { isHiddenFrontendToolName } from "@/lib/tool-visibility";
import { cn } from "@/lib/utils";
import { AgentEventCard, isVisibleAgentEvent } from "@/components/message/AgentEventCard";
import { ToolCallGroup } from "@/components/message/ToolCallGroup";
import type { UIImage, UIMediaAttachment, UIMessage } from "@/lib/types";

interface MessageBubbleProps {
  message: UIMessage;
}

/**
 * Render a single message. Following agent-chat-ui: user turns are a rounded
 * "pill" right-aligned with a muted fill; assistant turns render as bare
 * markdown so prose/code read like a document rather than a chat bubble.
 * Each turn fades+slides in for a touch of motion polish.
 *
 * Trace rows (tool-call hints, progress breadcrumbs) render as a subdued
 * collapsible group so intermediate steps never masquerade as replies.
 */
export function MessageBubble({ message }: MessageBubbleProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const copyResetRef = useRef<number | null>(null);
  const baseAnim = "animate-in fade-in-0 slide-in-from-bottom-1 duration-300";

  useEffect(() => {
    return () => {
      if (copyResetRef.current !== null) {
        window.clearTimeout(copyResetRef.current);
      }
    };
  }, []);

  const onCopyAssistantReply = useCallback(() => {
    if (!navigator.clipboard) return;
    void navigator.clipboard.writeText(message.content).then(() => {
      setCopied(true);
      if (copyResetRef.current !== null) {
        window.clearTimeout(copyResetRef.current);
      }
      copyResetRef.current = window.setTimeout(() => {
        setCopied(false);
        copyResetRef.current = null;
      }, 1_500);
    });
  }, [message.content]);

  if (message.kind === "trace") {
    return <TraceGroup message={message} animClass={baseAnim} />;
  }

  if (message.kind === "agent_event" && message.agentEvent) {
    if (!isVisibleAgentEvent(message.agentEvent)) {
      return null;
    }
    return (
      <div className={cn("flex gap-3", baseAnim)}>
        <AgentAvatar agentName={message.agentName} size="md" />
        <div className="max-w-[80%] min-w-0 space-y-2">
          <AgentMeta agentName={message.agentName} />
          <AgentEventCard payload={message.agentEvent} agentName={message.agentName} />
        </div>
      </div>
    );
  }

  if (message.role === "user") {
    const images = message.images ?? [];
    const media = message.media ?? [];
    const hasImages = images.length > 0;
    const hasMedia = media.length > 0;
    const hasText = message.content.trim().length > 0;
    return (
      <div
        className={cn(
          "group flex gap-3 justify-end",
          baseAnim,
        )}
      >
        <div className="flex max-w-[70%] flex-col items-end gap-1.5">
          {hasImages ? <UserImages images={images} align="right" /> : null}
          {!hasImages && hasMedia ? (
            <MessageMedia media={media} align="right" />
          ) : null}
          {hasText ? (
            <p
              className={cn(
                "rounded-2xl rounded-tr-sm gradient-primary px-4 py-2.5 text-sm text-white shadow-md",
                "text-left whitespace-pre-wrap break-words",
              )}
            >
              {message.content}
            </p>
          ) : null}
        </div>
        <div
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg font-bold text-white shadow-sm"
          style={{ background: "linear-gradient(135deg, hsl(210 100% 56%), hsl(195 100% 60%))" }}
        >
          <User className="h-4 w-4" aria-hidden />
        </div>
      </div>
    );
  }

  const empty = message.content.trim().length === 0;
  const media = message.media ?? [];
  const visibleToolCalls =
    message.toolCalls?.filter((tc) => !isHiddenFrontendToolName(tc.tool_name)) ?? [];
  const hasToolCalls = visibleToolCalls.length > 0;
  const showTypingPlaceholder = empty && message.isStreaming && !hasToolCalls && media.length === 0;
  // 隐藏空内容的助手消息（无内容、无媒体、无工具调用、非流式）
  if (empty && !message.isStreaming && media.length === 0 && !hasToolCalls) {
    return null;
  }
  const showAssistantActions = message.role === "assistant" && !message.isStreaming && !empty;
  return (
    <div className={cn("flex gap-3", baseAnim)}>
      <AgentAvatar agentName={message.agentName} size="md" />
      <div className="max-w-[80%] min-w-0 space-y-2">
        <AgentMeta agentName={message.agentName} />
        {showTypingPlaceholder ? (
          <TypingDots />
        ) : (
          <>
            <div
              className={cn(
                "text-sm leading-relaxed",
                "break-words whitespace-pre-wrap",
              )}
            >
              {!empty ? <MarkdownText>{message.content}</MarkdownText> : null}
              {message.isStreaming && !empty ? <StreamCursor /> : null}
            </div>
            {/* Aggregate every command from this subagent into one
                collapsed-by-default bubble instead of N detached cards. */}
            {visibleToolCalls.length > 0 ? (
              <div className="mt-3">
                <ToolCallGroup calls={visibleToolCalls} />
              </div>
            ) : null}
            {media.length > 0 ? <MessageMedia media={media} align="left" /> : null}
            {showAssistantActions ? (
              <div className="flex items-center gap-1 text-muted-foreground">
                <button
                  type="button"
                  onClick={onCopyAssistantReply}
                  aria-label={copied ? t("message.copiedReply") : t("message.copyReply")}
                  title={copied ? t("message.copiedReply") : t("message.copyReply")}
                  className={cn(
                    "inline-flex h-8 w-8 items-center justify-center rounded-full",
                    "transition-colors hover:bg-muted/55 hover:text-foreground",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  )}
                >
                  {copied ? (
                    <Check className="h-4 w-4" aria-hidden />
                  ) : (
                    <Copy className="h-4 w-4" aria-hidden />
                  )}
                </button>
                {message.turnUsage ? (
                  <TurnUsageBadge usage={message.turnUsage} />
                ) : null}
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function MessageMedia({
  media,
  align,
}: {
  media: UIMediaAttachment[];
  align: "left" | "right";
}) {
  if (media.length === 0) return null;
  const images = media
    .filter((item) => item.kind === "image")
    .map(({ url, name }) => ({ url, name }));
  const nonImages = media.filter((item) => item.kind !== "image");

  return (
    <div
      className={cn(
        "mt-2 flex flex-wrap gap-2",
        align === "right" ? "justify-end" : "justify-start",
      )}
    >
      {images.length > 0 ? <UserImages images={images} align={align} /> : null}
      {nonImages.map((item, i) => (
        <MediaCell key={`${item.url ?? item.name ?? item.kind}-${i}`} media={item} />
      ))}
    </div>
  );
}

function MediaCell({ media }: { media: UIMediaAttachment }) {
  const { t } = useTranslation();
  const hasUrl = typeof media.url === "string" && media.url.length > 0;

  if (media.kind === "video" && hasUrl) {
    return (
      <figure className="max-w-[min(100%,32rem)] overflow-hidden rounded-[14px] border border-border/60 bg-muted/40">
        <video
          src={media.url}
          controls
          preload="metadata"
          className="block max-h-[26rem] w-full bg-black"
          aria-label={media.name ? `${t("message.videoAttachment", { defaultValue: "Video attachment" })}: ${media.name}` : t("message.videoAttachment", { defaultValue: "Video attachment" })}
        />
        {media.name ? (
          <figcaption className="truncate px-3 py-1.5 text-xs text-muted-foreground">
            {media.name}
          </figcaption>
        ) : null}
      </figure>
    );
  }

  const label =
    media.kind === "video"
      ? t("message.videoAttachment", { defaultValue: "Video attachment" })
      : t("message.fileAttachment", { defaultValue: "File attachment" });
  const Icon = media.kind === "video" ? PlaySquare : FileIcon;

  // Check if this is an HTML report file
  const isHtmlReport = media.kind === "file" && media.name?.toLowerCase().endsWith(".html");

  const cellInner = (
    <>
      <Icon className="h-4 w-4 flex-none" aria-hidden />
      <span className="truncate">{media.name ?? label}</span>
    </>
  );

  if (media.kind === "file" && hasUrl) {
    // Special styling for HTML reports - wider, more prominent
    if (isHtmlReport) {
      return (
        <a
          href={media.url}
          download={media.name ?? undefined}
          className={cn(
            "group flex w-full max-w-[min(75%,36rem)] items-center gap-3",
            "rounded-2xl border-2 border-primary/20 bg-gradient-to-br from-primary/8 to-primary/4",
            "px-4 py-3.5 shadow-md transition-all duration-200",
            "hover:shadow-lg hover:border-primary/35 hover:from-primary/12 hover:to-primary/6",
          )}
          title={media.name ?? undefined}
          aria-label={`${label}: ${media.name ?? ""}`}
        >
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary group-hover:bg-primary/20 transition-colors">
            <FileIcon className="h-5 w-5" aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-foreground">
              {media.name ?? label}
            </div>
            <div className="text-xs text-muted-foreground">
              点击下载 HTML 报告
            </div>
          </div>
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground group-hover:text-primary transition-colors" aria-hidden />
        </a>
      );
    }

    // Default file styling
    return (
      <a
        href={media.url}
        download={media.name ?? undefined}
        className="flex max-w-[18rem] items-center gap-2 rounded-[14px] border border-border/60 bg-muted/40 px-3 py-2 text-xs text-muted-foreground hover:bg-muted/60 transition-colors"
        title={media.name ?? undefined}
        aria-label={label}
      >
        {cellInner}
      </a>
    );
  }

  return (
    <div
      className="flex max-w-[18rem] items-center gap-2 rounded-[14px] border border-border/60 bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
      title={media.name ?? undefined}
      aria-label={label}
    >
      {cellInner}
    </div>
  );
}

/**
 * Right-aligned preview row for images attached to a user turn.
 *
 * Visual follows agent-chat-ui: a single wrapping row of fixed-size square
 * thumbnails that stay modest next to the text pill regardless of how many
 * images are attached.
 *
 * The URL is expected to be a self-contained ``data:`` URL (the Composer
 * hands the normalized base64 payload to the optimistic bubble so that the
 * preview survives React StrictMode double-mount — blob URLs would be
 * revoked by the Composer's cleanup before remount). Historical replays
 * have no URL (the backend strips data URLs before persisting), so we
 * render a labelled placeholder tile instead of a broken ``<img>``.
 */
function UserImages({
  images,
  align = "right",
}: {
  images: UIImage[];
  align?: "left" | "right";
}) {
  const { t } = useTranslation();
  // Only real-URL images can open in the lightbox; historical-replay
  // placeholders (no URL) have nothing to zoom into.
  const viewable = images
    .map((img, i) => ({ img, i }))
    .filter(({ img }) => typeof img.url === "string" && img.url.length > 0);
  const viewableImages = viewable.map(({ img }) => img);
  const originalToViewable = new Map<number, number>(
    viewable.map(({ i }, v) => [i, v]),
  );

  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);

  return (
    <>
      <div
        className={cn(
          "flex flex-wrap items-end gap-2",
          align === "right" ? "ml-auto justify-end" : "mr-auto justify-start",
        )}
      >
        {images.map((img, i) => (
          <UserImageCell
            key={`${img.url ?? "placeholder"}-${i}`}
            image={img}
            placeholderLabel={t("message.imageAttachment")}
            openLabel={t("lightbox.open")}
            onOpen={
              originalToViewable.has(i)
                ? () => setLightboxIndex(originalToViewable.get(i)!)
                : undefined
            }
          />
        ))}
      </div>
      <ImageLightbox
        images={viewableImages}
        index={lightboxIndex}
        onIndexChange={setLightboxIndex}
        onOpenChange={(open) => {
          if (!open) setLightboxIndex(null);
        }}
      />
    </>
  );
}

function UserImageCell({
  image,
  placeholderLabel,
  openLabel,
  onOpen,
}: {
  image: UIImage;
  placeholderLabel: string;
  openLabel: string;
  onOpen?: () => void;
}) {
  const hasUrl = typeof image.url === "string" && image.url.length > 0;
  const tileClasses = cn(
    "relative h-24 w-24 overflow-hidden rounded-[14px] border border-border/60 bg-muted/40",
    "shadow-[0_6px_18px_-14px_rgba(0,0,0,0.45)]",
  );

  if (hasUrl && onOpen) {
    return (
      <button
        type="button"
        onClick={onOpen}
        aria-label={image.name ? `${openLabel}: ${image.name}` : openLabel}
        title={image.name ?? undefined}
        className={cn(
          tileClasses,
          "cursor-zoom-in transition-transform duration-150 motion-reduce:transition-none",
          "hover:scale-[1.02] hover:ring-2 hover:ring-primary/30",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
        )}
      >
        <img
          src={image.url}
          alt={image.name ?? ""}
          loading="lazy"
          decoding="async"
          draggable={false}
          className="h-full w-full object-cover"
        />
      </button>
    );
  }

  return (
    <div className={tileClasses} title={image.name ?? undefined}>
      <div
        className="flex h-full w-full flex-col items-center justify-center gap-1 px-2 text-[11px] text-muted-foreground"
        aria-label={placeholderLabel}
      >
        <ImageIcon className="h-4 w-4 flex-none" aria-hidden />
        <span className="line-clamp-2 text-center leading-tight">
          {image.name ?? placeholderLabel}
        </span>
      </div>
    </div>
  );
}

/** Blinking cursor appended at the end of streaming text. */
function StreamCursor() {
  const { t } = useTranslation();
  return (
    <span
      aria-label={t("message.streaming")}
      className={cn(
        "ml-0.5 inline-block h-[1em] w-[3px] translate-y-[2px] align-middle",
        "rounded-sm bg-foreground/70 animate-pulse",
      )}
    />
  );
}

/** Pre-token-arrival placeholder: three bouncing dots. */
function TypingDots() {
  const { t } = useTranslation();
  return (
    <span
      aria-label={t("message.assistantTyping")}
      className="inline-flex items-center gap-2 px-1 text-xs text-muted-foreground"
    >
      <span className="flex gap-1">
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-primary" />
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-primary" />
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-primary" />
      </span>
      <span>{t("message.assistantTyping", { defaultValue: "智能体正在分析端口指纹…" })}</span>
    </span>
  );
}

interface TraceGroupProps {
  message: UIMessage;
  animClass: string;
}

/**
 * Collapsible group of tool-call / progress breadcrumbs. Collapsed by
 * default so a long trace never dominates the thread on reopen; a single
 * click expands it for detail.
 */
function TraceGroup({ message, animClass }: TraceGroupProps) {
  const { t } = useTranslation();
  const lines = message.traces ?? [message.content];
  const count = lines.length;
  const [open, setOpen] = useState(false);
  return (
    <div className={cn("w-full", animClass)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "group flex w-full items-center gap-2 rounded-md px-2 py-1.5",
          "text-xs text-muted-foreground transition-colors hover:bg-muted/45",
        )}
        aria-expanded={open}
      >
        <BrainCircuit className="h-3.5 w-3.5 text-primary" aria-hidden />
        <span className="font-medium">
          {count === 1
            ? t("message.toolSingle")
            : t("message.toolMany", { count })}
        </span>
        <ChevronRight
          aria-hidden
          className={cn(
            "ml-auto h-3.5 w-3.5 transition-transform duration-200",
            open && "rotate-90",
          )}
        />
      </button>
      {open && (
        <ul
          className={cn(
            "mt-1 space-y-0.5 border-l border-muted-foreground/20 pl-3",
            "animate-in fade-in-0 slide-in-from-top-1 duration-200",
          )}
        >
          {lines.map((line, i) => (
            <li
              key={`trace-${i}-${line.slice(0, 20)}`}
              className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-muted-foreground/90"
            >
              {line}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
