# Wayweaver project

This repository contains two deliberately separate products:

- `docker/` and `compose.yaml`: an interactive Ubuntu 26.04 desktop container for humans and agents.
- `src/`, `pyproject.toml`, and `tests/`: the host-side Python MCP/CLI controller, which can operate this VM or unrelated remote targets.

The reusable operating skill is `.agents/skills/wayweaver/SKILL.md`.

## Product requirements

Preserve these user requirements:

- Chrome, SSH, VNC/noVNC, and XFCE share one visible desktop. A graphical process launched over SSH must appear in that desktop.
- `/home/vm` is the swappable persistent identity. `VM_HOME` selects it; `homes/` stays ignored.
- noVNC is the primary human access path; native VNC remains available.
- Host ports default to loopback. Credentials and local target files are never committed or printed.
- The host controller supports modular local and SSH command transports plus X11, Wayland, AT-SPI, Windows UIA, VNC, CDP, RDP, and Android ADB/UIAutomator adapters.
- Capabilities and live availability, not target names or operating-system assumptions, determine routing. External adapters load through the `wayweaver.adapters` entry-point group.
- The public automation contract is the canonical operation registry: discover with `operations`, execute with `do` or `run`, and use an explicitly discovered `raw` adapter operation only as a last resort.
- Prefer CDP for browser semantics, local/SSH transports for shell semantics, AT-SPI/UIA/UIAutomator for accessible elements, and native compositor APIs for applications, windows, workspaces, and clipboard. Use OCR and coordinates only when semantic interfaces cannot express the operation; use VNC/RDP when native desktop control is unavailable.
- Screenshot and coordinate input must use a coherent session and coordinate space. Never silently act through an unrelated fallback surface.
- Known operation chains execute locally as one declarative sequence. Do not require one model/agent call per click.
- Failed sequences stop immediately and return the failed step, completed steps, error, and a fresh observation when possible. A step retries only errors explicitly marked retryable; optional error-code filters may narrow retries further.
- Assume a human may move the pointer or change UI state between steps. Native desktop input must resolve the live pointer or re-anchor it with an absolute event before every trajectory. Guard destructive steps with `window.assert`, `element.assert`, `element.wait`, or a fresh `screen.observe`; coordinate actions may bind signed, expiring `surface_id` and `observation_id` tokens that remain verifiable across controller processes and reject replaced sessions.
- OCR text locators support repeated-label disambiguation with `region` and `nth`.
- Pointer actions use human-like curved/eased paths while landing on the exact endpoint. This is interaction realism, not an anti-bot claim.
- Keep the MCP surface compact and the code modular. Generic semantic operations belong in the registry; backend-specific commands belong only in discoverable raw escape hatches.
- X11 recordings use independent start/status/stop/cancel lifecycle state, unique recording IDs, semantic accessibility inference where possible, and explicit coordinate fallbacks for clicks, drags, and scrolling.
- Package target-side helpers and platform bridges under `src/wayweaver/runtime/`; adapters consume versioned runtime paths, and the reference Docker image consumes those same packaged Linux assets.
- Native desktop adapters depend on a configured shell-capable `transport`, never a concrete SSH implementation. Native-host targets use `local`; remote targets use `ssh`. Windows UIA must run in the signed-in interactive session; an OpenSSH service session cannot inspect another Windows session.
- Wayland window control is compositor-specific: Sway IPC for wlroots, KWin scripting through `kdotool` for KDE, and the bundled session D-Bus GNOME Shell extension for GNOME. Never claim generic Wayland window metadata from pixels.
- Accessibility waits use OS event streams where available and bounded refreshes for stale or snapshot-only trees. Re-resolve the element immediately before every action; never retain a UIA, AT-SPI, or UIAutomator object across steps.

## Repository rules

Use Docker Compose rather than a bare `docker run`; Compose owns persistence, shared memory, ports, and runtime configuration.

Do not commit `.env`, `targets.toml`, VM homes, controller caches, virtual environments, screenshots, or credentials. Add permanent guest dependencies to `docker/Dockerfile`; do not rely on changes made inside a running container.

Python controller changes require the focused unit suite and an end-to-end exercise against an available target. Docker changes require a rebuild and healthy-container check. GUI behavior must be verified through the visible desktop surface, not inferred from process state alone.

Optional protocol dependencies belong in extras. Import them lazily and return actionable availability errors when they are absent. Prefer credible protocol libraries for complex transports; small self-contained clients are acceptable for stable, narrow protocols such as VNC and CDP.
