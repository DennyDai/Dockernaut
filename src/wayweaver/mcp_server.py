import os
from typing import Any

from mcp.server.fastmcp import FastMCP, Image

from .controller import Controller
from .sequence import run_sequence
from .errors import error_payload
from .operations import API_VERSION

mcp = FastMCP("Wayweaver")
_controller: Controller | None = None


def controller() -> Controller:
    global _controller
    if _controller is None:
        _controller = Controller.from_path(os.environ.get("WAYWEAVER_CONFIG"))
    return _controller


@mcp.tool()
async def wayweaver_targets() -> dict[str, Any]:
    """List configured targets, adapters, capabilities, and availability."""
    return await controller().targets()


@mcp.tool()
async def wayweaver_capture(
    target: str,
    region: list[int] | None = None,
    window: str | None = None,
) -> Image:
    """Capture the best coherent surface, optionally constrained to a native region or window title."""
    params = {
        key: value
        for key, value in {"region": region, "window": window}.items()
        if value is not None
    }
    frame, _ = await controller().capture(target, params)
    return Image(data=frame.png, format="png")


@mcp.tool()
async def wayweaver_observe(target: str, ocr: bool = True) -> dict[str, Any]:
    """Capture target state with optional OCR and window metadata."""
    return await controller().observe(target, ocr)


@mcp.tool()
async def wayweaver_operations(
    target: str, include_raw: bool = False
) -> dict[str, Any]:
    """List only operations supported by currently available adapters; optionally reveal raw escape hatches."""
    return await controller().operations(target, include_raw)


@mcp.tool()
async def wayweaver_do(
    target: str, operation: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Perform one versioned operation through the best semantic or fallback adapter."""
    try:
        return await controller().perform(target, operation, params)
    except Exception as error:
        return {
            "api_version": API_VERSION,
            "ok": False,
            "operation": operation,
            "error": error_payload(error),
        }


@mcp.tool()
async def wayweaver_run(
    target: str,
    steps: list[dict[str, Any]],
    on_error: str = "observe",
    observe_after: bool = False,
    saved_output_limit: int = 32_768,
) -> dict[str, Any]:
    """Execute ordered actions locally without an agent round-trip between steps."""
    return await run_sequence(
        controller(),
        target,
        steps,
        on_error=on_error,
        observe_after=observe_after,
        saved_output_limit=saved_output_limit,
    )


@mcp.tool()
async def wayweaver_raw(
    target: str,
    adapter: str,
    operation: str,
    params: dict[str, Any] | None = None,
) -> Any:
    """Use an explicitly discovered adapter-specific raw operation as a last resort."""
    return await controller().raw(target, adapter, operation, params)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
