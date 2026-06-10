import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { THEME_COLOR_STORAGE_KEY, THEME_MODE_STORAGE_KEY, useTheme } from "@/hooks/useTheme";

describe("useTheme", () => {
  beforeEach(() => {
    localStorage.removeItem(THEME_MODE_STORAGE_KEY);
    localStorage.removeItem(THEME_COLOR_STORAGE_KEY);
    document.documentElement.className = "";
    document.documentElement.removeAttribute("data-theme");
  });

  it("defaults to the dark secbot theme and persists it", async () => {
    const { result } = renderHook(() => useTheme());

    expect(result.current.theme).toBe("dark");
    expect(result.current.colorTheme).toBe("secbot");

    await waitFor(() => {
      expect(document.documentElement).toHaveClass("dark");
      expect(document.documentElement.dataset.theme).toBe("secbot");
      expect(localStorage.getItem(THEME_MODE_STORAGE_KEY)).toBe("dark");
      expect(localStorage.getItem(THEME_COLOR_STORAGE_KEY)).toBe("secbot");
    });
  });

  it("applies visual mode and color theme changes to the root element", async () => {
    const { result } = renderHook(() => useTheme());

    act(() => {
      result.current.setTheme("light");
      result.current.setColorTheme("emerald");
    });

    await waitFor(() => {
      expect(document.documentElement).not.toHaveClass("dark");
      expect(document.documentElement.dataset.theme).toBe("emerald");
      expect(localStorage.getItem(THEME_MODE_STORAGE_KEY)).toBe("light");
      expect(localStorage.getItem(THEME_COLOR_STORAGE_KEY)).toBe("emerald");
    });
  });

  it("ignores invalid stored theme values", async () => {
    localStorage.setItem(THEME_MODE_STORAGE_KEY, "sepia");
    localStorage.setItem(THEME_COLOR_STORAGE_KEY, "neon");

    const { result } = renderHook(() => useTheme());

    expect(result.current.theme).toBe("dark");
    expect(result.current.colorTheme).toBe("secbot");

    await waitFor(() => {
      expect(document.documentElement).toHaveClass("dark");
      expect(document.documentElement.dataset.theme).toBe("secbot");
    });
  });
});
