# nanobot webui

The browser front-end for the nanobot gateway. It is built with Vite + React 18 +
TypeScript + Tailwind 3 + shadcn/ui, talks to the gateway over the WebSocket
multiplex protocol, and reads session metadata from the embedded REST surface
on the same port.

For the project overview, install guide, and general docs map, see the root
[`README.md`](../README.md).

## Current status

> [!NOTE]
> The standalone WebUI development workflow currently requires a source
> checkout.
>
> WebUI changes in the GitHub repository may land before they are included in
> the next packaged release, so source installs and published package versions
> are not yet guaranteed to move in lockstep.

## Layout

```text
webui/                 source tree (this directory)
nanobot/web/dist/      build output served by the gateway
```

## Develop from source

### 1. Install nanobot from source

From the repository root:

```bash
pip install -e .
```

### 2. Install WebUI dependencies

> [!IMPORTANT]
> This step is required before opening `webui/` in your editor. Without
> `node_modules`, TypeScript cannot resolve `react`, `lucide-react`,
> `react-i18next`, etc., and every `.tsx` file will light up with dozens of
> `JSX 元素隐式具有类型 "any"` / `找不到模块` errors. Those errors disappear
> the moment dependencies are installed.

```bash
cd webui
bun install            # npm install also works
```

Run this once after cloning and again whenever `package.json` / `bun.lock`
changes.

### 3. Enable the WebSocket channel

In `~/.nanobot/config.json`:

```json
{ "channels": { "websocket": { "enabled": true } } }
```

### 4. Start the gateway

In one terminal:

```bash
nanobot gateway
```

### 5. Start the WebUI dev server

In another terminal (dependencies from step 2 must already be installed):

```bash
cd webui
bun run dev
```

Then open `http://127.0.0.1:5173`.

By default, the dev server proxies `/api`, `/webui`, `/auth`, and WebSocket
traffic to `http://127.0.0.1:8765`.

If your gateway listens on a non-default port, point the dev server at it:

```bash
NANOBOT_API_URL=http://127.0.0.1:9000 bun run dev
```

### Access from another device (LAN)

To use the webui from another device on the same network, set `host` to `"0.0.0.0"` and configure a `token` or `tokenIssueSecret` in `~/.nanobot/config.json`:

```json
{
  "channels": {
    "websocket": {
      "enabled": true,
      "host": "0.0.0.0",
      "port": 8765,
      "tokenIssueSecret": "your-secret-here"
    }
  }
}
```

The gateway will refuse to start if `host` is `"0.0.0.0"` and neither `token` nor `tokenIssueSecret` is set.

Then open `http://<your-ip>:8765` on the other device. The webui will show an authentication form where you enter the secret. It is saved in your browser so you only need to enter it once.

## Build for packaged runtime

```bash
cd webui
bun run build
```

This writes the production assets to `../nanobot/web/dist`, which is the
directory served by `nanobot gateway` and bundled into the Python wheel.

If you are cutting a release, run the build before packaging so the published
wheel contains the current WebUI assets.

## Test

```bash
cd webui
bun run test
```

## Acknowledgements

- [`agent-chat-ui`](https://github.com/langchain-ai/agent-chat-ui) for UI and
  interaction inspiration across the chat surface.
