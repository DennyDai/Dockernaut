# Dockernaut project

This repository has two deliberately separate products:

- `docker/` and `compose.yaml`: an interactive Ubuntu 26.04 desktop container for humans and agents.
- `agent/`: a host-side Python MCP/CLI controller that can operate this VM or unrelated remote targets.

The reusable operating skill is `.agents/skills/dockernaut/SKILL.md`.

## Product requirements

Preserve these user requirements:

- Chrome, SSH, VNC/noVNC, and XFCE share one visible desktop. A graphical process launched over SSH must appear in that desktop.
- `/home/vm` is the swappable persistent identity. `VM_HOME` selects it; `homes/` stays ignored.
- noVNC is the primary human access path; native VNC remains available.
- Host ports default to loopback. Credentials and local target files are never committed or printed.
- The host controller supports modular SSH, X11, VNC, CDP, RDP, and Android ADB adapters.
- Capabilities, not target names, determine routing. External adapters load through the `dockernaut.adapters` entry-point group.
- Screenshot and coordinate input must use a coherent session and coordinate space. Never silently act through an unrelated fallback surface.
- Prefer CDP for browser semantics, SSH for shell semantics, and X11 application/window primitives for Linux desktop semantics. Use OCR and coordinate control only when those interfaces cannot express the operation; use VNC when X11 is unavailable.
- Known action chains execute locally as one declarative sequence. Do not require one model/agent call per click.
- Failed sequences stop immediately and return the failed step, completed steps, error, and a fresh observation when possible.
- OCR text locators support repeated-label disambiguation with `region` and `nth`.
- Pointer actions use human-like curved/eased paths while landing on the exact endpoint. This is interaction realism, not an anti-bot claim.
- Keep the MCP surface compact and the code modular. Avoid app-specific commands when generic pointer, keyboard, shell, or protocol actions suffice.
- Keep guest helper tools separate in `docker/guest-tools/`; the host controller must not depend on baking itself into the VM.

## Repository rules

Use Docker Compose rather than a bare `docker run`; Compose owns persistence, shared memory, ports, and runtime configuration.

Do not commit `.env`, `agent/targets.toml`, VM homes, controller caches, virtual environments, screenshots, or credentials. Add permanent guest dependencies to `docker/Dockerfile`; do not rely on changes made inside a running container.

Python controller changes require the focused unit suite and an end-to-end exercise against an available target. Docker changes require a rebuild and healthy-container check. GUI behavior must be verified through the visible desktop surface, not inferred from process state alone.

Optional protocol dependencies belong in extras. Import them lazily and return actionable availability errors when they are absent. Prefer credible protocol libraries for complex transports; small self-contained clients are acceptable for stable, narrow protocols such as VNC and CDP.
