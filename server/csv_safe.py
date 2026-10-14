"""Spreadsheet-safe CSV cells.

Comments, bios and names are written by strangers. A cell that starts with = + - @ (or a tab / carriage return) is
run as a formula when the CSV is opened in Excel or Sheets (`=HYPERLINK(...)` can send data to a stranger's server).
Prefixing such text with a single quote makes the spreadsheet show it as plain text. Only strings are touched,
and a plain number or phone number such as +919876543210 is left alone because it cannot be a harmful formula.
"""

import re
from typing import Any, Dict

_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
_PHONE = re.compile(r"^[+-]?\d[\d\s().-]{4,}$")
_NUMBER = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


def safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_TRIGGERS) and not (_PHONE.match(value) or _NUMBER.match(value)):
        return "'" + value
    return value


def safe_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: safe_cell(v) for k, v in row.items()}
