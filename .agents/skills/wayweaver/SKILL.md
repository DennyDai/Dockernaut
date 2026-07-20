---
name: wayweaver
description: Control local or remote desktops, browsers, shells, Windows RDP hosts, and Android devices through Wayweaver MCP or its CLI.
---

# Wayweaver

Use Wayweaver when a task needs browser, desktop GUI, shell, VNC, RDP, X11, or Android interaction. It routes each capability to the best configured backend and can execute a full action sequence locally without an agent round-trip between steps.

## Install and configure

```bash
uv sync
cp targets.example.toml targets.toml
```

Edit `targets.toml`; do not commit credentials. Values support `${NAME}` and `${NAME:-default}` environment expansion. Set the config path explicitly when it is not `~/.config/wayweaver/targets.toml`:

```bash
export WAYWEAVER_CONFIG=/absolute/path/to/targets.toml
```

The reference Docker VM already contains the Linux runtime. For other targets, inspect and explicitly install the package-owned, versioned runtime through a named shell transport:

```bash
uv run wayweaver runtime doctor TARGET --platform linux --transport ssh
uv run wayweaver runtime inspect TARGET --platform linux
uv run wayweaver runtime install TARGET --platform linux --transport ssh
```

Probe targets before acting:

```bash
uv run wayweaver targets
```

Each target may combine adapters. Routing is operation- and capability-based:

- CDP: browser navigation, tabs, DOM text, CSS-targeted interaction, page capture, and page input.
- Local: execute shell operations and back native desktop adapters directly on the controller host.
- SSH: execute shell operations and transport desktop commands to remote targets.
- AT-SPI: Linux accessible elements, roles, state, actions, focus, text, and values.
- UIA: native Windows accessibility from the signed-in interactive session.
- X11 through any shell-capable transport: application catalog, window/workspace/clipboard semantics, desktop capture, and input.
- Wayland through any shell-capable transport: Sway IPC, KDE/KWin through `kdotool`, or the bundled GNOME Shell D-Bus bridge; capture and input remain capability-gated by live tools.
- VNC: protocol-native desktop screenshots and input fallback.
- RDP: Windows framebuffer and input through optional `aardwolf`.
- ADB: Android UIAutomator elements plus screenshot, input, shell, and optional `scrcpy`.

Run `wayweaver operations TARGET` before acting. It lists only currently routable canonical operations and the selected adapter. Add `--raw` only when semantic and visual operations are insufficient; it reveals raw operations for installed, available tools.

Keep capture and input on one coherent surface. A VNC screenshot must be acted on through VNC; X11 screenshots must use X11 input; an RDP framebuffer must use the same RDP session. Cross-backend fallback is valid only when coordinate spaces are known to match.

## MCP

Run the stdio server:

```bash
uv run wayweaver-mcp
```

Example client registration:

```json
{
  "mcpServers": {
    "wayweaver": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/repository", "run", "wayweaver-mcp"],
      "env": {
        "WAYWEAVER_CONFIG": "/absolute/path/to/repository/targets.toml"
      }
    }
  }
}
```

The MCP surface is deliberately small:

- `wayweaver_targets`: probe adapters, capabilities, and availability.
- `wayweaver_operations`: discover operations routable on a target; raw hatches are hidden by default.
- `wayweaver_do`: perform one canonical operation.
- `wayweaver_run`: execute an ordered canonical operation sequence locally.
- `wayweaver_capture`: return an MCP image, optionally constrained by native region or window.
- `wayweaver_observe`: return screen dimensions, screenshot path, OCR, and window metadata.
- `wayweaver_raw`: execute one adapter-specific operation previously returned by `wayweaver_operations(include_raw=true)`.

## CLI

```bash
uv run wayweaver targets
uv run wayweaver operations desktop
uv run wayweaver do desktop application.list
uv run wayweaver do desktop window.list
uv run wayweaver do desktop element.find '{"selector":{"name":"Save","role":"button"}}'
uv run wayweaver do desktop browser.navigate '{"url":"https://example.com"}'
uv run wayweaver capture desktop /tmp/current.png --params '{"window":"Terminal"}'
uv run wayweaver raw desktop x11 xprop '{"args":["-root"]}'
```

Use the hierarchy in this order: browser semantics through CDP; shell through SSH; accessible controls through AT-SPI; desktop applications/windows/workspaces/clipboard through X11 or Wayland; screenshot/OCR locators; coordinate input; an explicitly discovered raw operation.

## Batched operations

Use `wayweaver_run` or the CLI `run` command when the next operations are known. Canonical names are backend-neutral; the controller resolves every step against live adapter availability:

```bash
uv run wayweaver run desktop '{
  "steps": [
    {"application.open": "Xfce Terminal"},
    {"window.wait": {"selector": {"title": "Terminal"}, "timeout_ms": 3000}},
    {"window.assert": {"selector": {"title": "Terminal"}, "expect": {"active": true}}},
    {"keyboard.type": "whoami"},
    {"keyboard.press": "ENTER"},
    {"screen.observe": {"ocr": true}}
  ],
  "observe_after": true
}'
```

Operation families:

- `application.list`, `application.open`
- `window.list`, `window.wait`, `window.assert`, `window.focus`, `window.close`, `window.move`, `window.resize`, `window.minimize`, `window.maximize`, `window.fullscreen`, `window.restore`
- `workspace.list`, `workspace.switch`
- `clipboard.read`, `clipboard.write`
- `element.list`, `element.find`, `element.assert`, `element.wait`, `element.activate`, `element.focus`, `element.read`, `element.set_value`
- `browser.navigate`, `tab.list`, `browser.read`, `browser.click`, `browser.type`
- `pointer.move`, `pointer.click`, `pointer.drag`, `pointer.scroll`
- `keyboard.type`, `keyboard.press`, `keyboard.chord`
- `shell.execute`, `viewer.open`, `screen.observe`, `time.sleep`
- `recording.start`, `recording.status`, `recording.stop`, `recording.cancel`, `recording.capture`


The desktop is shared with a human. Semantic operations re-resolve applications, windows, and accessible elements at execution time. X11 reads the live pointer before every trajectory; CDP, VNC, RDP, and Wayland re-anchor with an absolute pointer event before moving. Before a destructive segment, use `element.assert` or `element.wait`; before coordinate input, use `window.assert`, `element.find`, or `screen.observe`. `screen.observe` returns signed `surface_id` and `observation_id` tokens that work across CLI processes, expire, reject older observations, and bind to the current graphical session when the adapter can identify it. UIA waits subscribe to native Windows accessibility events. AT-SPI and Android UIAutomator use bounded fresh-tree polling because remote providers and snapshot-only hierarchies do not offer a reliable cross-process event stream.

The runner stops at the first failure. It returns `failed_step`, the failed step, typed error, completed results, and a fresh observation by default. Correct the remaining sequence from that observation; do not replay completed non-idempotent steps.

Explicit steps may add bounded workflow controls: `id`, `retry` (`max_attempts` up to 10, `backoff_ms`, and optional `on_codes`), `repeat` (up to 100), `save_as`, and `when`. Retries run only for errors whose contract says `retryable: true`; `on_codes` narrows that set. A parameter object containing only `{"$ref":"saved.path"}` resolves a prior saved response before validation. Internal saved values remain complete for references, while the returned `saved` object is bounded by `saved_output_limit` (32 KiB by default).

```json
{"steps":[
  {"id":"observe","operation":"screen.observe","params":{},"save_as":"observation"},
  {"id":"move","operation":"pointer.move","params":{
    "point":{"x":640,"y":450},
    "space":"surface",
    "surface_id":{"$ref":"observation.data.surface.id"},
    "observation_id":{"$ref":"observation.data.observation_id"}
  },"retry":{"max_attempts":2,"backoff_ms":250}}
]}
```

OCR fallback selectors accept `text`, `contains`, `fuzzy`, `similarity`, `nth`, and `region`; use `timeout_ms` and `interval_ms` for bounded retries. A region is `{"x": X, "y": Y, "width": W, "height": H}` in the selected surface coordinates. Prefer native `element.*` operations whenever the control is accessible.

```json
{"element.activate":{"selector":{"name":"Terminal Emulator","role":"menu item","exact":true}}}
```

X11 targets with `wayweaver-x11-record` expose cross-process recordings for clicks, drags, vertical scrolling, keyboard input, and accessible-element activation. Use the lifecycle API when a human needs time to interact:

```bash
uv run wayweaver do desktop recording.start '{}'
uv run wayweaver do desktop recording.status '{"recording_id":"<id>"}'
uv run wayweaver do desktop recording.stop \
  '{"recording_id":"<id>","infer_elements":true}'
```

Use `recording.cancel` to discard a recording. `recording.capture` remains the bounded one-call form:

```bash
uv run wayweaver do desktop recording.capture \
  '{"duration_ms":5000,"infer_elements":true}'
```

`shell.execute` always returns `exit_code` and `success`. Set `check:true` to convert a disallowed exit code into `ACTION_FAILED`; customize success with `allowed_exit_codes`.

Raw access is explicit and discoverable:

```bash
uv run wayweaver operations desktop --raw
uv run wayweaver raw desktop x11 wmctrl '{"args":["-l"]}'
```

Do not guess a raw adapter command or use raw access merely because it is familiar.

## Platform-native semantics

The semantic stack is layered rather than pretending every desktop exposes one API:

1. CDP for browser DOM and browser input.
2. AT-SPI on Linux, UIA on Windows, and UIAutomator on Android for controls and state.
3. X11 EWMH or a compositor-specific Wayland API for windows and workspaces.
4. VNC/RDP framebuffer input, then screenshot/OCR, only when native metadata is unavailable.

Use `element.assert` for an immediate precondition and `element.wait` for appearance or a state transition. Put identity fields under `selector`, state requirements under `expect`, and all public durations in integer milliseconds:

```json
{"element.wait":{"selector":{"name":"Save","role":"button"},"expect":{"state":"enabled","value":true},"timeout_ms":5000}}
```

### GNOME Wayland

Install the packaged extension through the graphical user's local or SSH transport, then enable it and log out and back in before probing:

```bash
uv run wayweaver runtime install gnome --platform gnome --transport local
gnome-extensions enable wayweaver@wayweaver.local
```

Configure a Wayland adapter with `compositor = "gnome"`. The extension exports window/workspace metadata and actions only on the user's session D-Bus; it opens no network listener. `gnome-screenshot` supplies capture when installed, while `wtype`/`ydotool` and `wl-clipboard` independently gate input and clipboard capabilities.

```toml
[targets.gnome]
prefer = ["wayland", "atspi", "local"]

[targets.gnome.local]
kind = "local"

[targets.gnome.wayland]
transport = "local"
display = "wayland-0"
compositor = "gnome"
```

### KDE Wayland

Install `kdotool` in the graphical session and set `compositor = "kde"`. Wayweaver uses KWin's D-Bus scripting interface through `kdotool` for window identity, geometry, state, actions, and virtual desktops. Install Spectacle for capture; input and clipboard remain separately capability-gated.

```toml
[targets.kde.wayland]
transport = "local"
display = "wayland-0"
compositor = "kde"
```

### Windows UI Automation

Run Wayweaver as the signed-in desktop user, install the packaged UIA runtime with `wayweaver runtime install windows --platform windows --transport local`, and enable the `local` plus `uia` example in `targets.example.toml`. UIA exposes roles, names, automation IDs, state, bounds, native invoke/toggle/select patterns, focus, text, and writable values. Windows service/OpenSSH sessions are isolated from the signed-in desktop; use RDP only as the framebuffer/input fallback for a remote machine unless an agent runs inside that interactive session.

### Android UIAutomator

The ADB adapter probes `uiautomator` and advertises `element.*` only when the device provides it. Match by `name`, `text`, `resource_id`/`id`, `class`, `role`, or `package`; actions re-dump the hierarchy immediately before tapping or setting text. UIAutomator has no persistent cross-device event stream, so waits refresh bounded XML snapshots.

## Native Linux host

Use the `local` transport to control the Linux desktop on which Wayweaver itself runs. Run Wayweaver from the repository root, install `maim`, `xdotool`, `wmctrl`, `xclip`, `x11-utils`, and `python3-pyatspi`, then enable the host example in `targets.example.toml`:

```toml
[targets.host]
prefer = ["x11", "atspi", "local"]

[targets.host.local]
kind = "local"
cwd = "."

[targets.host.x11]
transport = "local"
display = "${DISPLAY:-:0}"

[targets.host.atspi]
transport = "local"
display = "${DISPLAY:-:0}"
```

The controller process must run as the graphical user and have access to that session's `DISPLAY`, Xauthority, and D-Bus. Install its runtime first with `wayweaver runtime install host --platform linux --transport local`. If the graphical environment is unavailable, the local target still exposes `shell.execute`, while desktop operations return an explicit availability error. For a remote machine, replace the local table with an SSH table and set `transport = "ssh"` on X11, Wayland, and AT-SPI.

Direct host control is equivalent to controlling an unlocked desktop. Prefer a dedicated user/session when isolation matters; VNC remains the pixel fallback rather than the primary native API.


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

`/home/vm` is the swappable desktop identity. `VM_HOME` defaults to `./homes/default`; the separate `ssh-host-keys` volume preserves the VM's SSH host identity across container recreation. Change `VM_HOME` and recreate the service to switch desktop identities:

```bash
docker compose up -d --force-recreate
```

Keep `BIND_ADDR=127.0.0.1` unless remote access is intentional and protected. SSH/VNC credentials come from `.env`; never print or commit that file. CDP grants full browser control.

The image installs the same package-owned Linux runtime assets used for non-Docker targets. Docker owns only the OS dependencies, desktop session, browser, and SSH/VNC/CDP access topology.
