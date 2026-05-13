# Skill-as-Tool

> Source: PRD `05-11-security-tools-as-tools` §Goal / §Requirements.
> Contract: [.trellis/spec/backend/skill-contract.md](../.trellis/spec/backend/skill-contract.md) · [.trellis/spec/backend/tool-invocation-safety.md](../.trellis/spec/backend/tool-invocation-safety.md).

Every skill under `secbot/skills/<name>/` is auto-promoted to a **first-class LLM tool**. The LLM sees the skill's JSON Schema directly (no shell-command stringification), invokes it by tool name, and the runtime executes it through the sandbox.

The shell `exec` tool is **disabled by default** (`ExecToolConfig.enable = False`). LLMs cannot reach security binaries except through skill tools — the sandbox + skill schema enforce argv validation, binary whitelisting, and high-risk gating.

## Why

Before: LLM wrote `bash -l -c "nmap -sn 10.0.0.0/24"`, which exposed `#`-as-comment issues, argv injection, and no argument validation.

After: LLM calls `nmap_host_discovery({"targets": ["10.0.0.0/24"]})`. The skill handler parses the structured input, builds safe argv, runs it under the sandbox, and returns parsed JSON.

## Writing a Skill

A skill is a directory with three files:

```
secbot/skills/my-skill/
├── SKILL.md       # front-matter metadata + human prose
├── handler.py     # async def run(input: dict, ctx: SkillContext) -> dict
└── schema.json    # JSON Schema for the input
```

### `SKILL.md` front-matter

```yaml
---
name: my-skill
description: One-line summary the LLM reads when choosing a tool.
risk_level: low        # low | medium | high | critical
required_binaries:     # optional; used by AgentRegistry.check_availability
  - mybinary
network_egress: required   # required | none
---

Free-form markdown body. Explain what the skill does, example inputs, caveats.
```

`risk_level` is the single knob for gate behaviour:

| Level      | Behaviour                                                                           |
|------------|-------------------------------------------------------------------------------------|
| `low`      | Runs immediately.                                                                   |
| `medium`   | Runs immediately; emits `activity_event` with `category=tool_call` for observation. |
| `high`     | Same as medium; subagent also checkpoints to blackboard.                            |
| `critical` | **Blocks** on `ctx.confirm(...)` before execution. Non-interactive mode → denied.   |

MVP critical skills: `sqlmap-dump`, `hydra-bruteforce`. MVP medium skills: `sqlmap-detect`, `ffuf-dir-fuzz`, `ffuf-vhost-fuzz`, `nuclei-template-scan`.

### `handler.py`

```python
from secbot.skills.types import SkillContext

async def run(input: dict, ctx: SkillContext) -> dict:
    # argv is built from validated input; never from free text.
    result = await ctx.sandbox.run_command(
        binary="nmap",
        args=["-sn", "-PE", *input["targets"]],
        timeout_sec=120,
        network=ctx.network_policy,
        capture="file",
    )
    return {"hosts": parse_nmap_host_discovery(result.stdout_path)}
```

See [.trellis/spec/backend/tool-invocation-safety.md](../.trellis/spec/backend/tool-invocation-safety.md) for the hard contract: `run_command` is the single legal entry point. Direct `subprocess.*` / `os.system` / `shell=True` is review-blocking.

### `schema.json`

Standard JSON Schema. This is what the LLM sees — keep descriptions short and precise.

## Runtime Wiring

- **Discovery**: `SkillsLoader` walks `secbot/skills/`, loads each `SKILL.md`, and registers a `SkillTool` in the ToolRegistry. Tool name = skill folder name with hyphens converted to underscores.
- **Orchestrator**: sees `spawn(agent=...)`, `blackboard_read/write`, `request_approval`, etc. — **not** the skill tools directly.
- **Specialist sub-loops**: `SubagentManager._run_subagent(spec)` registers only `spec.scoped_skills` from the agent YAML. A sub-loop for `port_scan.yaml` sees `nmap-port-scan`, `fscan-port-scan`, `nmap-service-fingerprint` — nothing else.
- **Availability**: at startup, `AgentRegistry.check_availability()` runs `shutil.which(binary)` for each skill's `required_binaries`. If ALL of an agent's scoped skill binaries are missing, the agent is marked `status=offline` and returned as such from `GET /api/agents`. `spawn(agent="<offline>")` fails fast with a tool-error message listing the missing binaries.

## Error Surfaces

SkillTool catches and translates the following into LLM-readable tool errors:

| Exception                | Source                                             | LLM sees                                             |
|--------------------------|----------------------------------------------------|------------------------------------------------------|
| `BinaryNotAllowed`       | `sandbox.py` — binary outside `BINARY_WHITELIST`   | `"binary '<name>' is not permitted"`                 |
| `SkillBinaryMissing`     | `shutil.which` returned None for required binary   | `"binary '<name>' is not installed on this host"`    |
| `InvalidArgvCharacter`   | `sandbox.py` — argv contained `;&|$\`<>\n\r\\"'`   | `"argument contains forbidden character: '<char>'"`  |

## Re-enabling `exec`

If a power user truly needs the free-form shell tool back (e.g. local dev, non-security tasks):

```yaml
tools:
  exec:
    enable: true
```

This is **not recommended** for multi-agent orchestration — it bypasses binary whitelist and argv validation entirely. Prefer writing a skill.
