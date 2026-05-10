import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import {
  Activity,
  BookOpen,
  CircleHelp,
  History,
  ImageIcon,
  Loader2,
  Paperclip,
  RotateCw,
  Send,
  Sparkles,
  Square,
  SquarePen,
  Undo2,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  COMPOSER_PREFILL_EVENT,
  type ComposerPrefillDetail,
} from "@/components/PromptSuggestions";
import {
  useAttachedImages,
  type AttachedImage,
  type AttachmentError,
  MAX_IMAGES_PER_MESSAGE,
} from "@/hooks/useAttachedImages";
import { useClipboardAndDrop } from "@/hooks/useClipboardAndDrop";
import type { SendImage } from "@/hooks/useNanobotStream";
import type { SlashCommand } from "@/lib/types";
import { cn } from "@/lib/utils";

/** ``<input accept>``: aligned with the server's MIME whitelist. SVG is
 * deliberately excluded to avoid an embedded-script XSS surface. */
const ACCEPT_ATTR = "image/png,image/jpeg,image/webp,image/gif";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

interface ThreadComposerProps {
  onSend: (content: string, images?: SendImage[]) => void;
  /** Invoked when the user clicks the stop button while ``isStreaming`` is
   * true. Should ask the backend to cancel the active turn. */
  onStop?: () => void;
  disabled?: boolean;
  placeholder?: string;
  isStreaming?: boolean;
  modelLabel?: string | null;
  variant?: "thread" | "hero";
  slashCommands?: SlashCommand[];
}

const COMMAND_ICONS: Record<string, LucideIcon> = {
  activity: Activity,
  "book-open": BookOpen,
  "circle-help": CircleHelp,
  history: History,
  "rotate-cw": RotateCw,
  sparkles: Sparkles,
  square: Square,
  "square-pen": SquarePen,
  "undo-2": Undo2,
};

function slashCommandI18nKey(command: string): string {
  return command.replace(/^\//, "").replace(/-/g, "_");
}

export function ThreadComposer({
  onSend,
  onStop,
  disabled,
  placeholder,
  isStreaming = false,
  variant = "thread",
  slashCommands = [],
}: ThreadComposerProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const [inlineError, setInlineError] = useState<string | null>(null);
  const [slashMenuDismissed, setSlashMenuDismissed] = useState(false);
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const chipRefs = useRef(new Map<string, HTMLButtonElement>());
  const isHero = variant === "hero";
  const resolvedPlaceholder = isStreaming
    ? t("thread.composer.placeholderStreaming")
    : placeholder ?? t("thread.composer.placeholderThread");

  const { images, enqueue, remove, clear, encoding, full } =
    useAttachedImages();

  const formatRejection = useCallback(
    (reason: AttachmentError): string => {
      const key = `thread.composer.imageRejected.${reason}`;
      return t(key, { max: MAX_IMAGES_PER_MESSAGE });
    },
    [t],
  );

  const addFiles = useCallback(
    (files: File[]) => {
      if (files.length === 0) return;
      const { rejected } = enqueue(files);
      if (rejected.length > 0) {
        setInlineError(formatRejection(rejected[0].reason));
      } else {
        setInlineError(null);
      }
    },
    [enqueue, formatRejection],
  );

  const {
    isDragging,
    onPaste,
    onDragEnter,
    onDragOver,
    onDragLeave,
    onDrop,
  } = useClipboardAndDrop(addFiles);

  useEffect(() => {
    if (disabled) return;
    const el = textareaRef.current;
    if (!el) return;
    const id = requestAnimationFrame(() => el.focus());
    return () => cancelAnimationFrame(id);
  }, [disabled]);

  const readyImages = useMemo(
    () => images.filter((img): img is AttachedImage & { dataUrl: string } =>
      img.status === "ready" && typeof img.dataUrl === "string",
    ),
    [images],
  );
  const hasErrors = images.some((img) => img.status === "error");

  const canSend =
    !disabled
    && !encoding
    && !hasErrors
    && (value.trim().length > 0 || readyImages.length > 0);

  const slashQuery = useMemo(() => {
    if (disabled || slashMenuDismissed || !value.startsWith("/")) return null;
    const commandToken = value.slice(1);
    if (/\s/.test(commandToken)) return null;
    return commandToken.toLowerCase();
  }, [disabled, slashMenuDismissed, value]);

  const filteredSlashCommands = useMemo(() => {
    if (slashQuery === null) return [];
    return slashCommands
      .filter((command) => {
        const haystack = [
          command.command,
          command.title,
          command.description,
          command.argHint ?? "",
          t(`thread.composer.slash.commands.${slashCommandI18nKey(command.command)}.title`, {
            defaultValue: "",
          }),
          t(`thread.composer.slash.commands.${slashCommandI18nKey(command.command)}.description`, {
            defaultValue: "",
          }),
        ].join(" ").toLowerCase();
        return haystack.includes(slashQuery);
      })
      .slice(0, 8);
  }, [slashCommands, slashQuery, t]);

  const showSlashMenu = filteredSlashCommands.length > 0;

  useEffect(() => {
    setSelectedCommandIndex(0);
  }, [slashQuery]);

  useEffect(() => {
    if (selectedCommandIndex >= filteredSlashCommands.length) {
      setSelectedCommandIndex(0);
    }
  }, [filteredSlashCommands.length, selectedCommandIndex]);

  // Listen for cross-component prefill requests (e.g. PromptSuggestions in
  // the HomePage left rail). We intentionally append to existing input —
  // dropping in-progress text would be hostile to the user — except when the
  // textarea is empty, in which case we replace.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<ComposerPrefillDetail>).detail;
      if (!detail || typeof detail.text !== "string" || !detail.text) return;
      setValue((prev) => (prev.trim() === "" ? detail.text : `${prev}\n${detail.text}`));
      setInlineError(null);
      if (detail.focus !== false) {
        requestAnimationFrame(() => {
          const el = textareaRef.current;
          if (!el) return;
          el.style.height = "auto";
          el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
          el.focus();
          // Move caret to end so the user can keep typing after the prefill.
          const len = el.value.length;
          el.setSelectionRange(len, len);
        });
      }
    };
    window.addEventListener(COMPOSER_PREFILL_EVENT, handler as EventListener);
    return () => {
      window.removeEventListener(
        COMPOSER_PREFILL_EVENT,
        handler as EventListener,
      );
    };
  }, []);

  const resizeTextarea = useCallback(() => {
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
      el.focus();
    });
  }, []);

  const chooseSlashCommand = useCallback(
    (command: SlashCommand) => {
      setValue(command.argHint ? `${command.command} ` : command.command);
      setSlashMenuDismissed(true);
      setInlineError(null);
      resizeTextarea();
    },
    [resizeTextarea],
  );

  const submit = useCallback(() => {
    if (!canSend) return;
    const trimmed = value.trim();
    // Share the same normalized ``data:`` URL with both the wire payload and
    // the optimistic bubble preview: data URLs are self-contained (no blob
    // lifetime, safe under React StrictMode double-mount) and keep the
    // bubble in sync with whatever the backend actually sees.
    const payload: SendImage[] | undefined =
      readyImages.length > 0
        ? readyImages.map((img) => ({
            media: {
              data_url: img.dataUrl,
              name: img.file.name,
            },
            preview: { url: img.dataUrl, name: img.file.name },
          }))
        : undefined;
    onSend(trimmed, payload);
    setValue("");
    setInlineError(null);
    // Bubble owns the data URL copy; safe to revoke every staged blob
    // preview here without affecting the rendered message.
    clear();
    setSlashMenuDismissed(false);
    resizeTextarea();
  }, [canSend, clear, onSend, readyImages, resizeTextarea, value]);

  const onKeyDown = (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (showSlashMenu) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedCommandIndex((idx) => (idx + 1) % filteredSlashCommands.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedCommandIndex(
          (idx) => (idx - 1 + filteredSlashCommands.length) % filteredSlashCommands.length,
        );
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        chooseSlashCommand(filteredSlashCommands[selectedCommandIndex]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setSlashMenuDismissed(true);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const onInput: React.FormEventHandler<HTMLTextAreaElement> = (e) => {
    const el = e.currentTarget;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  };

  const onFilePick: React.ChangeEventHandler<HTMLInputElement> = (e) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    addFiles(files);
  };

  const removeChip = useCallback(
    (id: string) => {
      const { nextFocusId } = remove(id);
      setInlineError(null);
      requestAnimationFrame(() => {
        const el = nextFocusId ? chipRefs.current.get(nextFocusId) : null;
        if (el) {
          el.focus();
        } else {
          textareaRef.current?.focus();
        }
      });
    },
    [remove],
  );

  const onChipKey = useCallback(
    (id: string) => (e: ReactKeyboardEvent<HTMLButtonElement>) => {
      if (
        e.key === "Delete" ||
        e.key === "Backspace" ||
        e.key === "Enter" ||
        e.key === " "
      ) {
        e.preventDefault();
        removeChip(id);
      }
    },
    [removeChip],
  );

  const attachButtonDisabled = disabled || full;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className={cn("relative w-full", isHero ? "px-0" : "px-01 pb-0 pt-0 sm:px-0")}
    >
      {showSlashMenu ? (
        <SlashCommandPalette
          commands={filteredSlashCommands}
          selectedIndex={selectedCommandIndex}
          isHero={isHero}
          onHover={setSelectedCommandIndex}
          onChoose={chooseSlashCommand}
        />
      ) : null}
      <div
        className={cn(
          "relative mx-auto flex w-full flex-col overflow-hidden rounded-xl border border-border bg-muted/40 p-2 transition focus-within:border-primary/60",
          isHero ? "max-w-[58rem]" : "max-w-[49.5rem]",
          disabled && "opacity-60",
          isDragging && "ring-2 ring-primary/40 motion-reduce:ring-0 motion-reduce:border-primary",
        )}
      >
        {images.length > 0 ? (
          <div
            className="flex flex-wrap gap-2 px-3 pt-3"
            aria-label={t("thread.composer.attachImage")}
          >
            {images.map((img) => (
              <AttachmentChip
                key={img.id}
                image={img}
                labelRemove={t("thread.composer.remove")}
                labelEncoding={t("thread.composer.encoding")}
                normalizedHint={(orig, current) =>
                  t("thread.composer.normalizedSizeHint", {
                    orig: formatBytes(orig),
                    current: formatBytes(current),
                  })
                }
                formatError={formatRejection}
                onRemove={() => removeChip(img.id)}
                onKeyDown={onChipKey(img.id)}
                registerRef={(el) => {
                  if (el) chipRefs.current.set(img.id, el);
                  else chipRefs.current.delete(img.id);
                }}
              />
            ))}
          </div>
        ) : null}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setSlashMenuDismissed(false);
          }}
          onInput={onInput}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          rows={1}
          placeholder={resolvedPlaceholder}
          disabled={disabled}
          aria-label={t("thread.composer.inputAria")}
          className={cn(
            "w-full resize-none bg-transparent",
            isHero
              ? "min-h-[78px] px-5 pb-2 pt-5 text-[16px] leading-6"
              : "min-h-[50px] px-4 pb-1.5 pt-3 text-sm",
            "placeholder:text-muted-foreground/70",
            "focus:outline-none focus-visible:outline-none",
            "disabled:cursor-not-allowed",
          )}
        />
        {inlineError ? (
          <div
            role="alert"
            className={cn(
              "mx-3 mb-1 rounded-md border border-destructive/40 bg-destructive/8 px-2.5 py-1",
              "text-[11.5px] font-medium text-destructive",
            )}
          >
            {inlineError}
          </div>
        ) : null}
        <div className="flex items-center justify-between px-1 pt-1">
          <div className="flex items-center gap-1">
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT_ATTR}
              multiple
              hidden
              onChange={onFilePick}
            />
            <button
              type="button"
              disabled={attachButtonDisabled}
              aria-label={t("thread.composer.attachImage")}
              onClick={() => fileInputRef.current?.click()}
              className="rounded-md p-1.5 text-muted-foreground hover:bg-white/5 hover:text-primary"
            >
              <Paperclip className="h-4 w-4" />
            </button>
            <button
              type="button"
              disabled={attachButtonDisabled}
              onClick={() => fileInputRef.current?.click()}
              className="rounded-md p-1.5 text-muted-foreground hover:bg-white/5 hover:text-primary disabled:opacity-50"
              aria-label={t("thread.composer.image", { defaultValue: "图片" })}
            >
              <ImageIcon className="h-4 w-4" />
            </button>
            <span className="ml-2 hidden select-none text-[10px] text-muted-foreground font-mono sm:inline">
              {t("thread.composer.sendHint")}
            </span>
          </div>
          {isStreaming && onStop ? (
            <button
              type="button"
              onClick={onStop}
              aria-label={t("thread.composer.stop")}
              title={t("thread.composer.stop")}
              className="group/stop relative grid h-7 w-7 place-items-center rounded-full border border-foreground bg-foreground text-background transition-transform hover:bg-foreground/90 hover:scale-[1.04] active:scale-95"
            >
              <span
                aria-hidden
                className="block h-2 w-2 rounded-[3px] bg-background transition-transform group-hover/stop:scale-95"
              />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!canSend}
              aria-label={t("thread.composer.send")}
              className={cn(
                "hover-lift inline-flex items-center gap-1.5 rounded-lg gradient-primary px-3 py-1.5 text-xs font-semibold text-white shadow-md",
                !canSend && "opacity-50",
              )}
            >
              <Send className="h-3.5 w-3.5" />
              {t("thread.composer.sendBtn", { defaultValue: "发送" })}
            </button>
          )}
        </div>
      </div>
    </form>
  );
}

interface SlashCommandPaletteProps {
  commands: SlashCommand[];
  selectedIndex: number;
  isHero: boolean;
  onHover: (index: number) => void;
  onChoose: (command: SlashCommand) => void;
}

function SlashCommandPalette({
  commands,
  selectedIndex,
  isHero,
  onHover,
  onChoose,
}: SlashCommandPaletteProps) {
  const { t } = useTranslation();
  return (
    <div
      role="listbox"
      aria-label={t("thread.composer.slash.ariaLabel")}
      className={cn(
        "absolute bottom-full left-1/2 z-30 mb-2 max-h-[22rem] w-[calc(100%-0.5rem)] -translate-x-1/2 overflow-hidden rounded-[18px] border",
        "border-border/65 bg-popover/98 p-1.5 text-popover-foreground shadow-[0_18px_55px_rgba(15,23,42,0.18)] backdrop-blur",
        "dark:border-white/10 dark:shadow-[0_22px_55px_rgba(0,0,0,0.45)]",
        isHero ? "max-w-[58rem]" : "max-w-[49.5rem]",
      )}
    >
      <div className="px-2 pb-1 pt-1 text-[11px] font-medium tracking-[0.08em] text-muted-foreground/70">
        {t("thread.composer.slash.label")}
      </div>
      <div className="max-h-[18rem] overflow-y-auto pr-0.5">
        {commands.map((command, index) => {
          const Icon = COMMAND_ICONS[command.icon] ?? CircleHelp;
          const selected = index === selectedIndex;
          const commandKey = slashCommandI18nKey(command.command);
          const title = t(`thread.composer.slash.commands.${commandKey}.title`, {
            defaultValue: command.title,
          });
          const description = t(`thread.composer.slash.commands.${commandKey}.description`, {
            defaultValue: command.description,
          });
          return (
            <button
              key={command.command}
              type="button"
              role="option"
              aria-selected={selected}
              onMouseEnter={() => onHover(index)}
              onMouseDown={(e) => {
                e.preventDefault();
                onChoose(command);
              }}
              className={cn(
                "flex w-full items-center gap-3 rounded-[13px] px-3 py-2.5 text-left transition-colors",
                selected
                  ? "bg-primary/10 text-foreground"
                  : "text-foreground/86 hover:bg-accent/55",
              )}
            >
              <span
                className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] border",
                  selected
                    ? "border-primary/25 bg-primary/12 text-primary"
                    : "border-border/65 bg-muted/45 text-muted-foreground",
                )}
              >
                <Icon className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex min-w-0 items-baseline gap-2">
                  <span className="font-mono text-[13px] font-semibold text-foreground">
                    {command.command}
                  </span>
                  {command.argHint ? (
                    <span className="font-mono text-[12px] text-muted-foreground">
                      {command.argHint}
                    </span>
                  ) : null}
                  <span className="truncate text-[13px] font-medium">
                    {title}
                  </span>
                </span>
                <span className="mt-0.5 block truncate text-[12px] text-muted-foreground">
                  {description}
                </span>
              </span>
            </button>
          );
        })}
      </div>
      <div className="flex items-center gap-2 px-2 pt-1.5 text-[10.5px] text-muted-foreground/70">
        <span>{t("thread.composer.slash.navigateHint")}</span>
        <span>{t("thread.composer.slash.selectHint")}</span>
        <span>{t("thread.composer.slash.closeHint")}</span>
      </div>
    </div>
  );
}

interface AttachmentChipProps {
  image: AttachedImage;
  labelRemove: string;
  labelEncoding: string;
  normalizedHint: (origBytes: number, currentBytes: number) => string;
  formatError: (reason: AttachmentError) => string;
  onRemove: () => void;
  onKeyDown: (e: ReactKeyboardEvent<HTMLButtonElement>) => void;
  registerRef: (el: HTMLButtonElement | null) => void;
}

function AttachmentChip({
  image,
  labelRemove,
  labelEncoding,
  normalizedHint,
  formatError,
  onRemove,
  onKeyDown,
  registerRef,
}: AttachmentChipProps) {
  const sizeLabel =
    image.status === "ready" && image.normalized && image.encodedBytes
      ? normalizedHint(image.file.size, image.encodedBytes)
      : formatBytes(image.file.size);
  const tone =
    image.status === "error"
      ? "border-destructive/40 bg-destructive/5 text-destructive"
      : "border-border/70 bg-muted/60";

  return (
    <div
      className={cn(
        "group relative flex items-center gap-2 rounded-[12px] border px-2 py-1.5",
        "transition-colors motion-reduce:transition-none",
        tone,
      )}
      data-testid="composer-chip"
    >
      <div className="relative h-10 w-10 overflow-hidden rounded-md bg-background">
        {image.previewUrl ? (
          <img
            src={image.previewUrl}
            alt=""
            aria-hidden
            loading="eager"
            draggable={false}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <ImageIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
          </div>
        )}
        {image.status === "encoding" ? (
          <div
            className="absolute inset-0 flex items-center justify-center bg-background/60"
            aria-label={labelEncoding}
          >
            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />
          </div>
        ) : null}
      </div>
      <div className="flex min-w-0 flex-col text-[11.5px] leading-4">
        <span className="truncate max-w-[14rem] font-medium" title={image.file.name}>
          {image.file.name}
        </span>
        <span className="truncate text-muted-foreground">
          {image.status === "error" && image.error
            ? formatError(image.error)
            : sizeLabel}
        </span>
      </div>
      <button
        type="button"
        ref={registerRef}
        onClick={onRemove}
        onKeyDown={onKeyDown}
        aria-label={labelRemove}
        className={cn(
          "ml-1 grid h-5 w-5 flex-none place-items-center rounded-full",
          "text-muted-foreground/80 hover:bg-foreground/8 hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground/30",
        )}
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
