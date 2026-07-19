import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .controller import Controller
from .sequence import run_sequence


def load_json(value: str) -> Any:
    if value == "-":
        return json.load(sys.stdin)
    try:
        path = Path(value)
        if path.is_file():
            return json.loads(path.read_text())
    except OSError:
        pass
    return json.loads(value)


async def execute(args: argparse.Namespace) -> Any:
    controller = Controller.from_path(args.config)
    try:
        if args.command == "targets":
            return await controller.targets()
        if args.command == "observe":
            return await controller.observe(args.target, args.ocr)
        if args.command == "capture":
            frame, adapter = await controller.capture(args.target)
            output = frame.save(Path(args.output).expanduser())
            return {"output": str(output), "adapter": adapter, "width": frame.width, "height": frame.height}
        if args.command == "act":
            return await controller.act(args.target, args.action, load_json(args.params))
        if args.command == "run":
            payload = load_json(args.sequence)
            if isinstance(payload, list):
                steps, options = payload, {}
            else:
                steps, options = payload["steps"], payload
            return await run_sequence(
                controller, args.target, steps,
                on_error=options.get("on_error", "observe"),
                observe_after=bool(options.get("observe_after", False)),
            )
        if args.command == "shell":
            return await controller.shell(args.target, args.shell_command)
        if args.command == "browser":
            return await controller.browser(args.target, args.method, load_json(args.params))
        raise ValueError(f"unknown command: {args.command}")
    finally:
        await controller.close()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="dockernaut")
    root.add_argument("--config")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("targets")

    observe = commands.add_parser("observe")
    observe.add_argument("target")
    observe.add_argument("--ocr", action="store_true")

    capture = commands.add_parser("capture")
    capture.add_argument("target")
    capture.add_argument("output")

    act = commands.add_parser("act")
    act.add_argument("target")
    act.add_argument("action")
    act.add_argument("params", nargs="?", default="{}")

    run = commands.add_parser("run")
    run.add_argument("target")
    run.add_argument("sequence", help="inline JSON, a JSON file, or - for stdin")

    shell = commands.add_parser("shell")
    shell.add_argument("target")
    shell.add_argument("shell_command")

    browser = commands.add_parser("browser")
    browser.add_argument("target")
    browser.add_argument("method")
    browser.add_argument("params", nargs="?", default="{}")
    return root


def main() -> None:
    args = parser().parse_args()
    try:
        result = asyncio.run(execute(args))
    except Exception as error:
        print(json.dumps({"ok": False, "error": {"type": type(error).__name__, "message": str(error)}}), file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
