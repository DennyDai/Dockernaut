# Wayweaver

Wayweaver routes browser, desktop, shell, and mobile operations through the best available native interface. This repository includes the Python CLI/MCP controller and an optional Ubuntu desktop VM.

## Desktop VM

Create `.env` from `.env.example`, set strong credentials, then start the VM:

```bash
docker compose up -d --build
docker compose ps
```

The human desktop is available at `http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale`.

## Controller

```bash
uv sync
cp targets.example.toml targets.toml
uv run wayweaver --config targets.toml targets
```

Set the target credentials directly or through the environment variables referenced by `targets.toml`.

The reference VM already includes the Linux runtime. Deploy package-owned helpers to other targets explicitly:

```bash
uv run wayweaver --config targets.toml runtime doctor host --platform linux
uv run wayweaver --config targets.toml runtime inspect host --platform linux
uv run wayweaver --config targets.toml runtime install host --platform linux
```

Core commands:

```bash
uv run wayweaver --config targets.toml operations desktop
uv run wayweaver --config targets.toml do desktop screen.observe '{}'
uv run wayweaver --config targets.toml run desktop sequence.json
uv run wayweaver-mcp
```

Prefer CDP, shell, accessibility, window, and workspace semantics. Use coordinates only when semantic operations cannot express the action, and bind them to the signed surface and observation tokens returned by `screen.observe`.

Full operating and platform guidance: `.agents/skills/wayweaver/SKILL.md`.
