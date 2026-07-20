import ast
import json
import re
import shlex
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from ..errors import ActionError

RunCommand = Callable[[str, bytes | None], Awaitable[bytes]]


class CompositorBackend(ABC):
    kind: str

    def __init__(self, run: RunCommand):
        self.run = run

    @abstractmethod
    async def probe(self) -> None: ...

    @abstractmethod
    async def windows(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def window_action(
        self, action: str, window: dict[str, Any], params: dict[str, Any]
    ) -> None: ...

    @abstractmethod
    async def workspaces(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def switch_workspace(self, value: str | int) -> None: ...


class SwayBackend(CompositorBackend):
    kind = "sway"

    async def probe(self) -> None:
        await self.run("swaymsg -r -t get_version >/dev/null", None)

    def _flatten(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        result = []
        if node.get("type") in {"con", "floating_con"} and node.get("name"):
            rectangle = node.get("rect", {})
            result.append(
                {
                    "id": str(node.get("id")),
                    "title": node.get("name", ""),
                    "class": (
                        node.get("app_id")
                        or node.get("window_properties", {}).get("class")
                        or ""
                    ),
                    "pid": node.get("pid"),
                    "desktop": node.get("workspace"),
                    "x": rectangle.get("x", 0),
                    "y": rectangle.get("y", 0),
                    "width": rectangle.get("width", 0),
                    "height": rectangle.get("height", 0),
                    "active": bool(node.get("focused")),
                }
            )
        for child in [*node.get("nodes", []), *node.get("floating_nodes", [])]:
            result.extend(self._flatten(child))
        return result

    async def windows(self) -> list[dict[str, Any]]:
        return self._flatten(json.loads(await self.run("swaymsg -r -t get_tree", None)))

    async def window_action(
        self, action: str, window: dict[str, Any], params: dict[str, Any]
    ) -> None:
        selector = f"'[con_id={window['id']}]'"
        if action == "focus_window":
            command = f"swaymsg {selector} focus"
        elif action == "close_window":
            command = f"swaymsg {selector} kill"
        elif action == "move_window":
            command = (
                f"swaymsg {selector} floating enable, "
                f"move position {int(params['x'])} {int(params['y'])}"
            )
        elif action == "resize_window":
            command = (
                f"swaymsg {selector} floating enable, "
                f"resize set width {int(params['width'])} px "
                f"height {int(params['height'])} px"
            )
        elif action == "minimize_window":
            command = f"swaymsg {selector} move scratchpad"
        elif action in {"maximize_window", "fullscreen_window"}:
            enabled = action == "maximize_window" or params.get("enabled", True)
            command = (
                f"swaymsg {selector} fullscreen {'enable' if enabled else 'disable'}"
            )
        elif action == "restore_window":
            command = f"swaymsg {selector} scratchpad show, fullscreen disable"
        else:
            return
        await self.run(command, None)

    async def workspaces(self) -> list[dict[str, Any]]:
        values = json.loads(await self.run("swaymsg -r -t get_workspaces", None))
        return [
            {
                "index": workspace.get("num"),
                "name": workspace.get("name", ""),
                "active": bool(workspace.get("focused")),
                "visible": bool(workspace.get("visible")),
                "output": workspace.get("output", ""),
                **workspace.get("rect", {}),
            }
            for workspace in values
        ]

    async def switch_workspace(self, value: str | int) -> None:
        await self.run("swaymsg workspace " + shlex.quote(str(value)), None)


class KDotoolBackend(CompositorBackend):
    kind = "kde"

    async def probe(self) -> None:
        await self.run("kdotool get_num_desktops >/dev/null", None)

    async def _text(self, command: str) -> str:
        return (await self.run(command, None)).decode(errors="replace").strip()

    async def windows(self) -> list[dict[str, Any]]:
        identifiers = (
            await self._text("kdotool search --name '.*' getwindowid %@")
        ).splitlines()
        active = await self._text("kdotool getactivewindow getwindowid")
        windows = []
        for identifier in identifiers:
            identifier = identifier.strip()
            if not identifier:
                continue
            quoted = shlex.quote(identifier)
            output = await self._text(
                " ".join(
                    [
                        "kdotool",
                        "getwindowname",
                        quoted,
                        "getwindowclassname",
                        quoted,
                        "getwindowpid",
                        quoted,
                        "getwindowgeometry",
                        quoted,
                        "get_desktop_for_window",
                        quoted,
                    ]
                )
            )
            lines = output.splitlines()
            if len(lines) < 7:
                continue
            position = re.search(r"Position:\s*(-?\d+),(-?\d+)", output)
            geometry = re.search(r"Geometry:\s*(\d+)x(\d+)", output)
            windows.append(
                {
                    "id": identifier,
                    "title": lines[0],
                    "class": lines[1],
                    "pid": int(lines[2]) if lines[2].isdigit() else None,
                    "desktop": int(lines[-1]) if lines[-1].isdigit() else lines[-1],
                    "x": int(position.group(1)) if position else 0,
                    "y": int(position.group(2)) if position else 0,
                    "width": int(geometry.group(1)) if geometry else 0,
                    "height": int(geometry.group(2)) if geometry else 0,
                    "active": identifier == active,
                }
            )
        return windows

    async def window_action(
        self, action: str, window: dict[str, Any], params: dict[str, Any]
    ) -> None:
        identifier = shlex.quote(window["id"])
        if action == "focus_window":
            command = f"kdotool windowactivate {identifier}"
        elif action == "close_window":
            command = f"kdotool windowclose {identifier}"
        elif action == "move_window":
            command = (
                f"kdotool windowmove {identifier} {int(params['x'])} {int(params['y'])}"
            )
        elif action == "resize_window":
            command = (
                f"kdotool windowsize {identifier} "
                f"{int(params['width'])} {int(params['height'])}"
            )
        elif action == "minimize_window":
            command = f"kdotool windowminimize {identifier}"
        elif action == "maximize_window":
            command = f"kdotool windowstate --add maximized {identifier}"
        elif action == "fullscreen_window":
            verb = "--add" if params.get("enabled", True) else "--remove"
            command = f"kdotool windowstate {verb} fullscreen {identifier}"
        elif action == "restore_window":
            command = (
                "kdotool windowstate --remove minimized --remove maximized "
                f"--remove fullscreen {identifier}"
            )
        else:
            return
        await self.run(command, None)

    async def workspaces(self) -> list[dict[str, Any]]:
        current = int(await self._text("kdotool get_desktop"))
        count = int(await self._text("kdotool get_num_desktops"))
        return [
            {
                "index": index,
                "name": f"Desktop {index}",
                "active": index == current,
            }
            for index in range(1, count + 1)
        ]

    async def switch_workspace(self, value: str | int) -> None:
        text = str(value)
        match = re.fullmatch(r"(?:Desktop\s+)?(\d+)", text, re.IGNORECASE)
        if not match:
            raise ActionError(f"invalid KDE desktop: {value!r}")
        await self.run(f"kdotool set_desktop {int(match.group(1))}", None)


class GnomeBackend(CompositorBackend):
    kind = "gnome"
    _prefix = (
        "gdbus call --session --dest org.wayweaver.Gnome "
        "--object-path /org/wayweaver/Gnome --method org.wayweaver.Gnome1."
    )

    async def _call(self, method: str, *arguments: str) -> Any:
        command = self._prefix + method
        if arguments:
            command += " " + " ".join(shlex.quote(value) for value in arguments)
        output = (await self.run(command, None)).decode(errors="replace").strip()
        try:
            values = ast.literal_eval(output)
            return json.loads(values[0])
        except (ValueError, SyntaxError, IndexError, json.JSONDecodeError) as error:
            raise ActionError(f"invalid GNOME bridge response: {output!r}") from error

    async def probe(self) -> None:
        result = await self._call("Ping")
        if not result.get("ok"):
            raise ActionError("GNOME bridge probe failed")

    async def windows(self) -> list[dict[str, Any]]:
        result = await self._call("ListWindows")
        return list(result.get("windows", []))

    async def window_action(
        self, action: str, window: dict[str, Any], params: dict[str, Any]
    ) -> None:
        await self._call(
            "WindowAction",
            window["id"],
            action,
            json.dumps(params, separators=(",", ":")),
        )

    async def workspaces(self) -> list[dict[str, Any]]:
        result = await self._call("ListWorkspaces")
        return list(result.get("workspaces", []))

    async def switch_workspace(self, value: str | int) -> None:
        await self._call("SwitchWorkspace", str(value))
