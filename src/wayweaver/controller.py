import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any

from .config import Config, load_config
from .contracts import prepare_params, validate_params, validate_result
from .errors import ActionError, CapabilityError, ContractError, SurfaceError
from .operations import API_VERSION, OPERATIONS
from .provenance import ProvenanceStore
from .router import Router
from .runtime.deploy import manage_runtime
from .types import Capability, Frame
from .vision import find_text, recognize, text_output


class Controller:
    def __init__(self, config: Config):
        self.config = config
        self.routers: dict[str, Router] = {}
        self.observations: dict[str, dict[str, Any]] = {}
        self.provenance = ProvenanceStore(config.cache_dir)

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

    async def capture(
        self, target: str, params: dict[str, Any] | None = None
    ) -> tuple[Frame, str]:
        adapter = await self.router(target).select(Capability.CAPTURE)
        return await adapter.capture(params), adapter.name

    async def _ocr(self, target: str, frame: Frame, psm: int | None = None):
        shell = None
        try:
            shell = await self.router(target).select(Capability.SHELL)
        except CapabilityError:
            pass
        return await recognize(frame, shell, psm)

    async def observe(self, target: str, ocr: bool = False) -> dict[str, Any]:
        frame, adapter_name = await self.capture(target)
        path = self.config.cache_dir / target / "current.png"
        frame.save(path)
        adapter = self.router(target).adapters[adapter_name]
        space = "viewport" if adapter.kind == "cdp" else "screen"
        session_id = hashlib.sha256(
            (await adapter.surface_session()).encode()
        ).hexdigest()[:24]
        surface_id = self.provenance.issue(
            "surface",
            {
                "target": target,
                "adapter": adapter_name,
                "adapter_kind": adapter.kind,
                "source": frame.source,
                "space": space,
                "session_id": session_id,
                "width": frame.width,
                "height": frame.height,
                "scale": 1.0,
            },
        )
        observation_id = self.provenance.issue(
            "observation",
            {"target": target, "surface_id": surface_id},
        )
        surface = {
            "id": surface_id,
            "session_id": session_id,
            "adapter": adapter_name,
            "source": frame.source,
            "space": space,
            "width": frame.width,
            "height": frame.height,
            "scale": 1.0,
        }
        result: dict[str, Any] = {
            "observation_id": observation_id,
            "target": target,
            "surface": surface,
            "screenshot": str(path),
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
        self.observations[target] = {
            "observation_id": observation_id,
            "surface": surface,
        }
        self.provenance.remember(target, observation_id, surface_id)
        return result

    async def locate(
        self, target: str, locator: str | dict[str, Any], click: bool = False
    ) -> dict[str, Any]:
        options = {"text": locator} if isinstance(locator, str) else dict(locator)
        timeout = float(options.pop("timeout", 3))
        interval = float(options.pop("interval", 0.25))
        desktop = await self.router(target).select(
            {Capability.CAPTURE, Capability.POINTER} if click else Capability.CAPTURE
        )
        deadline = time.monotonic() + max(0, timeout)
        last_error: Exception | None = None
        while True:
            frame = await desktop.capture()
            frame.save(self.config.cache_dir / target / "current.png")
            attempts = [(None, options)]
            if options.get("region") is not None:
                regional = dict(options)
                regional.setdefault("fuzzy", True)
                attempts.append((6, regional))
            for psm, locator_options in attempts:
                words = await self._ocr(target, frame, psm)
                try:
                    match = find_text(words, locator_options)
                    match["ocr_psm"] = psm or "auto"
                    if click:
                        action = (
                            "right_click"
                            if int(options.get("button", 1)) == 3
                            else "click"
                        )
                        await desktop.act(
                            action,
                            {
                                "x": match["x"],
                                "y": match["y"],
                                "button": options.get("button", 1),
                            },
                        )
                    return match
                except ActionError as error:
                    last_error = error
            if time.monotonic() >= deadline:
                raise ActionError(str(last_error))
            await asyncio.sleep(max(0.05, interval))

    async def _validate_surface(
        self,
        target: str,
        operation: str,
        params: dict[str, Any],
        adapter_name: str,
        adapter_kind: str,
    ) -> None:
        if not operation.startswith("pointer."):
            return
        expected_space = "viewport" if adapter_kind == "cdp" else "screen"
        space = params["space"]
        if space not in {expected_space, "surface"}:
            raise SurfaceError(
                f"{operation} uses {space!r} coordinates on a {expected_space!r} surface",
                details={"expected_space": expected_space, "actual_space": space},
            )
        observation_id = params.get("observation_id")
        surface_id = params.get("surface_id")
        if space == "surface" and not surface_id:
            raise ContractError(
                f"{operation} requires surface_id when space is 'surface'",
                details={"operation": operation},
            )
        if observation_id:
            observation = self.provenance.verify(observation_id, "observation")
            if observation.get("target") != target:
                raise SurfaceError(
                    f"{operation} references an observation from another target",
                    details={"target": target},
                )
            observed_surface_id = observation.get("surface_id")
            if surface_id and surface_id != observed_surface_id:
                raise SurfaceError(
                    f"{operation} mixes unrelated observation and surface tokens"
                )
            surface_id = str(observed_surface_id)
            latest = self.provenance.latest(target)
            if latest is None or latest["observation_id"] != observation_id:
                raise SurfaceError(
                    f"{operation} references a stale observation",
                    details={
                        "observation_id": observation_id,
                        "latest_observation_id": (
                            latest["observation_id"] if latest else None
                        ),
                    },
                )
        if not surface_id:
            return
        surface = self.provenance.verify(surface_id, "surface")
        if (
            surface.get("target") != target
            or surface.get("adapter") != adapter_name
            or surface.get("adapter_kind") != adapter_kind
            or surface.get("space") != expected_space
        ):
            raise SurfaceError(
                f"{operation} references a different control surface",
                details={
                    "target": target,
                    "adapter": adapter_name,
                    "space": expected_space,
                },
            )
        adapter = self.router(target).adapters[adapter_name]
        session_id = hashlib.sha256(
            (await adapter.surface_session()).encode()
        ).hexdigest()[:24]
        if surface.get("session_id") != session_id:
            raise SurfaceError(
                f"{operation} references a replaced desktop session",
                details={
                    "expected_session_id": session_id,
                    "actual_session_id": surface.get("session_id"),
                },
            )

    async def operations(
        self, target: str, include_raw: bool = False
    ) -> dict[str, Any]:
        return await self.router(target).operation_routes(include_raw)

    async def perform(
        self, target: str, operation: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        started = time.monotonic()
        spec = OPERATIONS.get(operation)
        if spec is None:
            raise ContractError(
                f"unknown operation: {operation}",
                details={"operation": operation},
            )
        validated = validate_params(operation, spec.params_schema, params or {})
        fallback = False
        fallback_reason = None
        if operation == "time.sleep":
            await asyncio.sleep(validated["duration_ms"] / 1000)
            adapter_name, adapter_kind = "controller", "control"
            result = {"duration_ms": validated["duration_ms"]}
        else:
            router = self.router(target)
            adapter, fallback = await router.select_operation(operation)
            adapter_name, adapter_kind = adapter.name, adapter.kind
            await self._validate_surface(
                target, operation, validated, adapter_name, adapter_kind
            )
            prepared = prepare_params(operation, validated)
            if operation == "screen.observe":
                result = await self.observe(target, bool(prepared.get("ocr", False)))
            elif operation in {"element.find", "element.activate"} and fallback:
                locator = dict(prepared)
                if "name" in locator and "text" not in locator:
                    locator["text"] = locator.pop("name")
                result = await self.locate(
                    target, locator, operation == "element.activate"
                )
            else:
                try:
                    result = await adapter.perform(operation, prepared)
                except ActionError as error:
                    if operation not in {"element.find", "element.activate"}:
                        raise
                    fallback_adapter = await router.select_fallback(
                        operation, {adapter.name}
                    )
                    locator = dict(prepared)
                    if "name" in locator and "text" not in locator:
                        locator["text"] = locator.pop("name")
                    result = await self.locate(
                        target, locator, operation == "element.activate"
                    )
                    adapter_name = fallback_adapter.name
                    adapter_kind = fallback_adapter.kind
                    fallback = True
                    fallback_reason = str(error)
        validate_result(operation, spec.result_schema, result)
        backend = {
            "adapter": adapter_name,
            "kind": adapter_kind,
            "fallback": fallback,
        }
        if fallback_reason:
            backend["fallback_reason"] = fallback_reason
        return {
            "api_version": API_VERSION,
            "ok": True,
            "operation": operation,
            "backend": backend,
            "data": result,
            "timing": {
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            },
        }

    async def runtime(
        self,
        target: str,
        action: str,
        platform: str,
        transport: str | None = None,
    ) -> dict[str, Any]:
        router = self.router(target)
        if transport is None:
            selected = await router.select(Capability.SHELL)
        else:
            selected = router.adapters.get(transport)
            if selected is None or Capability.SHELL not in selected.capabilities:
                raise CapabilityError(
                    f"target {target} has no shell transport {transport!r}"
                )
        return await manage_runtime(selected, action, platform)

    async def raw(
        self,
        target: str,
        adapter: str,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return await self.router(target).raw(adapter, operation, params or {})

    async def close(self) -> None:
        for router in self.routers.values():
            await router.close()
