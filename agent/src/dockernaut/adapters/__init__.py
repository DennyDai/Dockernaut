from importlib.metadata import entry_points
from typing import Any, Callable

from .base import Adapter

AdapterFactory = Callable[[str, dict[str, Any], dict[str, Adapter]], Adapter]


def factories() -> dict[str, AdapterFactory]:
    from .adb import create as adb
    from .cdp import create as cdp
    from .rdp import create as rdp
    from .ssh import create as ssh
    from .vnc import create as vnc
    from .x11 import create as x11

    result: dict[str, AdapterFactory] = {
        "adb": adb,
        "cdp": cdp,
        "rdp": rdp,
        "ssh": ssh,
        "vnc": vnc,
        "x11": x11,
    }
    for entry in entry_points(group="dockernaut.adapters"):
        result[entry.name] = entry.load()
    return result
