import asyncio
import time
from pathlib import Path
from typing import Any

from .config import Config, load_config
from .errors import ActionError, CapabilityError
from .router import Router
from .types import Capability, Frame
from .vision import find_text, recognize, text_output

_POINTER_ACTIONS = {"move", "click", "double_click", "right_click", "drag", "scroll"}
_KEYBOARD_ACTIONS = {"type", "key", "hotkey"}


class Controller:
    def __init__(self, config: Config):
        self.config = config
        self.routers: dict[str, Router] = {}

    @classmethod
    def from_path(cls, path: str | Path | None = None) -> "Controller":
        return cls(load_config(path))

    def router(self, target: str) -> Router:
        if target not in self.routers:
            self.routers[target] = Router(self.config.target(target))
        return self.routers[target]

    async def targets(self) -> dict[str, Any]:
        result = {}
        for name in self.config.targets:
            status = await self.router(name).probe()
            result[name] = {
                "adapters": {
                    adapter_name: {
                        "kind": item.kind,
                        "capabilities": list(item.capabilities),
                        "available": item.available,
                        "reason": item.reason,
                    }
                    for adapter_name, item in status.items()
                }
            }
        return result

    async def capture(self, target: str) -> tuple[Frame, str]:
        adapter = await self.router(target).select(Capability.CAPTURE)
        return await adapter.capture(), adapter.name

    async def _ocr(self, target: str, frame: Frame):
        shell = None
        try:
            shell = await self.router(target).select(Capability.SHELL)
        except CapabilityError:
            pass
        return await recognize(frame, shell)

    async def observe(self, target: str, ocr: bool = False) -> dict[str, Any]:
        frame, adapter_name = await self.capture(target)
        path = self.config.cache_dir / target / "current.png"
        frame.save(path)
        result: dict[str, Any] = {
            "target": target,
            "adapter": adapter_name,
            "screenshot": str(path),
            "screen": {"width": frame.width, "height": frame.height},
        }
        router = self.router(target)
        try:
            windows_adapter = await router.select(Capability.WINDOWS)
            result["windows"] = await windows_adapter.windows()
        except CapabilityError:
            pass
        if ocr:
            words = await self._ocr(target, frame)
            result["ocr"] = text_output(words)
        return result

    async def locate(self, target: str, locator: str | dict[str, Any], click: bool = False) -> dict[str, Any]:
        options = {"text": locator} if isinstance(locator, str) else dict(locator)
        timeout = float(options.pop("timeout", 3))
        interval = float(options.pop("interval", 0.25))
        desktop = await self.router(target).select({Capability.CAPTURE, Capability.POINTER} if click else Capability.CAPTURE)
        deadline = time.monotonic() + max(0, timeout)
        last_error: Exception | None = None
        while True:
            frame = await desktop.capture()
            frame.save(self.config.cache_dir / target / "current.png")
            words = await self._ocr(target, frame)
            try:
                match = find_text(words, options)
                if click:
                    action = "right_click" if int(options.get("button", 1)) == 3 else "click"
                    await desktop.act(action, {"x": match["x"], "y": match["y"], "button": options.get("button", 1)})
                return match
            except ActionError as error:
                last_error = error
            if time.monotonic() >= deadline:
                raise ActionError(str(last_error))
            await asyncio.sleep(max(0.05, interval))

    async def act(self, target: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        if action in {"click_text", "click_element"}:
            return await self.locate(target, params, True)
        if action in {"assert_text", "wait_text"}:
            return await self.locate(target, params, False)
        if action in _POINTER_ACTIONS:
            adapter = await self.router(target).select(Capability.POINTER)
            return await adapter.act(action, params)
        if action in _KEYBOARD_ACTIONS:
            adapter = await self.router(target).select(Capability.KEYBOARD)
            return await adapter.act(action, params)
        if action == "wait":
            seconds = float(params.get("seconds", params.get("value", 0)))
            if seconds < 0:
                raise ActionError("wait cannot be negative")
            await asyncio.sleep(seconds)
            return {"seconds": seconds}
        if action == "observe":
            return await self.observe(target, bool(params.get("ocr", False)))
        if action == "viewer":
            adapter = await self.router(target).select(Capability.VIEWER)
            return await adapter.viewer()
        if action == "screenshot":
            frame, adapter = await self.capture(target)
            path = Path(params.get("path", self.config.cache_dir / target / "capture.png")).expanduser()
            frame.save(path)
            return {"path": str(path), "adapter": adapter, "width": frame.width, "height": frame.height}
        if action == "clear":
            directory = self.config.cache_dir / target
            removed = []
            if directory.is_dir():
                for item in directory.iterdir():
                    if item.is_file():
                        item.unlink()
                        removed.append(str(item))
            return {"removed": removed}
        raise ActionError(f"unknown action: {action}")

    async def shell(self, target: str, command: str, stdin: bytes | None = None) -> dict[str, Any]:
        adapter = await self.router(target).select(Capability.SHELL)
        code, stdout, stderr = await adapter.shell(command, stdin)
        return {
            "adapter": adapter.name,
            "exit_code": code,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
        }

    async def browser(self, target: str, method: str, params: dict[str, Any] | None = None) -> Any:
        adapter = await self.router(target).select(Capability.BROWSER)
        return await adapter.browser(method, params or {})

    async def close(self) -> None:
        for router in self.routers.values():
            await router.close()
