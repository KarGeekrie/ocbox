"""Reads JSONC - JSON with // and /* */ comments and trailing commas.

opencode-config/opencode.jsonc is JSONC, and ocbox has to read it (the LLM's
address lives there). The standard library only parses strict JSON, and this
project takes no runtime dependencies, so comments and trailing commas are
removed first - without touching anything inside strings, where `//` is
ordinary text: every URL contains it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsoncError(ValueError):
    """Raised when a JSONC document can't be parsed."""


def _strip_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
        elif c == '"':
            in_string = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end  # keep the newline itself
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end == -1:
                raise JsoncError("unterminated /* comment")
            # Keep the line count, so JSON error positions still match the source.
            out.append("\n" * text.count("\n", i, end + 2))
            i = end + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
        elif c == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


def loads(text: str) -> Any:
    try:
        return json.loads(_strip_trailing_commas(_strip_comments(text)))
    except json.JSONDecodeError as exc:
        raise JsoncError(str(exc)) from exc


def load(path: Path) -> Any:
    return loads(Path(path).read_text())
