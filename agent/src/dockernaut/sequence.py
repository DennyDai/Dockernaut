import time
from typing import Any

from .controller import Controller


def normalize(step: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(step, dict):
        raise ValueError("each step must be an object")
    if "action" in step:
        action = str(step["action"])
        if set(step) == {"action", "params"}:
            params = step["params"]
            if not isinstance(params, dict):
                raise ValueError("step params must be an object")
            return action, dict(params)
        return action, {key: value for key, value in step.items() if key != "action"}
    if len(step) != 1:
        raise ValueError("each step must contain exactly one action")
    action, value = next(iter(step.items()))
    if action in {"move", "click", "double_click", "right_click"}:
        if not isinstance(value, list) or len(value) < 2:
            raise ValueError(f"{action} expects [x, y]")
        params = {"x": value[0], "y": value[1]}
        if len(value) > 2:
            params["button"] = value[2]
        return action, params
    if action == "drag":
        if not isinstance(value, list) or len(value) != 4:
            raise ValueError("drag expects [x1, y1, x2, y2]")
        return action, dict(zip(("x1", "y1", "x2", "y2"), value))
    if action == "type":
        return action, {"text": value}
    if action in {"key", "hotkey"}:
        return action, {"keys": value}
    if action == "wait":
        return action, {"seconds": value}
    if action in {"click_text", "click_element", "assert_text", "wait_text"}:
        return action, {"text": value} if isinstance(value, str) else dict(value)
    if action == "scroll":
        return action, {"direction": value} if isinstance(value, str) else dict(value)
    if action in {"observe", "screenshot", "clear", "viewer"}:
        return action, {} if value is True or value is None else dict(value)
    return action, {} if value is None else dict(value)


async def run_sequence(
    controller: Controller,
    target: str,
    steps: list[dict[str, Any]],
    *,
    on_error: str = "observe",
    observe_after: bool = False,
) -> dict[str, Any]:
    completed = []
    for index, step in enumerate(steps):
        started = time.monotonic()
        try:
            action, params = normalize(step)
            result = await controller.act(target, action, params)
            completed.append({
                "step": index,
                "action": action,
                "result": result,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            })
        except Exception as error:
            output: dict[str, Any] = {
                "ok": False,
                "failed_step": index,
                "step": step,
                "error": {"type": type(error).__name__, "message": str(error)},
                "completed": completed,
            }
            if on_error == "observe":
                try:
                    output["observation"] = await controller.observe(target, True)
                except Exception as observation_error:
                    output["observation_error"] = str(observation_error)
            return output
    output = {"ok": True, "completed": completed}
    if observe_after:
        output["observation"] = await controller.observe(target, True)
    return output
