import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { ImageIcon, Paperclip, Send, Sparkles } from "lucide-react";
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
import {
  SlashCommandPalette,
  slashCommandI18nKey,
} from "@/components/thread/SlashCommandPalette";
import { AttachmentChip, formatBytes } from "@/components/thread/AttachmentChip";

/** ``<input accept>``: aligned with the server's MIME whitelist. SVG is
 * deliberately excluded to avoid an embedded-script XSS surface. */
const ACCEPT_ATTR = "image/png,image/jpeg,image/webp,image/gif";

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

/** @description Composer textarea with slash-command palette, image attachments, and send/stop controls. */
export function ThreadComposer({
  onSend,
  onStop,
  disabled,
  placeholder,
  isStreaming = false,
  variant = "thread",
  modelLabel,
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

  const { images, enqueue, remove, clear, encoding, full } = useAttachedImages();

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

  const { isDragging, onPaste, onDragEnter, onDragOver, onDragLeave, onDrop } =
    useClipboardAndDrop(addFiles);

  useEffect(() => {
    if (disabled) return;
    const el = textareaRef.current;
    if (!el) return;
    const id = requestAnimationFrame(() => el.focus());
    return () => cancelAnimationFrame(id);
  }, [disabled]);

  const readyImages = useMemo(
    () =>
      images.filter(
        (img): img is AttachedImage & { dataUrl: string } =>
          img.status === "ready" && typeof img.dataUrl === "string",
      ),
    [images],
  );
  const hasErrors = images.some((img) => img.status === "error");

  const canSend =
    !disabled &&
    !encoding &&
    !hasErrors &&
    (value.trim().length > 0 || readyImages.length > 0);

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
        const haystack =
          [
            command.command,
            command.title,
            command.description,
            command.argHint ?? "",
            t(
              `thread.composer.slash.commands.${slashCommandI18nKey(command.command)}.title`,
              {
                defaultValue: "",
              },
            ),
            t(
              `thread.composer.slash.commands.${slashCommandI18nKey(command.command)}.description`,
              {
                defaultValue: "",
              },
            ),
          ]
            .join(" ")
            .toLowerCase();
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
      setValue((prev) =>
        prev.trim() === "" ? detail.text : `${prev}\n${detail.text}`,
      );
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
      window.removeEventListener(COMPOSER_PREFILL_EVENT, handler as EventListener);
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
          "relative mx-auto flex w-full flex-col overflow-hidden rounded-xl border border-border/60 bg-muted/30 p-2 transition-all duration-200",
          isHero
            ? "max-w-[58rem] rounded-2xl bg-gradient-to-b from-muted/40 to-muted/20 shadow-[0_12px_44px_-16px_hsl(var(--primary)/0.32)]"
            : "max-w-[49.5rem]",
          disabled && "opacity-60",
          isDragging && "ring-2 ring-primary/40 motion-reduce:ring-0 motion-reduce:border-primary",
          !disabled && "focus-within:border-primary/40 focus-within:shadow-[0_0_16px_hsl(var(--primary)/0.08)]",
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
        {modelLabel ? (
          <div className="flex items-center gap-1.5 px-3 pt-2 text-xs">
            <Sparkles className="h-3 w-3 flex-none text-gradient" aria-hidden />
            <code className="font-mono text-gradient font-semibold">{modelLabel}</code>
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
              className="rounded-md p-1.5 text-muted-foreground/80 transition-colors duration-150 hover:bg-primary/8 hover:text-primary"
            >
              <Paperclip className="h-4 w-4" />
            </button>
            <button
              type="button"
              disabled={attachButtonDisabled}
              onClick={() => fileInputRef.current?.click()}
              className="rounded-md p-1.5 text-muted-foreground/80 transition-colors duration-150 hover:bg-primary/8 hover:text-primary disabled:opacity-50"
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
                "inline-flex items-center gap-1.5 rounded-lg gradient-primary px-3.5 py-1.5 text-xs font-semibold text-white shadow-[0_2px_10px_hsl(var(--primary)/0.3)] transition-all duration-200 hover:shadow-[0_4px_16px_hsl(var(--primary)/0.45)] active:scale-[0.97]",
                !canSend && "opacity-50 shadow-none",
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
