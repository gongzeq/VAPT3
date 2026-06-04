import { useTranslation } from "react-i18next";

import { AgentStatusPanel } from "@/components/AgentStatusPanel";
import { AssetsPanel } from "@/components/AssetsPanel";
import { BlackboardPanel } from "@/components/BlackboardPanel";
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
 * Default tab is ``Agents`` (智能体). Tab order: ``Blackboard | Assets |
 * Agents``.
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
      defaultValue="agents"
      className={cn(
        "flex h-full min-h-0 w-full flex-col gap-3 p-5",
        className,
      )}
    >
      <TabsList>
        <TabsTrigger value="blackboard">
          {t("home.rightRail.tabs.blackboard", { defaultValue: "黑板" })}
        </TabsTrigger>
        <TabsTrigger value="assets">
          {t("home.rightRail.tabs.assets", { defaultValue: "资产" })}
        </TabsTrigger>
        <TabsTrigger value="agents">
          {t("home.rightRail.tabs.agents", { defaultValue: "智能体" })}
        </TabsTrigger>
      </TabsList>

      <TabsContent value="blackboard" forceMount className="flex flex-col">
        <BlackboardPanel
          chatId={chatId}
          onToggleRightRail={onToggleRightRail}
        />
      </TabsContent>

      <TabsContent value="assets" forceMount className="flex flex-col">
        <AssetsPanel
          chatId={chatId}
          onToggleRightRail={onToggleRightRail}
        />
      </TabsContent>

      <TabsContent value="agents" forceMount className="flex flex-col">
        <AgentStatusPanel chatId={chatId} />
      </TabsContent>
    </Tabs>
  );
}

export default RightRail;
