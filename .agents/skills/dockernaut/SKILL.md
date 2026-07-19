---
name: dockernaut
description: Control local or remote desktops, browsers, shells, Windows RDP hosts, and Android devices through Dockernaut MCP or its CLI.
---

# Dockernaut

Use Dockernaut when a task needs browser, desktop GUI, shell, VNC, RDP, X11, or Android interaction. It routes each capability to the best configured backend and can execute a full action sequence locally without an agent round-trip between steps.

## Install and configure

```bash
cd agent
uv sync
cp targets.example.toml targets.toml
```

Edit `targets.toml`; do not commit credentials. Values support `${NAME}` and `${NAME:-default}` environment expansion. Set the config path explicitly when it is not `~/.config/dockernaut/targets.toml`:

```bash
export DOCKERNAUT_CONFIG=/absolute/path/to/targets.toml
```

Probe targets before acting:

```bash
uv run dockernaut targets
```

Each target may combine adapters. Typical capability routing:

- CDP: Chrome DOM/accessibility control, page screenshots, page pointer and keyboard input.
- X11 over SSH: Linux desktop screenshots, windows, pointer, and keyboard.
- VNC: protocol-native desktop screenshots, pointer, and keyboard.
- RDP: Windows framebuffer, pointer, and keyboard through optional `aardwolf`.
- ADB: Android screenshot, pointer, keyboard, shell, and optional `scrcpy`.
- SSH: shell commands and transport for X11.

Keep capture and input on one coherent surface. A VNC screenshot must be acted on through VNC; X11 screenshots must use X11 input; an RDP framebuffer must use the same RDP session. Cross-backend fallback is valid only when coordinate spaces are known to match.

## MCP

Run the stdio server:

```bash
uv run dockernaut-mcp
```

Example client registration:

```json
{
  "mcpServers": {
    "dockernaut": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/agent", "run", "dockernaut-mcp"],
      "env": {
        "DOCKERNAUT_CONFIG": "/absolute/path/to/agent/targets.toml"
      }
    }
  }
}
```

The MCP surface is deliberately small:

- `dockernaut_targets`: probe adapters and capabilities.
- `dockernaut_capture`: return a target screenshot as image content.
- `dockernaut_observe`: save a screenshot and return screen, OCR, and window metadata.
- `dockernaut_act`: perform one action.
- `dockernaut_run`: execute a batch and return structured recovery state on failure.
- `dockernaut_shell`: run a shell command.
- `dockernaut_browser`: call a raw Chrome DevTools Protocol method.

## CLI

```bash
uv run dockernaut targets
uv run dockernaut observe desktop --ocr
uv run dockernaut capture desktop /tmp/current.png
uv run dockernaut shell desktop 'uname -a'
uv run dockernaut browser desktop Runtime.evaluate '{"expression":"document.title","returnByValue":true}'
uv run dockernaut act desktop click '{"x":45,"y":13}'
```

Prefer CDP for browser content and SSH for shell output. Use visual desktop control only when semantic interfaces do not cover the task.

## Batched actions

Use `dockernaut_run` or the CLI `run` command when the next operations are known. The controller executes the sequence without asking an agent after every step:

```bash
uv run dockernaut run desktop '{
  "steps": [
    {"click": [45, 13]},
    {"click_text": {"text": "Terminal Emulator", "timeout": 3}},
    {"type": "whoami"},
    {"key": "Return"},
    {"wait_text": {"text": "vm", "timeout": 2}}
  ],
  "observe_after": true
}'
```

Supported operations include `move`, `click`, `double_click`, `right_click`, `drag`, `scroll`, `click_text`, `click_element`, `assert_text`, `wait_text`, `type`, `key`, `hotkey`, `wait`, `observe`, `screenshot`, `clear`, and Android `viewer`.

Coordinate pointer actions use randomized curved, eased trajectories and land exactly on the requested endpoint. This emulates ordinary pointer movement; it is not an anti-bot guarantee.

OCR locators accept `text`, `contains`, `fuzzy`, `similarity`, `nth`, `region`, `timeout`, `interval`, and `button`. A region is `[left, top, right, bottom]` in native target coordinates:

```json
{"click_text":{"text":"Desktop","region":[900,400,1200,800],"nth":0}}
```

Locator results report `matches` within the region and `total_matches` across the screen. Use a region and then `nth` to disambiguate repeated labels. When a full-screen OCR pass misses text inside an explicit region, Dockernaut automatically retries with a dense-text page segmentation mode and fuzzy token matching. Set `fuzzy` explicitly to override that fallback; `similarity` defaults to `0.8`.

The runner stops at the first failure. It returns `failed_step`, the failed step, error type and message, completed results, and a fresh observation by default. Correct the remaining sequence from that observation; do not replay completed non-idempotent steps.

## Bundled Ubuntu desktop

Start the repository VM with Compose:

```bash
docker compose up -d --build
docker compose ps
```

The web desktop is:

```text
http://${BIND_ADDR:-127.0.0.1}:${DESKTOP_PORT:-6080}/vnc.html?autoconnect=1&resize=remote
```

SSH uses `${SSH_PORT:-2222}`, native VNC uses `${VNC_PORT:-5901}`, and CDP uses `${CDP_PORT:-9222}`. Interactive SSH logins set `DISPLAY=:1`, so graphical programs launched with SSH appear in the shared desktop.

Only `/home/vm` persists. `VM_HOME` defaults to `./homes/default`; change it and recreate the service to switch desktop identities:

```bash
docker compose up -d --force-recreate
```

Keep `BIND_ADDR=127.0.0.1` unless remote access is intentional and protected. SSH/VNC credentials come from `.env`; never print or commit that file. CDP grants full browser control.

The image retains lightweight guest-side fallback commands in `docker/guest-tools/`: `agent-observe`, `agent-run`, `agent-mouse`, `agent-type`, `agent-key`, screenshot/OCR helpers, and compatibility wrappers. Prefer the host-side controller for modular protocol routing.
