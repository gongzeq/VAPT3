import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  Check,
  Globe,
  LogOut,
  Moon,
  Palette,
  Server,
  Sun,
  Trash2,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { SettingsView } from "@/components/settings/SettingsView";
import { Button } from "@/components/ui/button";
import {
  THEME_COLOR_OPTIONS,
  useTheme,
  type ThemeColor,
  type ThemeColorOption,
} from "@/hooks/useTheme";
import { cn } from "@/lib/utils";

/** Props for the route-level settings page. */
export interface SettingsPageProps {
  onModelNameChange: (modelName: string | null) => void;
  onLogout: () => void;
}

type SettingsTab = "preferences" | "platform" | "danger";

interface TabDef {
  id: SettingsTab;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const TABS: TabDef[] = [
  { id: "preferences", label: "用户偏好", icon: Palette },
  { id: "platform", label: "平台管理", icon: Server },
  { id: "danger", label: "危险区", icon: AlertTriangle },
];

/** Props for a selectable theme color button. */
export interface ThemeColorButtonProps {
  option: ThemeColorOption;
  selected: boolean;
  onSelect: (theme: ThemeColor) => void;
}

function ThemeColorButton({ option, selected, onSelect }: ThemeColorButtonProps) {
  const handleClick = () => onSelect(option.id);

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-pressed={selected}
      className={cn(
        "flex h-10 items-center justify-between gap-2 rounded-md border px-3 text-sm transition-all",
        selected
          ? "border-primary bg-primary/10 text-foreground shadow-[0_0_0_1px_hsl(var(--primary)/0.18)]"
          : "border-border/60 bg-background text-muted-foreground hover:border-primary/40 hover:text-foreground",
      )}
    >
      <span className="flex min-w-0 items-center gap-2">
        <span
          className={cn(
            "h-4 w-4 shrink-0 rounded-full ring-1 ring-border/60",
            option.swatchClassName,
          )}
          aria-hidden="true"
        />
        <span className="truncate">{option.label}</span>
      </span>
      {selected ? (
        <Check className="h-3.5 w-3.5 shrink-0 text-primary" />
      ) : (
        <span className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      )}
    </button>
  );
}

/**
 * /settings — Tab layout per template §7.5 / PRD R4.5.
 *
 * Three tabs:
 * 1. 用户偏好: theme toggle + language switcher (+ future notification prefs)
 * 2. 平台管理: existing SettingsView (model/provider/api_base)
 * 3. 危险区: logout + clear all sessions
 */
export function SettingsPage({ onModelNameChange, onLogout }: SettingsPageProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<SettingsTab>("preferences");
  const { theme, colorTheme, setTheme, setColorTheme } = useTheme();

  return (
    <div className="flex h-full w-full flex-col bg-background">
      <Navbar />

      <main className="container flex-1 overflow-y-auto py-6 space-y-6">
        {/* ── Tab Bar ── */}
        <div className="flex gap-1 rounded-lg border border-border/40 bg-card p-1">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-accent text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
                )}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* ── Tab Content ── */}
        {activeTab === "preferences" && (
          <section className="space-y-6">
            {/* Theme */}
            <div className="rounded-xl border border-border/40 bg-card p-6">
              <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-foreground">
                <Palette className="h-4 w-4 text-muted-foreground" />
                {t("settings.theme.title", { defaultValue: "主题外观" })}
              </h3>
              <div className="space-y-5">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-sm text-foreground">
                      {t("settings.theme.mode", { defaultValue: "显示模式" })}
                    </p>
                  </div>
                  <div className="grid w-full grid-cols-2 gap-2 sm:w-[260px]">
                    <Button
                      type="button"
                      variant={theme === "light" ? "default" : "outline"}
                      size="sm"
                      onClick={() => setTheme("light")}
                      aria-pressed={theme === "light"}
                      className="justify-center gap-1.5"
                    >
                      <Sun className="h-3.5 w-3.5" />
                      {t("settings.theme.light", { defaultValue: "浅色" })}
                    </Button>
                    <Button
                      type="button"
                      variant={theme === "dark" ? "default" : "outline"}
                      size="sm"
                      onClick={() => setTheme("dark")}
                      aria-pressed={theme === "dark"}
                      className="justify-center gap-1.5"
                    >
                      <Moon className="h-3.5 w-3.5" />
                      {t("settings.theme.dark", { defaultValue: "深色" })}
                    </Button>
                  </div>
                </div>

                <div className="border-t border-border/40" />

                <div className="flex flex-col gap-3">
                  <p className="text-sm text-foreground">
                    {t("settings.theme.color", { defaultValue: "主题色彩" })}
                  </p>
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                    {THEME_COLOR_OPTIONS.map((option) => (
                      <ThemeColorButton
                        key={option.id}
                        option={option}
                        selected={colorTheme === option.id}
                        onSelect={setColorTheme}
                      />
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Language */}
            <div className="rounded-xl border border-border/40 bg-card p-6">
              <h3 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
                <Globe className="h-4 w-4 text-muted-foreground" />
                {t("settings.language", { defaultValue: "语言与时区" })}
              </h3>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-foreground">
                    {t("settings.interfaceLang", { defaultValue: "界面语言" })}
                  </p>
                </div>
                <LanguageSwitcher />
              </div>
            </div>
          </section>
        )}

        {activeTab === "platform" && (
          <div className="rounded-xl border border-border/40 bg-card overflow-hidden">
            <SettingsView
              onBackToChat={() => navigate("/")}
              onModelNameChange={onModelNameChange}
              onLogout={onLogout}
            />
          </div>
        )}

        {activeTab === "danger" && (
          <section className="space-y-4">
            <div className="rounded-xl border border-destructive/40 bg-card p-6">
              <h3 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-destructive" />
                {t("settings.dangerZone", { defaultValue: "危险操作" })}
              </h3>
              <div className="space-y-4">
                {/* Logout */}
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-foreground">
                      {t("settings.logout", { defaultValue: "退出登录" })}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {t("settings.logoutHint", {
                        defaultValue: "清除本地凭据并返回登录页",
                      })}
                    </p>
                  </div>
                  <Button variant="destructive" size="sm" onClick={onLogout} className="gap-1.5">
                    <LogOut className="h-3.5 w-3.5" />
                    {t("settings.logoutBtn", { defaultValue: "退出" })}
                  </Button>
                </div>

                <div className="border-t border-border/40" />

                {/* Clear sessions */}
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-foreground">
                      {t("settings.clearSessions", {
                        defaultValue: "清空所有会话",
                      })}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {t("settings.clearSessionsHint", {
                        defaultValue: "删除所有对话历史记录，此操作不可逆",
                      })}
                    </p>
                  </div>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => {
                      if (
                        window.confirm(
                          t("settings.clearConfirm", {
                            defaultValue: "确定要清空所有会话吗？此操作不可逆。",
                          }),
                        )
                      ) {
                        // TODO: call delete-all-sessions API when backend lands
                        window.alert(
                          t("settings.clearDone", {
                            defaultValue: "会话已清空（mock — 后端未接入）",
                          }),
                        );
                      }
                    }}
                    className="gap-1.5"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {t("settings.clearBtn", { defaultValue: "清空" })}
                  </Button>
                </div>
              </div>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

export default SettingsPage;
