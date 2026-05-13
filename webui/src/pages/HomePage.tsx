import { useNavigate } from "react-router-dom";
import { Navbar } from "@/components/Navbar";
import { RightRail } from "@/components/RightRail";
import { Shell } from "@/components/Shell";

export interface HomePageProps {
  onModelNameChange: (modelName: string | null) => void;
  onLogout: () => void;
}

/**
 * /  — Chat HomePage (template §7.2).
 *
 * Mounts the existing Shell with the new tabbed `RightRail` (F7) so that on
 * xl: screens the Blackboard panel (default) + PromptSuggestions tab appears
 * in a collapsible 320px rail on the right side. On smaller screens the rail
 * is hidden and the UX degrades gracefully to the full-width chat surface.
 *
 * The Blackboard tab is scoped per-chat: HomePage forwards `session` from
 * Shell down to RightRail so the panel can hydrate via
 * `GET /api/blackboard?chat_id=...` and subscribe to the same chat's
 * `agent_event.blackboard_entry` WS frames (PRD F8).
 */
export function HomePage({ onModelNameChange, onLogout }: HomePageProps) {
  const navigate = useNavigate();
  return (
    <div className="flex h-screen w-full flex-col overflow-hidden">
      <Navbar />
      <div className="flex-1 overflow-hidden">
        <Shell
          onModelNameChange={onModelNameChange}
          onLogout={onLogout}
          onOpenSettingsExternal={() => navigate("/settings")}
          rightRail={({ onToggleSidebar, onToggleRightRail, session }) => (
            <RightRail
              session={session}
              onToggleSidebar={onToggleSidebar}
              onToggleRightRail={onToggleRightRail}
            />
          )}
        />
      </div>
    </div>
  );
}

export default HomePage;
