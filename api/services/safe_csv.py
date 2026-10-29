"""
CSV files that owners and the super admin open in Excel / LibreOffice.

A cell typed by a client or an owner (a name, a sector, a note) that starts
with = + - @ — or a tab / carriage return before one — is a formula there:
« =HYPERLINK(...) » as a client's name would run on the owner's computer
(audit 2026-10-29). Such a cell gets a leading apostrophe, which the
spreadsheet shows as text. Plain numbers keep their sign: « -5,00 »,
« +33 6 12 34 56 78 », « -12.5 € », « +4 % ».

Every export writes through `writer()` (a test checks no `csv.writer` is left).
"""
import csv
import re
from typing import Any, Iterable

_DANGER = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"^[+-]?\d[\d\s.,]*\s*(€|%)?$")


def cell(v: Any) -> Any:
    if isinstance(v, str) and v.startswith(_DANGER) and not _NUMBER.match(v):
        return "'" + v
    return v


class _Writer:
    def __init__(self, w):
        self._w = w

    def writerow(self, row: Iterable[Any]):
        return self._w.writerow([cell(v) for v in row])

    def writerows(self, rows: Iterable[Iterable[Any]]):
        for r in rows:
            self.writerow(r)


def writer(buf, delimiter: str = ";", **kw) -> _Writer:
    return _Writer(csv.writer(buf, delimiter=delimiter, **kw))


class _DictWriter:
    def __init__(self, w):
        self._w = w

    def writeheader(self):
        return self._w.writeheader()

    def writerow(self, row):
        return self._w.writerow({k: cell(v) for k, v in row.items()})

    def writerows(self, rows):
        for r in rows:
            self.writerow(r)


def dict_writer(buf, fieldnames, delimiter: str = ";", **kw) -> _DictWriter:
    return _DictWriter(csv.DictWriter(buf, fieldnames=fieldnames, delimiter=delimiter, **kw))
