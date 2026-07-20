from importlib.metadata import entry_points
from typing import Any, Callable

from .base import Adapter

AdapterFactory = Callable[[str, dict[str, Any], dict[str, Adapter]], Adapter]


def factories() -> dict[str, AdapterFactory]:
    from .adb import create as adb
    from .atspi import create as atspi
    from .cdp import create as cdp
    from .rdp import create as rdp
    from .local import create as local
    from .ssh import create as ssh
    from .uia import create as uia
    from .vnc import create as vnc
    from .wayland import create as wayland
    from .x11 import create as x11

    result: dict[str, AdapterFactory] = {
        "adb": adb,
        "atspi": atspi,
        "cdp": cdp,
        "rdp": rdp,
        "local": local,
        "ssh": ssh,
        "uia": uia,
        "vnc": vnc,
        "x11": x11,
        "wayland": wayland,
    }
    for entry in entry_points(group="wayweaver.adapters"):
        result[entry.name] = entry.load()
    return result
