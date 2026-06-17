from __future__ import annotations

import re
from html import escape


def to_test_steps_xml(value: str | None, expected: str | None = None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if text.startswith("<steps"):
        return text

    lines = [line.strip(" \t-") for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines:
        return None

    steps = []
    for index, line in enumerate(lines, start=1):
        action, result = _split_expected(line)
        if not result and expected:
            result = str(expected)
        steps.append(
            f'<step id="{index}" type="ActionStep">'
            f'<parameterizedString isformatted="true">{escape(action)}</parameterizedString>'
            f'<parameterizedString isformatted="true">{escape(result or "")}</parameterizedString>'
            "</step>"
        )
    return f'<steps id="0" last="{len(steps)}">' + "".join(steps) + "</steps>"


def _split_expected(line: str) -> tuple[str, str | None]:
    for marker in (r"\s=>\s", r"\s\|\s*expected:\s", r"\sexpected:\s", r"\sresult:\s"):
        parts = re.split(marker, line, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2:
            left, right = parts
            return left.strip(), right.strip()
    return line, None
