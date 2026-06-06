/**
 * Slash-command autocomplete palette rendered above the composer textarea.
 *
 * Exports:
 * - `SlashCommandPalette` — the floating listbox component
 * - `COMMAND_ICONS` — icon-name → LucideIcon mapping
 * - `slashCommandI18nKey` — normalises a slash command string to an i18n key
 */

import { useTranslation } from "react-i18next";
import {
  Activity,
  BookOpen,
  CircleHelp,
  History,
  RotateCw,
  Sparkles,
  Square,
  SquarePen,
  Undo2,
  type LucideIcon,
} from "lucide-react";

import type { SlashCommand } from "@/lib/types";
import { cn } from "@/lib/utils";

/** @description Mapping from slash command icon names to Lucide icon components. */
export const COMMAND_ICONS: Record<string, LucideIcon> = {
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

/** @description Normalise a slash command string to its corresponding i18n translation key. */
export function slashCommandI18nKey(command: string): string {
  return command.replace(/^\//, "").replace(/-/g, "_");
}

/** @description Props for the slash-command autocomplete palette. */
export interface SlashCommandPaletteProps {
  commands: SlashCommand[];
  selectedIndex: number;
  isHero: boolean;
  onHover: (index: number) => void;
  onChoose: (command: SlashCommand) => void;
}

/** @description Floating listbox showing matching slash commands as the user types. */
export function SlashCommandPalette({
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
          const description = t(
            `thread.composer.slash.commands.${commandKey}.description`,
            {
              defaultValue: command.description,
            },
          );
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
                  <span className="truncate text-[13px] font-medium">{title}</span>
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
