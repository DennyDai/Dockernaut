from abc import ABC
from typing import Any

from ..errors import ActionError, CapabilityError, ConfigError
from ..operations import OPERATIONS
from ..types import Capability, Frame


class Adapter(ABC):
    kind: str
    capabilities: frozenset[Capability] = frozenset()
    raw_operations: dict[str, str] = {}

    def __init__(self, name: str, config: dict[str, Any]):
        self.name = name
        self.config = config

    async def available(self) -> tuple[bool, str | None]:
        return True, None

    async def surface_session(self) -> str:
        return str(self.config.get("session_id", f"{self.kind}:{self.name}"))

    async def capture(self, params: dict[str, Any] | None = None) -> Frame:
        raise CapabilityError(f"{self.kind} does not capture screens")

    async def act(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        raise CapabilityError(f"{self.kind} does not support {action}")

    async def shell(
        self, command: str, stdin: bytes | None = None
    ) -> tuple[int, bytes, bytes]:
        raise CapabilityError(f"{self.kind} does not provide a shell")

    async def browser(self, method: str, params: dict[str, Any]) -> Any:
        raise CapabilityError(f"{self.kind} does not control a browser")

    async def windows(self) -> list[dict[str, Any]]:
        raise CapabilityError(f"{self.kind} does not inspect windows")

    async def viewer(self) -> dict[str, Any]:
        raise CapabilityError(f"{self.kind} does not launch a viewer")

    async def perform(self, operation: str, params: dict[str, Any]) -> Any:
        if operation == "pointer.click":
            button = int(params.get("button", 1))
            count = int(params.get("count", 1))
            if count == 2 and button == 1:
                return await self.act("double_click", params)
            action = "right_click" if button == 3 else "click"
            result = None
            for _ in range(count):
                result = await self.act(action, params)
            return result
        spec = OPERATIONS.get(operation)
        if spec and spec.action:
            return await self.act(spec.action, params)
        if operation == "window.list":
            return {"windows": await self.windows()}
        if operation == "shell.execute":
            stdin = params.get("stdin")
            code, stdout, stderr = await self.shell(
                str(params["command"]),
                stdin.encode() if isinstance(stdin, str) else stdin,
            )
            allowed = params.get("allowed_exit_codes", [0])
            success = code in allowed
            if params.get("check") and not success:
                raise ActionError(
                    f"shell command exited {code}",
                    details={
                        "exit_code": code,
                        "allowed_exit_codes": allowed,
                    },
                )
            return {
                "exit_code": code,
                "success": success,
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
            }
        if operation == "viewer.open":
            return await self.viewer()
        raise CapabilityError(f"{self.kind} does not perform {operation}")

    async def raw(self, operation: str, params: dict[str, Any]) -> Any:
        raise CapabilityError(f"{self.kind} does not expose raw operation {operation}")

    async def close(self) -> None:
        return None


def require_shell_transport(
    owner: str,
    config: dict[str, Any],
    adapters: dict[str, Adapter],
) -> Adapter:
    reference = config.get("transport")
    if not isinstance(reference, str) or not reference:
        raise ConfigError(f"{owner} adapter requires a transport name")
    transport = adapters.get(reference)
    if transport is None or Capability.SHELL not in transport.capabilities:
        raise ConfigError(
            f"{owner} adapter requires shell-capable transport {reference!r}"
        )
    return transport
