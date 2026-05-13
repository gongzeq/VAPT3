import { useCallback, useEffect, useRef, useState } from "react";
import { MessageSquareText, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface AskUserPromptProps {
  question: string;
  buttons: string[][];
  variant?: "question" | "approval";
  /** Pre-formatted detail block shown above buttons (approval variant).
   * Typically displays tool name + args summary from the high_risk_confirm
   * payload for user review before approve/deny. */
  detail?: string;
  onAnswer: (answer: string) => void;
}

/** Cooldown (ms) before the Approve button becomes clickable — prevents
 * accidental confirmation of destructive actions (spec §F4 / PRD B.8). */
const APPROVE_DELAY_MS = 300;

export function AskUserPrompt({
  question,
  buttons,
  variant = "question",
  detail,
  onAnswer,
}: AskUserPromptProps) {
  const [customOpen, setCustomOpen] = useState(false);
  const [custom, setCustom] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const options = buttons.flat().filter(Boolean);
  const isApproval = variant === "approval";
  const Icon = isApproval ? ShieldAlert : MessageSquareText;

  // 300ms arm delay for the "Approve" button so users don't reflexively click.
  const [armed, setArmed] = useState(!isApproval);
  useEffect(() => {
    if (!isApproval) { setArmed(true); return; }
    setArmed(false);
    const timer = setTimeout(() => setArmed(true), APPROVE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [isApproval]);

  useEffect(() => {
    if (customOpen) {
      inputRef.current?.focus();
    }
  }, [customOpen]);

  const submitCustom = useCallback(() => {
    const answer = custom.trim();
    if (!answer) return;
    onAnswer(answer);
    setCustom("");
    setCustomOpen(false);
  }, [custom, onAnswer]);

  if (options.length === 0) return null;

  return (
    <div
      className={cn(
        "mx-auto mb-2 w-full max-w-[49.5rem] rounded-[16px] border border-primary/30",
        "bg-card/95 p-3 shadow-sm backdrop-blur",
        isApproval && "border-destructive/40 bg-destructive/5",
      )}
      role="group"
      aria-label={isApproval ? "Approval request" : "Question"}
    >
      <div className="mb-2 flex items-start gap-2">
        <div className={cn(
          "mt-0.5 rounded-full p-1.5",
          isApproval ? "bg-destructive/10 text-destructive" : "bg-primary/10 text-primary",
        )}>
          <Icon className="h-3.5 w-3.5" aria-hidden />
        </div>
        <p className="min-w-0 flex-1 text-sm font-medium leading-5 text-foreground">
          {question}
        </p>
      </div>

      {isApproval && detail ? (
        <pre className="mb-2 max-h-40 overflow-auto rounded-md border border-destructive/20 bg-muted/50 px-3 py-2 font-mono text-[11px] leading-relaxed text-muted-foreground">
          {detail}
        </pre>
      ) : null}

      <div className="grid gap-1.5 sm:grid-cols-2">
        {options.map((option) => {
          const isApproveBtn = isApproval && option.toLowerCase().includes("approve");
          const isDenyBtn = isApproval && option.toLowerCase().includes("deny");
          return (
            <Button
              key={option}
              type="button"
              variant={isDenyBtn ? "destructive" : "outline"}
              size="sm"
              disabled={isApproveBtn && !armed}
              onClick={() => onAnswer(option)}
              className={cn(
                "justify-start rounded-[10px] px-3 text-left",
                isApproveBtn && "border-green-500/50 text-green-600 hover:bg-green-500/10",
              )}
            >
              <span className="truncate">{option}</span>
            </Button>
          );
        })}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setCustomOpen((open) => !open)}
          className="justify-start rounded-[10px] px-3 text-muted-foreground"
        >
          Other...
        </Button>
      </div>

      {customOpen ? (
        <div className="mt-2 flex gap-2">
          <textarea
            ref={inputRef}
            value={custom}
            onChange={(event) => setCustom(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                submitCustom();
              }
            }}
            rows={1}
            placeholder="Type your own answer..."
            className={cn(
              "min-h-9 flex-1 resize-none rounded-[10px] border border-border/70 bg-background",
              "px-3 py-2 text-sm leading-5 outline-none placeholder:text-muted-foreground",
              "focus-visible:ring-1 focus-visible:ring-primary/40",
            )}
          />
          <Button type="button" size="sm" onClick={submitCustom} disabled={!custom.trim()}>
            Send
          </Button>
        </div>
      ) : null}
    </div>
  );
}
