# Desktop VM

This repository defines an interactive Ubuntu 26.04 desktop container. Use Docker Compose, not a bare `docker run`: Compose supplies the persistent home mount, shared memory, configurable port mappings, and runtime configuration.

## Start and inspect

```bash
docker compose up -d --build
docker compose ps
docker compose logs --no-color desktop-vm
```

A ready container reports `healthy`. Stop it with `docker compose down`. Configuration and credentials come from `.env`; do not print or commit that file. Defaults and supported variables are documented in `.env.example`.

## Preferred agent access

Use CDP for browser automation. It controls the same visible Chrome instance shown on the desktop:

```text
http://${BIND_ADDR:-127.0.0.1}:${CDP_PORT:-9222}
```

Useful discovery endpoints:

```bash
curl -fsS "http://${BIND_ADDR:-127.0.0.1}:${CDP_PORT:-9222}/json/version"
curl -fsS "http://${BIND_ADDR:-127.0.0.1}:${CDP_PORT:-9222}/json/list"
```

Attach Puppeteer, Playwright, or another CDP client to that endpoint rather than launching a separate headless browser. Browser actions are then visible to a human through the web desktop.

Use SSH for shell and graphical application launches:

```bash
ssh -p "${SSH_PORT:-2222}" vm@"${BIND_ADDR:-127.0.0.1}"
chrome https://example.com
```

Interactive SSH login sets `DISPLAY=:1` and `CDP_URL=http://127.0.0.1:9222`. For a non-interactive SSH command, set the display explicitly for graphical programs:

```bash
ssh -p "${SSH_PORT:-2222}" vm@"${BIND_ADDR:-127.0.0.1}" 'DISPLAY=:1 chrome https://example.com'
```

Prefer SSH and CDP over `docker exec`; they exercise the same interfaces intended for normal use. Use `docker exec` only for container-level diagnosis that cannot be performed as `vm`.

## Desktop GUI control

For non-browser GUI work, run an observe-act-observe loop. noVNC exposes the desktop as pixels, so screenshot inspection is the primary way to understand visible state before clicking.

Observe the current desktop:

```bash
ssh -p "${SSH_PORT:-2222}" vm@"${BIND_ADDR:-127.0.0.1}" 'agent-observe --ocr'
```

`agent-observe` writes a screenshot to:

```text
/home/vm/.agent/screenshots/current.png
```

Host-side agents can read it at:

```text
${VM_HOME:-./homes/default}/.agent/screenshots/current.png
```

Act with small, explicit human input operations:

```bash
agent-mouse move 800 450
agent-mouse click 45 13
agent-mouse double-click 300 200
agent-mouse click 300 200 3
agent-mouse drag 825 570 1100 720 --duration-ms 700
agent-mouse scroll down 5 --x 800 --y 450
agent-mouse down 1
agent-mouse up 1
agent-type whoami
agent-key Return
agent-key ctrl+l
```

`agent-mouse` provides generic move, click, double-click, right-click through button `3`, drag, scroll, button-down, and button-up primitives. Pointer travel follows a randomized curved, eased path with slight timing variation and always lands on the exact requested coordinate before acting; this applies when moving between successive clicks as well as during drags. `--duration-ms` overrides movement duration when a task needs deliberate speed. `agent-click X Y [BUTTON]` remains as a shorthand for `agent-mouse click`. `agent-type TEXT` enters text and `agent-key KEY...` sends keys or shortcuts.

Then observe again before the next action. Use `wmctrl -lG`, `xwininfo -root -tree`, or the `windows` field from `agent-observe` to derive coordinates from window geometry rather than guessing. Do not add app-specific action commands when the operation can be expressed as ordinary pointer or keyboard input.

For several known actions, use `agent-run` instead of round-tripping after every step. It accepts an AutoHotkey-like declarative JSON sequence while retaining the humanized mouse behavior:

```bash
agent-run '[
  {"click":[45,13]},
  {"click_text":{"text":"Terminal Emulator","timeout":3}},
  {"type":"whoami"},
  {"key":"Return"},
  {"wait_text":{"text":"vm","timeout":2}}
]'
```

Supported operations include `move`, `click`, `double_click`, `right_click`, `drag`, `scroll`, `click_text`, `click_element`, `assert_text`, `wait_text`, `type`, `key`, `hotkey`, `wait`, `observe`, `screenshot`, and `clear`. Examples:

```json
[
  {"hotkey":"ctrl+a"},
  {"key":"BackSpace"},
  {"click_element":{"text":"XXX","contains":true}},
  {"right_click":[500,300]},
  {"drag":[825,542,1100,700]}
]
```

`click_text` and `click_element` use screenshot OCR to locate visible text, then move along a randomized path and click its center. Locator options include `text`, `contains`, `nth`, `region`, `timeout`, `interval`, and `button`. `region` is `[left, top, right, bottom]` in native desktop coordinates and keeps only matches whose center falls inside it:

```json
{"click_text":{"text":"Desktop","region":[900,400,1200,800]}}
```

Locator results report both `matches` inside the region and `total_matches` across the screen. Combine `region` with `nth` when the constrained area still contains repeated labels.

The runner stops on the first failed action and returns structured JSON containing `failed_step`, the failed action, the error, completed steps, and a fresh observation with screenshot path, OCR, active window, pointer, and window geometry. Use that observation to correct the sequence. A successful batch returns every action result and elapsed time; set top-level `observe_after` to `true` when a final screenshot/OCR observation is needed.

After reading screenshots, clear the handoff directory:

```bash
ssh -p "${SSH_PORT:-2222}" vm@"${BIND_ADDR:-127.0.0.1}" 'agent-clear'
```

Use `desktop-screenshot <path>` for one-off captures outside the shared dropbox. Run `desktop-ocr <path>` on a screenshot when exact visible text matters. Prefer CDP for browser pages and SSH for shell output whenever those semantic interfaces are available.

## Human desktop access

Open noVNC in a local browser:

```text
http://${BIND_ADDR:-127.0.0.1}:${DESKTOP_PORT:-6080}/vnc.html?autoconnect=1&resize=remote
```

A native VNC client can connect to `${BIND_ADDR:-127.0.0.1}:${VNC_PORT:-5901}`. VNC and SSH passwords come from `.env`.

## Persistence and VM switching

Only `/home/vm` is persistent. It maps from `VM_HOME`, which defaults to `./homes/default`; `homes/` is intentionally gitignored. Change `VM_HOME` in `.env`, then recreate the service to switch user state:

```bash
docker compose up -d --force-recreate
```

Chrome profiles, downloads, desktop settings, and user files follow `VM_HOME`. Packages installed with `apt` and other system-level container changes do not; add permanent system dependencies to `docker/Dockerfile` and rebuild.

## Security constraints

`BIND_ADDR` controls which host interface receives published ports. Keep `BIND_ADDR=127.0.0.1` for local-only use. Set `BIND_ADDR=0.0.0.0` only when another machine must connect and the SSH/VNC passwords are strong; CDP grants full control of Chrome. Do not make the container privileged merely to enable Chrome's sandbox; Chrome currently runs non-root with `--no-sandbox` inside the Docker isolation boundary.
