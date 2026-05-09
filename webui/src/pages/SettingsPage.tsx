import { useNavigate } from "react-router-dom";
import { Navbar } from "@/components/Navbar";
import { SettingsView } from "@/components/settings/SettingsView";
import { useTheme } from "@/hooks/useTheme";

export interface SettingsPageProps {
  onModelNameChange: (modelName: string | null) => void;
  onLogout: () => void;
}

/**
 * /settings — wraps the existing SettingsView under the shared Navbar so the
 * settings UX matches the template chrome. PR7 (R4.5) will rework the inner
 * layout into a Tab structure (用户偏好 / 平台 Admin / 危险区); PR3 only
 * promotes settings from a Shell sub-view to a first-class route.
 */
export function SettingsPage({ onModelNameChange, onLogout }: SettingsPageProps) {
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  return (
    <div className="flex h-full w-full flex-col bg-background">
      <Navbar />
      <div className="flex min-h-0 flex-1 flex-col">
        <SettingsView
          theme={theme}
          onToggleTheme={toggle}
          onBackToChat={() => navigate("/")}
          onModelNameChange={onModelNameChange}
          onLogout={onLogout}
        />
      </div>
    </div>
  );
}

export default SettingsPage;
