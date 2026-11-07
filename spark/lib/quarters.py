"""Quarter labels for Spark jobs: '2026q3', lists, and ranges such as '2009q2..2026q3'."""

from __future__ import annotations

import re

_QUARTER = re.compile(r"^(\d{4})q([1-4])$")


def _parse(label: str) -> tuple[int, int]:
    match = _QUARTER.match(label)
    if match is None:
        raise ValueError(f"not a quarter: {label!r} (expected e.g. '2026q3')")
    return int(match.group(1)), int(match.group(2))


def expand(spec: str) -> list[str]:
    """'2009q2..2009q4,2026q3' -> ['2009q2', '2009q3', '2009q4', '2026q3'], in order, once each."""
    quarters: list[str] = []
    for part in (p.strip().lower() for p in spec.split(",")):
        if not part:
            continue
        if ".." in part:
            first, last = (_parse(end.strip()) for end in part.split("..", 1))
            if first > last:
                raise ValueError(f"range runs backwards: {part!r}")
            year, quarter = first
            while (year, quarter) <= last:
                quarters.append(f"{year}q{quarter}")
                year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
        else:
            _parse(part)
            quarters.append(part)
    return list(dict.fromkeys(quarters))  # drop repeats, keep order
