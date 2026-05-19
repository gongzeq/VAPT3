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
  const [submitted, setSubmitted] = useState(false);
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
    setSubmitted(true);
    onAnswer(answer);
    setCustom("");
    setCustomOpen(false);
  }, [custom, onAnswer]);

  const handleOptionClick = useCallback((option: string) => {
    setSubmitted(true);
    onAnswer(option);
  }, [onAnswer]);

  if (options.length === 0) return null;

  return (
    <div
      className={cn(
        "relative z-10 mx-auto mb-3 w-full max-w-[49.5rem] rounded-[16px] border",
        isApproval
          ? "border-destructive/40 bg-destructive/[0.08] shadow-[0_2px_12px_rgba(239,68,68,0.08)]"
          : "border-primary/30 bg-card shadow-sm",
        "p-3",
        submitted && "opacity-60",
      )}
      role="group"
      aria-label={isApproval ? "Approval request" : "Question"}
    >
      {/* Approval header */}
      <div className="mb-2 flex items-start gap-2">
        <div
          className={cn(
            "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
            isApproval ? "bg-destructive/15 text-destructive" : "bg-primary/10 text-primary",
          )}
        >
          <Icon className="h-4 w-4" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold leading-5 text-foreground">
            {isApproval ? "需要您的确认" : question}
          </p>
          {isApproval && (
            <p className="mt-0.5 text-[12.5px] leading-4 text-muted-foreground">
              {question}
            </p>
          )}
        </div>
      </div>

      {isApproval && detail ? (
        <pre className="mb-2.5 max-h-40 overflow-auto rounded-lg border border-destructive/15 bg-background/60 px-3 py-2 font-mono text-[11px] leading-relaxed text-muted-foreground">
          {detail}
        </pre>
      ) : null}

      <div className="grid gap-2 sm:grid-cols-2">
        {options.map((option) => {
          const isApproveBtn = isApproval && option.toLowerCase().includes("approve");
          const isDenyBtn = isApproval && option.toLowerCase().includes("deny");
          return (
            <Button
              key={option}
              type="button"
              variant={isDenyBtn ? "destructive" : isApproveBtn ? "default" : "outline"}
              size="sm"
              disabled={(isApproveBtn && !armed) || submitted}
              onClick={() => handleOptionClick(option)}
              className={cn(
                "h-9 justify-start rounded-[10px] px-3 text-left font-medium transition-all active:scale-[0.98]",
                isApproveBtn &&
                  "bg-green-600 text-white hover:bg-green-700 shadow-sm hover:shadow",
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
          disabled={submitted}
          onClick={() => setCustomOpen((open) => !open)}
          className="h-9 justify-start rounded-[10px] px-3 text-muted-foreground hover:text-foreground"
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
