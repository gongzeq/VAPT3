import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Navbar } from "@/components/Navbar";
import { RightRail } from "@/components/RightRail";
import { Shell } from "@/components/Shell";
import { useSessionsList } from "@/hooks/useSessionsList";

export interface HomePageProps {
  onModelNameChange: (modelName: string | null) => void;
  onLogout: () => void;
}

/**
 * /  — Chat HomePage (template §7.2).
 *
 * Mounts the existing Shell with the new tabbed `RightRail` (F7) so that on
 * xl: screens the Blackboard panel (default) + PromptSuggestions tab appears
 * in a 320px rail on the right side. On smaller screens the rail
 * is hidden and the UX degrades gracefully to the full-width chat surface.
 *
 * The Blackboard tab is scoped per-chat: HomePage forwards `session` from
 * Shell down to RightRail so the panel can hydrate via
 * `GET /api/blackboard?chat_id=...` and subscribe to the same chat's
 * `agent_event.blackboard_entry` WS frames (PRD F8).
 *
 * Auto-resume: if the backend reports a session with ``status: "running"``,
 * the home page sets the ``?session=`` query param so the Shell component
 * loads that session's conversation in-place — the user stays on the
 * 智能助手 page instead of being redirected to the session detail page.
 */
export function HomePage({ onModelNameChange, onLogout }: HomePageProps) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { sessions } = useSessionsList();

  // If there's a running session and the user hasn't already selected a
  // session via the URL, auto-resume it in the home Shell so the scan
  // progress is visible without leaving the 智能助手 page.
  const runningSession = sessions.find((s) => s.status === "running");
  useEffect(() => {
    if (!runningSession) return;
    const currentKey = searchParams.get("session");
    if (currentKey === runningSession.key) return; // already showing it
    const next = new URLSearchParams(searchParams);
    next.set("session", runningSession.key);
    setSearchParams(next, { replace: true });
  }, [runningSession, searchParams, setSearchParams]);

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
