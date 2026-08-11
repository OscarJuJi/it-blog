"""Parsing of the metadata block that opens every post file.

A post begins with a block delimited by ``---`` lines::

    ---
    title: Hello world
    date: 2026-08-01
    tags:
      - python
      - notes
    ---

    The body, in Markdown.

The value syntax is a deliberately small subset of YAML: scalars, flow lists
(``[a, b]``) and block lists. That covers everything this blog writes, by hand
and through the CMS, and a small grammar keeps the failure modes obvious.

Everything comes back as strings or lists of strings; interpreting a value as a
date or anything else is the caller's job.
"""

from __future__ import annotations

import re

DELIMITER = "---"

_KEY = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*):(?P<value>.*)$")


class FrontmatterError(ValueError):
    """Raised when a document carries no well-formed metadata block."""


def split(text: str) -> tuple[dict[str, object], str]:
    """Return the metadata mapping and the body of *text*."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    opening = 0
    while opening < len(lines) and not lines[opening].strip():
        opening += 1
    if opening >= len(lines) or lines[opening].strip() != DELIMITER:
        raise FrontmatterError("the document does not open with a '---' metadata block")

    closing = None
    for index in range(opening + 1, len(lines)):
        if lines[index].strip() == DELIMITER:
            closing = index
            break
    if closing is None:
        raise FrontmatterError("the metadata block is never closed with '---'")

    metadata = _parse(lines[opening + 1 : closing])
    body = "\n".join(lines[closing + 1 :]).strip("\n")
    return metadata, body


def _parse(lines: list[str]) -> dict[str, object]:
    metadata: dict[str, object] = {}
    listed: set[str] = set()
    open_key: str | None = None

    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- "):
            if open_key is None:
                raise FrontmatterError(f"line {number}: list item belongs to no key")
            metadata[open_key].append(_scalar(stripped[2:]))  # type: ignore[union-attr]
            listed.add(open_key)
            continue

        match = _KEY.match(line)
        if match is None:
            raise FrontmatterError(f"line {number}: not a 'key: value' pair: {line!r}")

        key = match.group("key")
        if key in metadata:
            raise FrontmatterError(f"line {number}: duplicate key {key!r}")
        raw = match.group("value").strip()

        if not raw:
            # Either a block list follows, or the value is simply empty. Which
            # one it was is settled once the whole block has been read.
            metadata[key] = []
            open_key = key
        elif raw.startswith("[") and raw.endswith("]"):
            metadata[key] = [_scalar(item) for item in raw[1:-1].split(",") if item.strip()]
            open_key = None
        else:
            metadata[key] = _scalar(raw)
            open_key = None

    for key, value in metadata.items():
        if value == [] and key not in listed:
            metadata[key] = ""
    return metadata


def quote(value: str) -> str:
    """Write *value* so that :func:`split` reads it back as one scalar.

    The inverse of :func:`_scalar`, and it lives here for that reason: a writer
    that lived beside its caller drifted from this parser and shipped `\\"` into
    a published page, because the grammar below has no escapes to drift towards.

    So there is nothing to escape *with*, and three characters are removed
    instead of escaped:

    * newlines and runs of whitespace collapse, because a second line inside the
      block is a second metadata key and takes the build down with it;
    * a double quote becomes a single one, which nobody can tell apart at the
      size these values are displayed;
    * a backslash goes altogether. Not for this parser -- it would read one back
      happily -- but for Sveltia, which parses the same file as real YAML where
      a backslash opens an escape: `"a \\"` never finds its closing quote and
      `"C:\\Users"` is an unknown escape, and either one leaves the CMS unable
      to open a post the site renders perfectly well.
    """
    collapsed = " ".join(str(value).split())
    return '"{}"'.format(collapsed.replace("\\", "").replace('"', "'"))


def _scalar(raw: str) -> str:
    """Strip surrounding whitespace and one layer of matching quotes.

    An unquoted ``#`` is kept: titles such as "C# in 2026" are more likely than
    trailing comments on a value.
    """
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value
