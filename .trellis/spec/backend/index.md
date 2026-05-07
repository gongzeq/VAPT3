# Backend Development Guidelines

> Best practices for backend development in this project.

---

## Overview

This directory contains guidelines for backend development. Fill in each file with your project's specific conventions.

---

## Guidelines Index

### General

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | To fill |
| [Database Guidelines](./database-guidelines.md) | ORM patterns, queries, migrations | To fill |
| [Error Handling](./error-handling.md) | Error types, handling strategies | To fill |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | To fill |
| [Logging Guidelines](./logging-guidelines.md) | Structured logging, log levels | To fill |

### VAPT3 Domain Contracts

> Authoritative business contracts for the cybersec agent platform. Sourced from `.trellis/tasks/05-07-cybersec-agent-platform/prd.md`. Changes require an ADR.

| Guide | Description | Status |
|-------|-------------|--------|
| [Architecture](./architecture.md) | Two-layer (Orchestrator + Expert) topology, data flow, layer boundaries | Active |
| [Agent Registry Contract](./agent-registry-contract.md) | Expert agent YAML schema, registration, discovery | Active |
| [Skill Contract](./skill-contract.md) | `SKILL.md` front-matter, `handler.run()` signature, schemas | Active |
| [Orchestrator Prompt](./orchestrator-prompt.md) | Top-level system prompt skeleton + multi-turn routing strategy | Active |
| [Tool Invocation Safety](./tool-invocation-safety.md) | Single sandbox entry point, binary whitelist, no shell | Active |
| [High-Risk Confirmation](./high-risk-confirmation.md) | `risk_level` semantics, `ask_user` blocking contract | Active |
| [Context Trimming](./context-trimming.md) | `summary_json` budgets vs `raw_log_path`, autocompact policy | Active |
| [CMDB Schema](./cmdb-schema.md) | SQLite tables, `actor_id` reservation, migration policy | Active |
| [Report Pipeline](./report-pipeline.md) | Markdown-canonical render path, DOCX/PDF skills, severity-color binding | Active |
| [Scan Lifecycle](./scan-lifecycle.md) | Scan state machine, bus events, cancellation semantics | Active |
| [WebSocket Protocol](./websocket-protocol.md) | Wire envelope, server↔client event catalog, versioning | Active |
| [Removed IM Channels](./removed-im-channels.md) | Anti-rollback manifest for the 13 deleted IM channels + bridge | Active |

---

## How to Fill These Guidelines

For each guideline file:

1. Document your project's **actual conventions** (not ideals)
2. Include **code examples** from your codebase
3. List **forbidden patterns** and why
4. Add **common mistakes** your team has made

The goal is to help AI assistants and new team members understand how YOUR project works.

---

**Language**: All documentation should be written in **English**.
