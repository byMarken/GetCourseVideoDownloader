from __future__ import annotations

import re

_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str, *, fallback: str = "video") -> str:
    clean = re.sub(
        r"\b(Просмотрено|Пройдено|Завершено)\b",
        "",
        name,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"\s+", " ", clean).strip()
    clean = re.sub(r"[\\/*?:\"<>|]", "_", clean).rstrip(". ")
    if not clean:
        clean = fallback
    if clean.upper() in _WINDOWS_RESERVED:
        clean = f"_{clean}"
    return clean[:180]
