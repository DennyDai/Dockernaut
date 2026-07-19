from abc import ABC
from typing import Any

from ..errors import CapabilityError
from ..types import Capability, Frame


class Adapter(ABC):
    kind: str
    capabilities: frozenset[Capability] = frozenset()

    def __init__(self, name: str, config: dict[str, Any]):
        self.name = name
        self.config = config

    async def available(self) -> tuple[bool, str | None]:
        return True, None

    async def capture(self) -> Frame:
        raise CapabilityError(f"{self.kind} does not capture screens")

    async def act(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        raise CapabilityError(f"{self.kind} does not support {action}")

    async def shell(self, command: str, stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
        raise CapabilityError(f"{self.kind} does not provide a shell")

    async def browser(self, method: str, params: dict[str, Any]) -> Any:
        raise CapabilityError(f"{self.kind} does not control a browser")

    async def windows(self) -> list[dict[str, Any]]:
        raise CapabilityError(f"{self.kind} does not inspect windows")

    async def viewer(self) -> dict[str, Any]:
        raise CapabilityError(f"{self.kind} does not launch a viewer")

    async def close(self) -> None:
        return None
