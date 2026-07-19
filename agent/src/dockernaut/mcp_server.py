import os
from typing import Any

from mcp.server.fastmcp import FastMCP, Image

from .controller import Controller
from .sequence import run_sequence

mcp = FastMCP("Dockernaut")
_controller: Controller | None = None


def controller() -> Controller:
    global _controller
    if _controller is None:
        _controller = Controller.from_path(os.environ.get("DOCKERNAUT_CONFIG"))
    return _controller


@mcp.tool()
async def dockernaut_targets() -> dict[str, Any]:
    """List configured targets, adapters, capabilities, and availability."""
    return await controller().targets()


@mcp.tool()
async def dockernaut_capture(target: str) -> Image:
    """Capture the best coherent visual surface for a target."""
    frame, _ = await controller().capture(target)
    return Image(data=frame.png, format="png")


@mcp.tool()
async def dockernaut_observe(target: str, ocr: bool = True) -> dict[str, Any]:
    """Capture target state with optional OCR and window metadata."""
    return await controller().observe(target, ocr)


@mcp.tool()
async def dockernaut_act(target: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Perform one pointer, keyboard, text-locator, wait, or observation action."""
    return await controller().act(target, action, params)


@mcp.tool()
async def dockernaut_run(
    target: str,
    steps: list[dict[str, Any]],
    on_error: str = "observe",
    observe_after: bool = False,
) -> dict[str, Any]:
    """Execute ordered actions locally without an agent round-trip between steps."""
    return await run_sequence(controller(), target, steps, on_error=on_error, observe_after=observe_after)


@mcp.tool()
async def dockernaut_shell(target: str, command: str) -> dict[str, Any]:
    """Execute a shell command through the best available shell adapter."""
    return await controller().shell(target, command)


@mcp.tool()
async def dockernaut_browser(target: str, method: str, params: dict[str, Any] | None = None) -> Any:
    """Call a Chrome DevTools Protocol method on the configured browser target."""
    return await controller().browser(target, method, params)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
