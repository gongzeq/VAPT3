# secbot Context

secbot is a conversational VAPT system where a surface sends user work to an Orchestrator, the Orchestrator delegates to Expert Agents, and Expert Agents invoke Skills that may update the CMDB or produce report artifacts.

## Language

**Surface**:
The user-facing entry point that transports messages, events, and approvals between a user and the Agent Turn Runtime.
_Avoid_: client, channel, UI layer

**Agent Turn Runtime**:
The runtime that executes one conversational turn, including streaming text, tool progress, checkpointing, cancellation, and final turn completion.
_Avoid_: main loop, agent loop internals

**Orchestrator**:
The top-level agent that interprets a VAPT task and delegates operational work to Expert Agents.
_Avoid_: coordinator, planner service

**Expert Agent**:
A scoped agent declared in YAML that performs one security domain of work through its allowed Skills.
_Avoid_: subagent, worker, specialist service

**Skill**:
A packaged security capability with metadata, schemas, and a handler that returns structured results.
_Avoid_: tool script, command wrapper

**CMDB**:
The local inventory of scans, assets, services, vulnerabilities, and report metadata.
_Avoid_: database, asset store

**Report Artifact**:
A generated VAPT deliverable such as HTML, Markdown, DOCX, or PDF.
_Avoid_: output file, export

## Relationships

- A **Surface** sends a user message into exactly one **Agent Turn Runtime** execution.
- The **Agent Turn Runtime** runs the **Orchestrator** for the turn.
- The **Orchestrator** delegates operational work to one or more **Expert Agents**.
- An **Expert Agent** invokes one or more **Skills**.
- A **Skill** may persist structured findings into the **CMDB**.
- A **Report Artifact** is generated from structured findings in the **CMDB**.

## Example dialogue

> **Dev:** "Should the WebUI own tool-call streaming state?"
> **Domain expert:** "No - the **Surface** should render events emitted by the **Agent Turn Runtime**, not reconstruct runtime state from scattered hints."

## Flagged ambiguities

- "subagent" appears in implementation names, but domain discussion should use **Expert Agent** when referring to YAML-scoped security agents.
