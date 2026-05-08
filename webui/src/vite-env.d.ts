/// <reference types="vite/client" />

/**
 * Vite client ambient types (`import.meta.env`, `?url`, `?worker`, etc.).
 * Declared here once so `tsc --noEmit` resolves `import.meta.env.VITE_*`
 * flags from `main.tsx` and anywhere else in `src/`.
 *
 * Project-specific custom env vars should extend `ImportMetaEnv`:
 */
interface ImportMetaEnv {
  /**
   * Ocean-tech HUD feature flag — see `main.tsx` and
   * `.trellis/tasks/05-07-ocean-tech-frontend/prd.md` §Decision 6.
   * Set to `"0"` at build time to collapse brand-deep/brand-light tokens
   * onto --primary (disables ocean identity layer).
   */
  readonly VITE_SECBOT_HUD?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
