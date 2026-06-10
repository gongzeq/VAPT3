import { useCallback, useEffect, useState } from "react";

/** Visual mode applied through the root `.dark` class. */
export type Theme = "light" | "dark";

/** Closed set of root `data-theme` values that drive brand color tokens. */
export type ThemeColor = "secbot" | "indigo" | "emerald" | "crimson";

/** Selectable brand color option shown in settings. */
export interface ThemeColorOption {
  id: ThemeColor;
  label: string;
  swatchClassName: string;
}

/** Theme color options backed by CSS variables in `globals.css`. */
export const THEME_COLOR_OPTIONS: readonly ThemeColorOption[] = [
  {
    id: "secbot",
    label: "海蓝",
    swatchClassName: "theme-swatch-secbot",
  },
  {
    id: "indigo",
    label: "靛蓝",
    swatchClassName: "theme-swatch-indigo",
  },
  {
    id: "emerald",
    label: "翠绿",
    swatchClassName: "theme-swatch-emerald",
  },
  {
    id: "crimson",
    label: "绯红",
    swatchClassName: "theme-swatch-crimson",
  },
] as const;

/** Local-storage key for the persisted light/dark mode. */
export const THEME_MODE_STORAGE_KEY = "secbot-webui.theme";

/** Local-storage key for the persisted brand color theme. */
export const THEME_COLOR_STORAGE_KEY = "secbot-webui.theme-color";

const DEFAULT_THEME: Theme = "dark";
const DEFAULT_THEME_COLOR: ThemeColor = "secbot";

function readStorage(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function persistStorage(key: string, value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // ignore storage errors
  }
}

function isTheme(value: string | null): value is Theme {
  return value === "light" || value === "dark";
}

function isThemeColor(value: string | null): value is ThemeColor {
  return THEME_COLOR_OPTIONS.some((option) => option.id === value);
}

function readStoredTheme(): Theme | null {
  const value = readStorage(THEME_MODE_STORAGE_KEY);
  return isTheme(value) ? value : null;
}

function readStoredThemeColor(): ThemeColor | null {
  const value = readStorage(THEME_COLOR_STORAGE_KEY);
  return isThemeColor(value) ? value : null;
}

function applyTheme(theme: Theme, colorTheme: ThemeColor): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.dataset.theme = colorTheme;
}

/** Theme hook that persists mode and brand color, then applies them to `<html>`. */
export function useTheme(): {
  theme: Theme;
  colorTheme: ThemeColor;
  toggle: () => void;
  setTheme: (theme: Theme) => void;
  setColorTheme: (colorTheme: ThemeColor) => void;
} {
  const [theme, setThemeState] = useState<Theme>(() => {
    return readStoredTheme() ?? DEFAULT_THEME;
  });
  const [colorTheme, setColorThemeState] = useState<ThemeColor>(() => {
    return readStoredThemeColor() ?? DEFAULT_THEME_COLOR;
  });

  useEffect(() => {
    applyTheme(theme, colorTheme);
    persistStorage(THEME_MODE_STORAGE_KEY, theme);
    persistStorage(THEME_COLOR_STORAGE_KEY, colorTheme);
  }, [colorTheme, theme]);

  const setTheme = useCallback((nextTheme: Theme) => {
    setThemeState(nextTheme);
  }, []);
  const setColorTheme = useCallback((nextColorTheme: ThemeColor) => {
    setColorThemeState(nextColorTheme);
  }, []);
  const toggle = useCallback(() => setThemeState((t) => (t === "dark" ? "light" : "dark")), []);
  return { theme, colorTheme, toggle, setTheme, setColorTheme };
}
