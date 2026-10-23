"""CSV writers for reports people open in Excel: workbook or Azure DevOps text can't run as a formula.

Not for files BPCTool reads back (ado-id-map.csv), where values must stay exact.
"""

from __future__ import annotations

import csv
from typing import Any, Iterable

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def spreadsheet_safe(value: Any) -> Any:
    """Prefix text that a spreadsheet would treat as a formula with an apostrophe."""
    if isinstance(value, str) and value.startswith(FORMULA_STARTS):
        return "'" + value
    return value


class SafeWriter:
    def __init__(self, handle: Any, **kwargs: Any) -> None:
        self._writer = csv.writer(handle, **kwargs)

    def writerow(self, row: Iterable[Any]) -> Any:
        return self._writer.writerow([spreadsheet_safe(value) for value in row])

    def writerows(self, rows: Iterable[Iterable[Any]]) -> None:
        for row in rows:
            self.writerow(row)


class SafeDictWriter(csv.DictWriter):
    def writerow(self, rowdict: dict[str, Any]) -> Any:
        return super().writerow({key: spreadsheet_safe(value) for key, value in rowdict.items()})

    def writerows(self, rowdicts: Iterable[dict[str, Any]]) -> None:
        for row in rowdicts:
            self.writerow(row)
