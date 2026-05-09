import { useNavigate } from "react-router-dom";
import { Shell } from "@/components/Shell";

export interface HomePageProps {
  onModelNameChange: (modelName: string | null) => void;
  onLogout: () => void;
}

/**
 * /  — Chat HomePage placeholder. Mounts the existing Shell (sidebar +
 * ThreadShell) verbatim so PR3 keeps the chat surface byte-for-byte
 * compatible. PR4 (R4.2) will introduce the prompt-suggestions + quick-stats
 * left rail described in the template; until then the chat experience is
 * unchanged.
 */
export function HomePage({ onModelNameChange, onLogout }: HomePageProps) {
  const navigate = useNavigate();
  return (
    <Shell
      onModelNameChange={onModelNameChange}
      onLogout={onLogout}
      onOpenSettingsExternal={() => navigate("/settings")}
    />
  );
}

export default HomePage;
