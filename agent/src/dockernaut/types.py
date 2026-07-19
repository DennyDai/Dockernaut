from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Capability(StrEnum):
    SHELL = "shell"
    CAPTURE = "capture"
    POINTER = "pointer"
    KEYBOARD = "keyboard"
    WINDOWS = "windows"
    BROWSER = "browser"
    VIEWER = "viewer"


@dataclass(frozen=True, slots=True)
class Frame:
    png: bytes
    width: int
    height: int
    source: str

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.png)
        return path
