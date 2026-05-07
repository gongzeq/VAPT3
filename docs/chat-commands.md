# In-Chat Commands

These commands work inside chat channels and interactive agent sessions:

| Command | Description |
|---------|-------------|
| `/new` | Stop current task and start a new conversation |
| `/stop` | Stop the current task |
| `/restart` | Restart the bot |
| `/status` | Show bot status |
| `/dream` | Run Dream memory consolidation now |
| `/dream-log` | Show the latest Dream memory change |
| `/dream-log <sha>` | Show a specific Dream memory change |
| `/dream-restore` | List recent Dream memory versions |
| `/dream-restore <sha>` | Restore memory to the state before a specific change |
| `/model` | List models from the configured OpenAI-compatible endpoint |
| `/model <name>` | Switch the default model (takes effect on the next message, no restart) |
| `/help` | Show available in-chat commands |

## Choosing a Model with `/model`

`/model` works against the OpenAI-compatible endpoint configured in
Web UI → **Settings** → *OpenAI-compatible endpoint* (Base URL + API Key).

- **`/model`** — fetches `GET {base}/v1/models` (cached for 60 seconds) and
  returns a quick-reply picker. Click a button to switch.
- **`/model <name>`** — switches directly without hitting the endpoint. Useful
  when you already know the id, or when `/v1/models` is not reachable.

The selected model is written to `agents.defaults.model` in `config.json`.
[AgentLoop](../secbot/agent/loop.py) re-reads the config and rebuilds its
provider on the **next** user turn, so you never need to restart after a
switch. In-flight turns keep the previous model until they finish.

## Periodic Tasks

The gateway wakes up every 30 minutes and checks `HEARTBEAT.md` in your workspace (`~/.nanobot/workspace/HEARTBEAT.md`). If the file has tasks, the agent executes them and delivers results to your most recently active chat channel.

**Setup:** edit `~/.nanobot/workspace/HEARTBEAT.md` (created automatically by `nanobot onboard`):

```markdown
## Periodic Tasks

- [ ] Check weather forecast and send a summary
- [ ] Scan inbox for urgent emails
```

The agent can also manage this file itself — ask it to "add a periodic task" and it will update `HEARTBEAT.md` for you.

> **Note:** The gateway must be running (`nanobot gateway`) and you must have chatted with the bot at least once so it knows which channel to deliver to.
