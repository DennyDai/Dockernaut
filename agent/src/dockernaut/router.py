import asyncio
import time
from dataclasses import dataclass
from typing import Iterable

from .adapters import factories
from .adapters.base import Adapter
from .config import TargetConfig
from .errors import CapabilityError, ConfigError
from .types import Capability


@dataclass(frozen=True, slots=True)
class AdapterStatus:
    name: str
    kind: str
    capabilities: tuple[str, ...]
    available: bool
    reason: str | None


class Router:
    def __init__(self, target: TargetConfig):
        self.target = target
        self.adapters = self._create_adapters()
        self.status: dict[str, AdapterStatus] = {}
        self.probed_at = 0.0

    def _create_adapters(self) -> dict[str, Adapter]:
        known = factories()
        adapters: dict[str, Adapter] = {}
        pending = dict(self.target.adapters)
        errors: dict[str, Exception] = {}
        while pending:
            progressed = False
            for name, config in tuple(pending.items()):
                kind = str(config.get("kind", name))
                factory = known.get(kind)
                if not factory:
                    raise ConfigError(f"unknown adapter kind {kind!r} on target {self.target.name}")
                try:
                    adapters[name] = factory(name, config, adapters)
                except ConfigError as error:
                    errors[name] = error
                    continue
                del pending[name]
                errors.pop(name, None)
                progressed = True
            if not progressed:
                detail = "; ".join(str(error) for error in errors.values())
                raise ConfigError(detail or f"cannot construct adapters for {self.target.name}")
        return adapters

    async def probe(self) -> dict[str, AdapterStatus]:
        names = list(self.adapters)
        results = await asyncio.gather(*(self.adapters[name].available() for name in names))
        status = {}
        for name, (available, reason) in zip(names, results):
            adapter = self.adapters[name]
            status[name] = AdapterStatus(
                name, adapter.kind,
                tuple(sorted(capability.value for capability in adapter.capabilities)),
                available, reason,
            )
        self.status = status
        self.probed_at = time.monotonic()
        return status

    def _ordered(self) -> list[Adapter]:
        preferred = list(self.target.prefer)
        rank = {value: index for index, value in enumerate(preferred)}
        return sorted(
            self.adapters.values(),
            key=lambda adapter: min(rank.get(adapter.name, len(rank)), rank.get(adapter.kind, len(rank))),
        )

    async def select(self, required: Capability | Iterable[Capability]) -> Adapter:
        requirements = {required} if isinstance(required, Capability) else set(required)
        if not self.status or time.monotonic() - self.probed_at > 5:
            await self.probe()
        for adapter in self._ordered():
            status = self.status[adapter.name]
            if status.available and requirements <= adapter.capabilities:
                return adapter
        names = ", ".join(sorted(capability.value for capability in requirements))
        reasons = "; ".join(f"{item.name}: {item.reason}" for item in self.status.values() if item.reason)
        raise CapabilityError(f"target {self.target.name} lacks [{names}]" + (f" ({reasons})" if reasons else ""))

    async def close(self) -> None:
        for adapter in self.adapters.values():
            await adapter.close()
