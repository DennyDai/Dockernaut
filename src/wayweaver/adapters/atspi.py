import asyncio
import json
import shlex
from typing import Any

from ..errors import ActionError, ConfigError
from ..runtime import linux_path_export
from ..types import Capability
from .base import Adapter, require_shell_transport


class ATSPIAdapter(Adapter):
    kind = "atspi"
    capabilities = frozenset({Capability.ELEMENTS})
    raw_operations = {"tree": "Return the bounded raw accessibility tree"}

    def __init__(self, name: str, config: dict[str, Any], transport: Adapter):
        super().__init__(name, config)
        self.transport = transport
        configured_display = config.get("display")
        self.display = (
            str(configured_display) if configured_display is not None else None
        )
        try:
            helper = shlex.split(str(config.get("command", "wayweaver-atspi")))
        except ValueError as error:
            raise ConfigError(f"invalid atspi command: {error}") from error
        if not helper:
            raise ConfigError("atspi command cannot be empty")
        self.helper_command = " ".join(shlex.quote(value) for value in helper)

    def _command(self, action: str) -> str:
        environment = linux_path_export()
        if self.display is not None:
            environment += f"export DISPLAY={shlex.quote(self.display)}; "
        return (
            f"{environment}export NO_AT_BRIDGE=0; "
            f"{self.helper_command} {shlex.quote(action)}"
        )

    async def _call(self, action: str, params: dict[str, Any] | None = None) -> Any:
        stdin = json.dumps(params or {}).encode() if params is not None else None
        code, stdout, stderr = await self.transport.shell(self._command(action), stdin)
        if code:
            message = stderr.decode(errors="replace").strip()
            try:
                message = json.loads(message.splitlines()[-1])["error"]
            except (IndexError, KeyError, TypeError, json.JSONDecodeError):
                pass
            raise ActionError(message or f"AT-SPI helper exited {code}")
        return json.loads(stdout)

    async def available(self) -> tuple[bool, str | None]:
        available, reason = await self.transport.available()
        if not available:
            return False, reason
        try:
            await self._call("probe")
            return True, None
        except Exception as error:
            return False, str(error)

    async def _wait(self, params: dict[str, Any]) -> Any:
        timeout = max(0.0, float(params.get("timeout", 5)))
        minimum_interval = max(0.0, float(self.config.get("wait_min_interval", 1)))
        interval = max(minimum_interval, float(params.get("interval", 1)))
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            try:
                return await self._call("assert", params)
            except ActionError as error:
                last_error = error
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise last_error
            await asyncio.sleep(min(interval, remaining))

    async def perform(self, operation: str, params: dict[str, Any]) -> Any:
        actions = {
            "element.list": "list",
            "element.find": "find",
            "element.assert": "assert",
            "element.activate": "invoke",
            "element.focus": "focus",
            "element.read": "read",
            "element.set_value": "set-value",
        }
        if operation == "element.wait":
            return await self._wait(params)
        if action := actions.get(operation):
            return await self._call(action, params)
        return await super().perform(operation, params)

    async def raw(self, operation: str, params: dict[str, Any]) -> Any:
        if operation != "tree":
            raise ActionError(f"unknown AT-SPI raw operation: {operation}")
        return await self._call("list", params)


def create(name: str, config: dict[str, Any], adapters: dict[str, Adapter]) -> Adapter:
    transport = require_shell_transport("atspi", config, adapters)
    return ATSPIAdapter(name, config, transport)
