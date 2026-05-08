import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";

import i18n from "@/i18n";

// happy-dom doesn't ship with ``crypto.randomUUID``; shim a tiny v4-ish helper.
if (!("randomUUID" in globalThis.crypto)) {
  Object.defineProperty(globalThis.crypto, "randomUUID", {
    value: () =>
      "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === "x" ? r : (r & 0x3) | 0x8;
        return v.toString(16);
      }),
    configurable: true,
  });
}

// happy-dom 16.x exposes `localStorage` as a getter on `window` but does not
// expose it on the globalThis surface that vitest's setup file targets, so
// `localStorage.setItem` raises `TypeError: localStorage.setItem is not a
// function`. Patch a minimal in-memory Storage onto globalThis when missing
// so the shared `beforeEach` (which writes the active locale) works in every
// test file. PR2 (05-07-ocean-tech-frontend) — see task notes.
if (
  typeof globalThis.localStorage !== "object" ||
  typeof globalThis.localStorage?.setItem !== "function"
) {
  const store = new Map<string, string>();
  const shim: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key: string) => (store.has(key) ? (store.get(key) as string) : null),
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    removeItem: (key: string) => {
      store.delete(key);
    },
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
  };
  Object.defineProperty(globalThis, "localStorage", {
    value: shim,
    configurable: true,
    writable: true,
  });
}

// happy-dom 16.x does not implement `window.alert` (returns undefined on the
// global `Window`). Components that surface error feedback via `alert()`
// (e.g. `SettingsView`'s load-error path) would otherwise raise
// `TypeError: window.alert is not a function` when their error branch runs
// under vitest. Install a no-op shim so the call is a quiet no-op in tests;
// assertions should target the in-page error banner, not the alert.
// PR2 (05-07-ocean-tech-frontend) — see task check notes.
if (typeof globalThis.alert !== "function") {
  Object.defineProperty(globalThis, "alert", {
    value: (_message?: unknown) => {
      // intentional no-op in tests
    },
    configurable: true,
    writable: true,
  });
}
if (typeof window !== "undefined" && typeof window.alert !== "function") {
  Object.defineProperty(window, "alert", {
    value: (_message?: unknown) => {
      // intentional no-op in tests
    },
    configurable: true,
    writable: true,
  });
}

beforeEach(async () => {
  await i18n.changeLanguage("en");
  document.documentElement.lang = "en";
  document.title = "nanobot";
  localStorage.setItem("nanobot.locale", "en");
});
