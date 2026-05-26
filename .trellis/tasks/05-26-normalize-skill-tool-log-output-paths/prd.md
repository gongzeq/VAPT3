# Normalize skill tool log output paths

## Goal

Fix scanner skill raw-log handling so tools such as `qscan-port-scan` and `httpx-probe` return readable log paths and all scanner logs are normalized to one scan-scoped raw-log directory.

## What I already know

- `qscan-port-scan` currently reports success but the user cannot read `qscan-port-scan.log` with `read_file`.
- `httpx-probe` currently reports success but the user cannot read `httpx-probe.jsonl` with `read_file`.
- Specs require scanner raw logs to live under `~/.secbot/scans/<scan_id>/raw/<skill>.log` and `SkillResult.raw_log_path` to be an absolute path.
- External scanner skills must call the shared sandbox rather than raw subprocess APIs.

## Assumptions

- The fix should preserve existing summaries and schemas unless a schema currently encodes the wrong path style.
- A scan's raw log directory is the single canonical destination for generated logs; per-tool extra output files should be either written there or returned as absolute paths when they remain distinct artifacts.
- Existing unrelated worktree changes are out of scope and must not be reverted.

## Requirements

- Normalize raw log paths for `qscan-port-scan`, `httpx-probe`, and any other scanner skills using ad hoc filenames.
- Return absolute paths that `read_file` can open directly.
- Keep raw subprocess output out of `summary_json` except for bounded previews already supported by existing code.
- Add or update focused tests covering the path contract.

## Acceptance Criteria

- [ ] `qscan-port-scan` returns a `raw_log_path` under the current scan raw-log directory.
- [ ] `httpx-probe` returns a `raw_log_path` under the current scan raw-log directory.
- [ ] Other scanner skills follow the same helper/path convention where applicable.
- [ ] Relevant tests and lint pass.

## Out of Scope

- Changing scanner semantics, target validation rules, or network behavior.
- Reworking the `read_file` tool beyond what is necessary to make returned log paths readable.
- Cleaning unrelated dirty worktree files.

## Technical Notes

- Relevant specs:
  - `.trellis/spec/backend/skill-contract.md`
  - `.trellis/spec/backend/tool-invocation-safety.md`
  - `.trellis/spec/backend/context-trimming.md`
  - `.trellis/spec/guides/code-reuse-thinking-guide.md`
