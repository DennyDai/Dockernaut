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

For non-browser GUI work, take a screenshot first. noVNC exposes the desktop as pixels, so screenshot inspection is the primary way to understand visible state before clicking.

Dump a screenshot into the mounted home so the host-side agent can read it directly:

```bash
ssh -p "${SSH_PORT:-2222}" vm@"${BIND_ADDR:-127.0.0.1}" 'agent-screenshot'
```

Default in-container output:

```text
/home/vm/.agent/screenshots/current.png
```

Default host-side path:

```text
${VM_HOME:-./homes/default}/.agent/screenshots/current.png
```

After reading the image, clear the screenshot dropbox:

```bash
ssh -p "${SSH_PORT:-2222}" vm@"${BIND_ADDR:-127.0.0.1}" 'agent-clear-screenshots'
```

Use `desktop-screenshot <path>` for one-off captures outside the shared dropbox. Run OCR on a screenshot when exact visible text matters:

```bash
ssh -p "${SSH_PORT:-2222}" vm@"${BIND_ADDR:-127.0.0.1}" 'desktop-ocr /home/vm/.agent/screenshots/current.png'
```

Use `xdotool` for pointer and keyboard actions, `wmctrl` for window management, and `xwininfo -root -tree` to inspect window placement. Prefer screenshots plus explicit coordinates for desktop-only apps. Prefer CDP for browser pages and SSH for shell output whenever those semantic interfaces are available.

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
