import { useTranslation } from "react-i18next";

import { ActivityEventStream } from "@/components/ActivityEventStream";
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
 * agent notes immediately visible). Tab order: ``Blackboard | Trace |
 * Prompts`` — Trace (PRD ``05-12-multi-agent-obs-trace``) replays
 * thought / tool_call / tool_result events for the active chat; Prompts
 * stays as the fallback surface until a future iteration retires it.
 */
export function RightRail({
  session,
  className,
  onToggleRightRail,
}: RightRailProps) {
  const { t } = useTranslation();
  const chatId = session?.chatId ?? null;
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
        <TabsTrigger value="trace">
          {t("home.rightRail.tabs.trace", { defaultValue: "追踪" })}
        </TabsTrigger>
        <TabsTrigger value="prompts">
          {t("home.rightRail.tabs.prompts", { defaultValue: "工作台" })}
        </TabsTrigger>
      </TabsList>

      <TabsContent value="blackboard" className="flex flex-col">
        <BlackboardPanel
          chatId={chatId}
          onToggleRightRail={onToggleRightRail}
        />
      </TabsContent>

      <TabsContent value="trace" className="flex flex-col">
        {chatId ? (
          <ActivityEventStream chatId={chatId} height="100%" />
        ) : (
          <div className="flex items-center justify-center py-10 text-xs text-muted-foreground">
            {t("home.rightRail.trace.empty", {
              defaultValue: "选择一个会话后查看其时间线",
            })}
          </div>
        )}
      </TabsContent>

      <TabsContent value="prompts" className="flex flex-col">
        <PromptSuggestions onToggleRightRail={onToggleRightRail} />
      </TabsContent>
    </Tabs>
  );
}

export default RightRail;
