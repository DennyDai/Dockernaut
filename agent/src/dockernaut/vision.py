import asyncio
import csv
import io
import re
import shutil
from dataclasses import dataclass
from typing import Any

from .adapters.base import Adapter
from .errors import ActionError, CapabilityError
from .types import Frame


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    token: str
    confidence: float
    left: int
    top: int
    width: int
    height: int
    line: tuple[str, str, str, str]


def tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)


def parse_tsv(tsv: str) -> list[Word]:
    words = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t"):
        text = (row.get("text") or "").strip()
        if not text or row.get("level") != "5":
            continue
        try:
            base = {
                "confidence": float(row["conf"]),
                "left": int(row["left"]),
                "top": int(row["top"]),
                "width": int(row["width"]),
                "height": int(row["height"]),
                "line": (row["page_num"], row["block_num"], row["par_num"], row["line_num"]),
            }
            words.extend(Word(text, token, **base) for token in tokens(text))
        except (KeyError, TypeError, ValueError):
            continue
    return words


async def recognize(frame: Frame, shell: Adapter | None = None) -> list[Word]:
    if command := shutil.which("tesseract"):
        process = await asyncio.create_subprocess_exec(
            command, "stdin", "stdout", "tsv",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(frame.png)
        if process.returncode:
            raise ActionError(stderr.decode(errors="replace").strip())
        return parse_tsv(stdout.decode(errors="replace"))
    if shell:
        code, stdout, stderr = await shell.shell("tesseract stdin stdout tsv", frame.png)
        if code:
            raise ActionError(stderr.decode(errors="replace").strip())
        return parse_tsv(stdout.decode(errors="replace"))
    raise CapabilityError("OCR requires local tesseract or an SSH target with tesseract")


def find_text(words: list[Word], locator: str | dict[str, Any]) -> dict[str, Any]:
    options = {"text": locator} if isinstance(locator, str) else locator
    text = options.get("text")
    if not isinstance(text, str):
        raise ActionError("text locator requires text")
    wanted = tokens(text)
    if not wanted:
        raise ActionError("text locator is empty")
    contains = bool(options.get("contains", False))
    region = options.get("region")
    if region is not None:
        if not isinstance(region, list) or len(region) != 4:
            raise ActionError("region must be [left, top, right, bottom]")
        left_bound, top_bound, right_bound, bottom_bound = map(int, region)
        if right_bound <= left_bound or bottom_bound <= top_bound:
            raise ActionError("region right/bottom must exceed left/top")
    matches = []
    size = len(wanted)
    for index in range(len(words) - size + 1):
        group = words[index:index + size]
        if size > 1 and any(word.line != group[0].line for word in group[1:]):
            continue
        seen = [word.token for word in group]
        matched = all(target in value for target, value in zip(wanted, seen)) if contains else seen == wanted
        if not matched:
            continue
        left = min(word.left for word in group)
        top = min(word.top for word in group)
        right = max(word.left + word.width for word in group)
        bottom = max(word.top + word.height for word in group)
        x, y = round((left + right) / 2), round((top + bottom) / 2)
        matches.append({
            "text": " ".join(seen), "x": x, "y": y,
            "box": {"left": left, "top": top, "width": right - left, "height": bottom - top},
            "confidence": round(sum(word.confidence for word in group) / len(group), 1),
        })
    all_matches = len(matches)
    if region is not None:
        matches = [match for match in matches if left_bound <= match["x"] <= right_bound and top_bound <= match["y"] <= bottom_bound]
    nth = int(options.get("nth", 0))
    nth = nth if nth >= 0 else len(matches) + nth
    if not 0 <= nth < len(matches):
        raise ActionError(f"text not found: {text!r}; {len(matches)} regional matches, {all_matches} total")
    result = dict(matches[nth])
    result.update({"matches": len(matches), "total_matches": all_matches})
    if region is not None:
        result["region"] = list(map(int, region))
    return result


def text_output(words: list[Word]) -> str:
    lines: dict[tuple[str, str, str, str], list[str]] = {}
    for word in words:
        if not lines.get(word.line) or lines[word.line][-1] != word.text:
            lines.setdefault(word.line, []).append(word.text)
    return "\n".join(" ".join(line) for line in lines.values())
