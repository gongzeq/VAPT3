# Removed IM Channels (Anti-Rollback Notice)

> Authoritative manifest of every IM channel and bridge component that was **intentionally deleted** when nanobot was rebranded to secbot.
> Purpose: prevent regression. If anyone proposes "let's restore IM support", this document is the no-go rationale.
> Source: `.trellis/tasks/05-07-cybersec-agent-platform/prd.md` §"R1 包重命名与 IM 清理" + Locked Decision #5.

---

## 1. Why these were removed

PRD Locked Decision #5 states:

> **secbot delivery surfaces are WebUI / CLI / OpenAI-compat HTTP API / Python SDK only.**

Reasons captured in the PRD and ADR-006:

1. **Scope discipline** — secbot is a security operations console for operators. Push-to-IM workflows do not match the destructive-confirmation UX required by [high-risk-confirmation.md](./high-risk-confirmation.md); IM clients cannot render the destructive AlertDialog in [frontend/component-patterns.md §3](../frontend/component-patterns.md#3-destructive-confirmation-dialog).
2. **Compliance surface** — every IM channel adds a third-party dependency, vendor T&C surface, and audit-trail gap. None of these are acceptable for a tool that may execute critical-risk skills (`hydra-bruteforce`, `fscan-weak-password`).
3. **Maintenance cost** — 13 IM connectors + 1 Node.js bridge are roughly 30% of the legacy nanobot codebase. Carrying them through the secbot rename and beyond is uncompensated overhead.
4. **No user demand for secbot** — secbot's persona (security analyst at a console) does not overlap with nanobot's persona (general LLM agent in a chat group).

Restoring any of these channels requires an ADR that explicitly overturns Locked Decision #5 AND addresses the destructive-confirmation gap above.

---

## 2. Removed Files (exhaustive)

The diff against the rename baseline is committed under PR2 of the `cybersec-agent-platform` task. The following files MUST remain absent.

### 2.1 Python channel modules (`nanobot/channels/` → `secbot/channels/`)

| Removed file | Channel |
|--------------|---------|
| `nanobot/channels/dingtalk.py` | DingTalk |
| `nanobot/channels/discord.py` | Discord |
| `nanobot/channels/email.py` | SMTP/IMAP email |
| `nanobot/channels/feishu.py` | Lark / Feishu |
| `nanobot/channels/matrix.py` | Matrix |
| `nanobot/channels/mochat.py` | MoChat |
| `nanobot/channels/msteams.py` | Microsoft Teams |
| `nanobot/channels/qq.py` | QQ |
| `nanobot/channels/slack.py` | Slack |
| `nanobot/channels/telegram.py` | Telegram |
| `nanobot/channels/wecom.py` | WeCom (企业微信) |
| `nanobot/channels/weixin.py` | WeChat (微信) |
| `nanobot/channels/whatsapp.py` | WhatsApp |

### 2.2 Tests

| Removed file |
|--------------|
| `tests/test_msteams.py` |
| `tests/channels/test_dingtalk_channel.py` |
| `tests/channels/test_discord_channel.py` |
| `tests/channels/test_email_channel.py` |
| `tests/channels/test_feishu_domain.py` |
| `tests/channels/test_feishu_markdown_rendering.py` |
| `tests/channels/test_feishu_mention.py` |
| `tests/channels/test_feishu_mentions.py` |
| `tests/channels/test_feishu_post_content.py` |
| `tests/channels/test_feishu_reaction.py` |
| `tests/channels/test_feishu_reply.py` |
| `tests/channels/test_feishu_streaming.py` |
| `tests/channels/test_feishu_table_split.py` |
| `tests/channels/test_feishu_tool_hint_code_block.py` |
| `tests/channels/test_matrix_channel.py` |
| `tests/channels/test_qq_ack_message.py` |
| `tests/channels/test_qq_channel.py` |
| `tests/channels/test_qq_media.py` |
| `tests/channels/test_slack_channel.py` |
| `tests/channels/test_telegram_channel.py` |
| `tests/channels/test_wecom_channel.py` |
| `tests/channels/test_weixin_channel.py` |
| `tests/channels/test_whatsapp_channel.py` |

### 2.3 WhatsApp bridge (`bridge/`)

The Node.js WhatsApp bridge built on Baileys is removed entirely. No equivalent surface exists in secbot.

| Removed file |
|--------------|
| `bridge/package.json` |
| `bridge/tsconfig.json` |
| `bridge/src/index.ts` |
| `bridge/src/server.ts` |
| `bridge/src/whatsapp.ts` |
| `bridge/src/types.d.ts` |

### 2.4 Docker compose entries

`docker-compose.yml` MUST NOT contain any service whose `command` references a deleted channel, nor any service named `*-bridge*`. The current compose file declares only `gateway`, `api`, and an opt-in `cli` profile — this is the only acceptable shape.

---

## 3. What is KEPT (do not delete by mistake)

Per PRD R1, these channel-infrastructure files stay because secbot still uses the WebSocket surface for the WebUI:

| Kept file | Why |
|-----------|-----|
| `secbot/channels/__init__.py` | Module init; exports `BaseChannel` and `ChannelManager`. |
| `secbot/channels/base.py` | Abstract base used by `websocket.py`. Removing it cascades. |
| `secbot/channels/manager.py` | Channel registration / lifecycle; the WebUI WS plugs into this. |
| `secbot/channels/registry.py` | Plugin registration map; reused by the assistant-ui WS adapter. |
| `secbot/channels/websocket.py` | The WebUI delivery surface — see [websocket-protocol.md](./websocket-protocol.md). |

If you find yourself shrinking this kept-list, **stop**. The WebUI surface depends on all five.

---

## 4. Reviewer Verification Checklist

Before approving any PR that touches `secbot/channels/` or the surfaces layer, run:

```bash
# 1. No IM channel modules survived (or got recreated under a new name).
grep -r -l -E "telegram|feishu|slack|discord|dingtalk|msteams|\bqq\b|wecom|weixin|whatsapp|mochat|matrix" \
    secbot/ tests/

# 2. No bridge directory.
test ! -d bridge/

# 3. No bridge service in compose.
grep -i -E "whatsapp|baileys|bridge" docker-compose.yml

# 4. No IM-channel docs leaked back in.
grep -r -l -E "telegram|feishu|slack|discord|dingtalk|msteams|wecom|whatsapp" docs/
```

All four commands MUST return empty output (or be limited to historical references inside `.trellis/`, `CHANGELOG`, license texts, and this file).

If you see hits in `secbot/channels/` itself, treat them as regression and fail the review.

---

## 5. Allowed Future Extensions

If the project later needs an external notification channel that does NOT violate Locked Decision #5 (e.g. a webhook receiver that the operator polls), it MUST:

1. Be added under a new directory (`secbot/notifiers/` or similar), NOT `secbot/channels/`. The `channels/` namespace is now reserved for in-app delivery surfaces only.
2. Carry an ADR amending the Locked Decision list.
3. Inherit the high-risk confirmation contract — there is no "fire-and-forget critical scan from an IM message" path, period.

---

## 6. Origin & Cross-References

- Locked Decision #5 — see PRD §"Locked Decisions".
- Surface layer responsibilities — see [architecture.md §1](./architecture.md#1-layering).
- WebUI delivery channel — see [websocket-protocol.md](./websocket-protocol.md).
- Why destructive flows can't run on IM — see [high-risk-confirmation.md §2](./high-risk-confirmation.md#2-confirmation-trigger) and [frontend/component-patterns.md §3](../frontend/component-patterns.md#3-destructive-confirmation-dialog).

## Related

- [architecture.md](./architecture.md) — surface-list decision and layering.
- [websocket-protocol.md](./websocket-protocol.md) — the only kept channel surface for WebUI.
- [high-risk-confirmation.md](./high-risk-confirmation.md) — why IM cannot host destructive flows.
- [../frontend/component-patterns.md](../frontend/component-patterns.md) — UI affordances IM cannot replicate.
- [../../tasks/05-07-cybersec-agent-platform/prd.md](../../tasks/05-07-cybersec-agent-platform/prd.md) — PRD §Locked Decisions #5 and §R1.
