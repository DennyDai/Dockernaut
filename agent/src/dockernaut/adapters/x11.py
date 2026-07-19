import asyncio
import shlex
import time
from typing import Any

from ..errors import ActionError, ConfigError
from ..image import png_size
from ..motion import trajectory
from ..types import Capability, Frame
from .base import Adapter
from .ssh import SSHAdapter


class X11Adapter(Adapter):
    kind = "x11"
    capabilities = frozenset({
        Capability.APPLICATIONS,
        Capability.CAPTURE,
        Capability.KEYBOARD,
        Capability.POINTER,
        Capability.WINDOWS,
    })

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
            await self._run("command -v maim >/dev/null && command -v xdotool >/dev/null && command -v wmctrl >/dev/null")
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

    async def _window(self, params: dict[str, Any]) -> dict[str, Any]:
        windows = await self.windows()
        if identifier := params.get("id"):
            matches = [window for window in windows if window["id"].casefold() == str(identifier).casefold()]
        else:
            title = params.get("title")
            if not isinstance(title, str) or not title:
                raise ActionError("window action requires title or id")
            wanted = title.casefold()
            if params.get("exact"):
                matches = [window for window in windows if window["title"].casefold() == wanted]
            else:
                matches = [window for window in windows if wanted in window["title"].casefold()]
        nth = int(params.get("nth", 0))
        nth = nth if nth >= 0 else len(matches) + nth
        if not 0 <= nth < len(matches):
            raise ActionError(f"window not found: {params.get('title', params.get('id'))!r}")
        result = dict(matches[nth])
        result["matches"] = len(matches)
        return result

    async def _wait_window(self, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + max(0, timeout)
        while True:
            try:
                return await self._window(params)
            except ActionError:
                if time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(max(0.05, float(params.get("interval", 0.2))))

    async def act(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "launch":
            command = params.get("command")
            if not isinstance(command, str) or not command:
                raise ActionError("launch requires command")
            await self._run(f"nohup sh -lc {shlex.quote(command)} >/dev/null 2>&1 </dev/null &")
            return {"command": command}
        if action in {"wait_window", "assert_window"}:
            timeout = float(params.get("timeout", 3 if action == "wait_window" else 0))
            return await self._wait_window(params, timeout)
        if action in {"focus_window", "close_window", "move_window", "resize_window", "maximize_window", "restore_window"}:
            try:
                window = await self._window(params)
            except ActionError:
                if params.get("if_exists"):
                    return {"action": action, "window": None, "skipped": True}
                raise
            identifier = shlex.quote(window["id"])
            if action == "focus_window":
                command = f"wmctrl -ia {identifier}"
            elif action == "close_window":
                command = f"wmctrl -ic {identifier}"
            elif action in {"maximize_window", "restore_window"}:
                operation = "add" if action == "maximize_window" else "remove"
                command = f"wmctrl -ir {identifier} -b {operation},maximized_vert,maximized_horz"
            else:
                x = int(params.get("x", window["x"]))
                y = int(params.get("y", window["y"]))
                width = int(params.get("width", window["width"]))
                height = int(params.get("height", window["height"]))
                if action == "move_window":
                    width, height = window["width"], window["height"]
                else:
                    x, y = window["x"], window["y"]
                command = f"wmctrl -ir {identifier} -e 0,{x},{y},{width},{height}"
            await self._run(command)
            return {"action": action, "window": window}
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
        active_output = (await self._run("xdotool getactivewindow 2>/dev/null || true")).decode(errors="replace").strip()
        active = int(active_output) if active_output.isdigit() else None
        windows = []
        for line in output.splitlines():
            parts = line.split(None, 7)
            if len(parts) == 8:
                window_id, desktop, x, y, width, height, host, title = parts
                windows.append({
                    "id": window_id,
                    "desktop": int(desktop),
                    "x": int(x),
                    "y": int(y),
                    "width": int(width),
                    "height": int(height),
                    "host": host,
                    "title": title,
                    "active": active == int(window_id, 16),
                })
        return windows


def create(name: str, config: dict[str, Any], adapters: dict[str, Adapter]) -> Adapter:
    reference = str(config.get("ssh", "ssh"))
    ssh = adapters.get(reference)
    if not isinstance(ssh, SSHAdapter):
        raise ConfigError(f"x11 adapter requires SSH adapter {reference!r}")
    return X11Adapter(name, config, ssh)
