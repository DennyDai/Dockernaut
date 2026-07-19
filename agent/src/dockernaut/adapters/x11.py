import shlex
from typing import Any

from ..errors import ActionError, ConfigError
from ..image import png_size
from ..motion import trajectory
from ..types import Capability, Frame
from .base import Adapter
from .ssh import SSHAdapter


class X11Adapter(Adapter):
    kind = "x11"
    capabilities = frozenset({Capability.CAPTURE, Capability.POINTER, Capability.KEYBOARD, Capability.WINDOWS})

    def __init__(self, name: str, config: dict[str, Any], ssh: SSHAdapter):
        super().__init__(name, config)
        self.ssh = ssh
        self.display = str(config.get("display", ":1"))

    def _command(self, body: str) -> str:
        display = shlex.quote(self.display)
        return f"export DISPLAY={display}; export XDG_RUNTIME_DIR=/run/user/$(id -u); {body}"

    async def _run(self, body: str, stdin: bytes | None = None) -> bytes:
        code, stdout, stderr = await self.ssh.shell(self._command(body), stdin)
        if code:
            raise ActionError(stderr.decode(errors="replace").strip() or f"remote command exited {code}")
        return stdout

    async def available(self) -> tuple[bool, str | None]:
        available, reason = await self.ssh.available()
        if not available:
            return False, reason
        try:
            await self._run("command -v maim >/dev/null && command -v xdotool >/dev/null")
            return True, None
        except ActionError as error:
            return False, str(error)

    async def capture(self) -> Frame:
        png = await self._run("maim -u")
        width, height = png_size(png)
        return Frame(png, width, height, self.kind)

    async def _pointer(self) -> tuple[int, int]:
        output = (await self._run("xdotool getmouselocation --shell")).decode()
        values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        return int(values["X"]), int(values["Y"])

    async def _move_script(self, x: int, y: int, duration_ms: int | None = None) -> str:
        points, duration = trajectory(await self._pointer(), (x, y), duration_ms)
        delay = duration / max(1, len(points)) / 1000
        commands = []
        for point_x, point_y in points:
            commands.append(f"xdotool mousemove {point_x} {point_y}")
            if delay:
                commands.append(f"sleep {delay:.4f}")
        return "; ".join(commands)

    async def act(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action in {"move", "click", "double_click", "right_click"}:
            x, y = int(params["x"]), int(params["y"])
            script = await self._move_script(x, y, params.get("duration_ms"))
            if action != "move":
                button = 3 if action == "right_click" else int(params.get("button", 1))
                repeat = 2 if action == "double_click" else 1
                script += f"; xdotool click --clearmodifiers --repeat {repeat} --delay 120 {button}"
            await self._run(script)
            return {"x": x, "y": y, "action": action}
        if action == "drag":
            x1, y1, x2, y2 = (int(params[key]) for key in ("x1", "y1", "x2", "y2"))
            first = await self._move_script(x1, y1)
            points, duration = trajectory((x1, y1), (x2, y2), params.get("duration_ms"))
            delay = duration / max(1, len(points)) / 1000
            moves = "; ".join(f"xdotool mousemove {x} {y}; sleep {delay:.4f}" for x, y in points)
            button = int(params.get("button", 1))
            await self._run(f"{first}; xdotool mousedown {button}; {moves}; xdotool mouseup {button}")
            return {"from": [x1, y1], "to": [x2, y2]}
        if action == "scroll":
            direction = params.get("direction", "down")
            buttons = {"up": 4, "down": 5, "left": 6, "right": 7}
            if direction not in buttons:
                raise ActionError(f"invalid scroll direction: {direction}")
            prefix = ""
            if "x" in params and "y" in params:
                prefix = await self._move_script(int(params["x"]), int(params["y"])) + "; "
            amount = max(0, int(params.get("amount", 3)))
            await self._run(f"{prefix}xdotool click --repeat {amount} --delay 60 {buttons[direction]}")
            return {"direction": direction, "amount": amount}
        if action == "type":
            text = str(params.get("text", ""))
            await self._run(f"xdotool type --clearmodifiers --delay {int(params.get('delay_ms', 15))} {shlex.quote(text)}")
            return {"characters": len(text)}
        if action in {"key", "hotkey"}:
            keys = params.get("keys", params.get("key"))
            if isinstance(keys, str):
                keys = [keys]
            if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
                raise ActionError("key action requires a key string or list")
            await self._run("xdotool key --clearmodifiers " + " ".join(shlex.quote(key) for key in keys))
            return {"keys": keys}
        raise ActionError(f"unsupported X11 action: {action}")

    async def windows(self) -> list[dict[str, Any]]:
        output = (await self._run("wmctrl -lG")).decode(errors="replace")
        windows = []
        for line in output.splitlines():
            parts = line.split(None, 7)
            if len(parts) == 8:
                window_id, desktop, x, y, width, height, host, title = parts
                windows.append({"id": window_id, "desktop": int(desktop), "x": int(x), "y": int(y), "width": int(width), "height": int(height), "host": host, "title": title})
        return windows


def create(name: str, config: dict[str, Any], adapters: dict[str, Adapter]) -> Adapter:
    reference = str(config.get("ssh", "ssh"))
    ssh = adapters.get(reference)
    if not isinstance(ssh, SSHAdapter):
        raise ConfigError(f"x11 adapter requires SSH adapter {reference!r}")
    return X11Adapter(name, config, ssh)
