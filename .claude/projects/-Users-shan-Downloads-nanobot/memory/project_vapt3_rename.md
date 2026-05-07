---
name: VAPT3 rename target (supersedes secbot)
description: Cybersec-agent-platform task renames nanobot to VAPT3, not secbot as the original PRD said
type: project
---

The cybersec-agent-platform task (`.trellis/tasks/05-07-cybersec-agent-platform`) renames the project as follows:

- **Branding (display, README titles, banners)**: `VAPT3` (uppercase)
- **Python package directory**: `vapt3/` (lowercase)
- **PyPI distribution name**: `vapt3`
- **CLI entrypoint**: `vapt3`
- **User data dir**: `~/.vapt3/`
- **Spec directory**: `.trellis/spec/vapt3/`

**Why:** User decided on 2026-05-07 to fork/rename to VAPT3 (Vulnerability Assessment and Penetration Testing, gen-3). The PRD (`.trellis/tasks/05-07-cybersec-agent-platform/prd.md`) was authored with `secbot` as the rename target — that name is **superseded**. Treat any `secbot` reference in the PRD or in earlier spec drafts as a stale artifact pointing to the same rename slot now filled by `vapt3` / `VAPT3`.

**How to apply:**
- When writing new code or docs in this task, use `vapt3` (package/CLI) and `VAPT3` (branding).
- When reading existing PRD text that says `secbot`, mentally substitute `vapt3` — the design decisions still apply, only the name changed.
- PR1 (the planned full repo rename) renames `nanobot → vapt3`, not `nanobot → secbot`.
