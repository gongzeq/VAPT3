import { useTranslation } from "react-i18next";

import { BlackboardPanel } from "@/components/BlackboardPanel";
import { PromptSuggestions } from "@/components/PromptSuggestions";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { ChatSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface RightRailProps {
  /** Active chat session — needed by the Blackboard tab to scope its
   * HTTP replay + WS subscription. ``null`` falls back to an empty state. */
  session: ChatSummary | null;
  className?: string;
  onToggleSidebar?: () => void;
  onToggleRightRail?: () => void;
}

/**
 * F7 — Right-Rail tabbed container.
 *
 * Default tab is ``Blackboard`` (per PRD requirement: refresh page → live
 * agent notes immediately visible). The second tab keeps the existing
 * ``PromptSuggestions`` surface untouched (KPI + prompt chips); the Trace
 * tab placeholder is intentionally deferred to Task 3 (out of scope here).
 */
export function RightRail({
  session,
  className,
  onToggleRightRail,
}: RightRailProps) {
  const { t } = useTranslation();
  return (
    <Tabs
      defaultValue="blackboard"
      className={cn(
        "flex h-full min-h-0 w-full flex-col gap-3 p-5",
        className,
      )}
    >
      <TabsList>
        <TabsTrigger value="blackboard">
          {t("home.rightRail.tabs.blackboard", { defaultValue: "黑板" })}
        </TabsTrigger>
        <TabsTrigger value="prompts">
          {t("home.rightRail.tabs.prompts", { defaultValue: "工作台" })}
        </TabsTrigger>
      </TabsList>

      <TabsContent value="blackboard" className="flex flex-col">
        <BlackboardPanel
          chatId={session?.chatId ?? null}
          onToggleRightRail={onToggleRightRail}
        />
      </TabsContent>

      <TabsContent value="prompts" className="flex flex-col">
        <PromptSuggestions onToggleRightRail={onToggleRightRail} />
      </TabsContent>
    </Tabs>
  );
}

export default RightRail;
