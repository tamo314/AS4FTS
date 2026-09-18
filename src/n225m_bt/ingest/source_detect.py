"""Conservative discovery for user-owned delimited source files."""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceInspection:
    path: str
    encoding: str
    delimiter: str
    headers: tuple[str, ...]
    candidate_mapping: dict[str, str]
    missing_required: tuple[str, ...]

    def to_json(self) -> str:
        import json

        return json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=True)


ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "日付", "年月日", "取引日"),
    "time": ("time", "時刻", "時間"),
    "open": ("open", "始値", "寄付"),
    "high": ("high", "高値"),
    "low": ("low", "安値"),
    "close": ("close", "終値", "現在値"),
    "volume": ("volume", "出来高", "売買高"),
}
REQUIRED = ("date", "time", "open", "high", "low", "close")


def detect_encoding(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("source encoding is not UTF-8 or CP932; configure a supported decoder")


def inspect_delimited_bytes(
    path: Path, raw: bytes, encoding: str = "auto", delimiter: str = "auto"
) -> SourceInspection:
    actual_encoding = detect_encoding(raw) if encoding == "auto" else encoding
    text = raw.decode(actual_encoding)
    sample = text[:8192]
    actual_delimiter = delimiter
    if delimiter == "auto":
        try:
            actual_delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
        except csv.Error:
            actual_delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=actual_delimiter)
    try:
        headers = tuple(cell.strip() for cell in next(reader))
    except StopIteration as error:
        raise ValueError(f"source file {path} is empty") from error
    return inspection_from_headers(path, actual_encoding, actual_delimiter, headers)


def inspection_from_headers(
    path: Path,
    encoding: str,
    delimiter: str,
    headers: tuple[str, ...],
) -> SourceInspection:
    """Resolve aliases from headers emitted by either a delimited file or worksheet."""
    normalized = {header.casefold(): header for header in headers}
    mapping: dict[str, str] = {}
    for canonical, aliases in ALIASES.items():
        for alias in aliases:
            match = normalized.get(alias.casefold())
            if match is not None:
                mapping[canonical] = match
                break
    missing = tuple(item for item in REQUIRED if item not in mapping)
    return SourceInspection(str(path), encoding, delimiter, headers, mapping, missing)
