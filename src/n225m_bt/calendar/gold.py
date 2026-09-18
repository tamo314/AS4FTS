"""Build an AS4FTS calendar from existing Gold time columns, without re-ingestion."""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from n225m_bt.calendar.model import ExchangeCalendar, TradingDay
from n225m_bt.calendar.session_rules import regime_for_trade_date
from n225m_bt.config import JST, SessionsConfig, load_yaml_model


@dataclass(frozen=True)
class TimeObservation:
    """One trade-date/session/calendar-date group's first and last observed instant."""

    trade_date: date
    session: str
    first_ts: datetime
    last_ts: datetime
    source: str = ""


def discover_gold_files(roots: Iterable[Path]) -> list[Path]:
    """Exact partition depth: the center root must not silently include forward."""
    paths: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        files = sorted(resolved.glob("year=*/month=*/*.parquet"))
        if not files:
            raise ValueError(f"no year=*/month=*/*.parquet files under {resolved}")
        paths.update(files)
    if not paths:
        raise ValueError("provide at least one Gold root")
    return sorted(paths)


def read_observations(paths: Iterable[Path]) -> Iterator[TimeObservation]:
    """Read three columns only; reduce each partition before creating Python objects."""
    import polars as pl

    required = ("trade_date", "session", "ts_jst")
    for path in paths:
        frame = pl.scan_parquet(str(path), hive_partitioning=False)
        schema = frame.collect_schema()
        missing = set(required) - set(schema.names())
        if missing:
            raise ValueError(f"{path}: missing canonical Gold columns {sorted(missing)}")
        dtype = schema["ts_jst"]
        if not isinstance(dtype, pl.Datetime) or dtype.time_zone is None:
            raise ValueError(f"{path}: ts_jst must be a timezone-aware Parquet datetime")
        frame = frame.select(list(required)).with_columns(
            pl.col("ts_jst").dt.convert_time_zone("Asia/Tokyo")
        )
        grouped = (
            frame.with_columns(pl.col("ts_jst").dt.date().alias("_calendar_date"))
            .group_by(["trade_date", "session", "_calendar_date"])
            .agg(
                pl.col("ts_jst").min().alias("first_ts"),
                pl.col("ts_jst").max().alias("last_ts"),
            )
            .collect()
        )
        for row in grouped.iter_rows(named=True):
            value = row["trade_date"]
            if isinstance(value, datetime):
                value = value.date()
            if not isinstance(value, date):
                value = date.fromisoformat(str(value))
            yield TimeObservation(
                value, str(row["session"]), row["first_ts"], row["last_ts"], str(path)
            )


def calendar_from_observations(
    observations: Iterable[TimeObservation], sessions: SessionsConfig
) -> tuple[ExchangeCalendar, dict[str, Any]]:
    """Prefer observed evenings; infer morning-only starts from actual timestamps.

    Never compute an evening as trade_date minus one day. No missing trading dates,
    holiday classifications or prices are invented. Existing Gold labels are trusted,
    not repaired. Date links describe observed trading dates, not an official calendar.
    """
    dates: set[date] = set()
    evenings: dict[date, set[date]] = defaultdict(set)
    mornings: dict[date, set[date]] = defaultdict(set)
    night_days: set[date] = set()
    for item in observations:
        dates.add(item.trade_date)
        if item.session not in {"day", "night"}:
            raise ValueError(f"{item.source}: unsupported session={item.session!r}")
        for stamp in (item.first_ts, item.last_ts):
            if not isinstance(stamp, datetime) or stamp.utcoffset() is None:
                raise ValueError(f"{item.source}: missing or timezone-naive ts_jst")
            if item.session == "day":
                continue
            night_days.add(item.trade_date)
            local = stamp.astimezone(JST)
            regime = regime_for_trade_date(sessions, local.date())
            if local.time() >= regime.night.session_open:
                evenings[item.trade_date].add(local.date())
            else:
                # This is the date of an OBSERVED post-midnight bar, not trade_date.
                start = local.date() - timedelta(days=1)
                previous = regime_for_trade_date(sessions, start)
                close = previous.night.session_close_next_day
                if close is None or local.time() > close:
                    raise ValueError(f"{item.source}: night timestamp outside configured hours: {local}")
                mornings[item.trade_date].add(start)
    if not dates:
        raise ValueError("Gold has no observed trading dates")
    ordered = sorted(dates)
    entries: list[TradingDay] = []
    warnings: list[dict[str, str]] = []
    observed_count = inferred_count = 0
    for index, trade_date in enumerate(ordered):
        explicit = evenings.get(trade_date, set())
        inferred = mornings.get(trade_date, set())
        candidates = explicit or inferred
        if len(candidates) > 1:
            raise ValueError(
                f"trade_date={trade_date}: conflicting night start dates {sorted(candidates)}; "
                "Gold labels disagree. Do not merge incompatible series or invent a date."
            )
        night_start = next(iter(candidates)) if candidates else None
        if night_start is not None and night_start >= trade_date:
            raise ValueError(
                f"trade_date={trade_date}: night starts on {night_start}; expected an earlier "
                "calendar date. Check the old Gold's trade_date semantics."
            )
        if explicit:
            observed_count += 1
            origin = "observed_gold_evening"
            if inferred - explicit:
                warnings.append({
                    "trade_date": trade_date.isoformat(),
                    "message": "Morning timestamps imply a different start; observed evening "
                    "was retained. Gold timestamp/trade-date semantics were NOT repaired.",
                })
        elif inferred:
            inferred_count += 1
            origin = "inferred_from_observed_gold_morning"
        else:
            origin = "gold_day_only_no_night_mapping"
        entries.append(TradingDay(
            trade_date=trade_date,
            previous_trade_date=ordered[index - 1] if index else None,
            next_trade_date=ordered[index + 1] if index + 1 < len(ordered) else None,
            night_calendar_start_date=night_start,
            # Required legacy boolean; NOT evidence that this was a non-holiday.
            is_holiday_trading_day=False,
            schedule_version=regime_for_trade_date(sessions, trade_date).id,
            source_note=f"{origin}; date_links=observed_only; holiday_status=unknown",
        ))
    return ExchangeCalendar(entries), {
        "trade_dates": len(ordered), "first_trade_date": ordered[0].isoformat(),
        "last_trade_date": ordered[-1].isoformat(),
        "observed_evening_mappings": observed_count,
        "morning_only_inferred_mappings": inferred_count,
        "dates_without_night_bars": len(dates - night_days),
        "holiday_status": "unknown; required boolean is false as a compatibility placeholder",
        "warnings": warnings,
        "note": "Calendar reconstructed from supplied Gold, not an official exchange calendar. "
        "OHLC, missing dates and upstream timestamp semantics are not audited or repaired.",
    }


def build_calendar_from_gold(
    gold_roots: Iterable[Path], output: Path, sessions_path: Path
) -> dict[str, Any]:
    """One-time preparation outside the research loop; source files are read-only."""
    roots = [root.resolve() for root in gold_roots]
    output = output.resolve()
    if output.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("calendar output must have .yaml or .yml extension")
    if any(output.is_relative_to(root) for root in roots):
        raise ValueError("write the calendar outside Gold roots, for example under config/")
    paths = discover_gold_files(roots)
    sessions = load_yaml_model(sessions_path, SessionsConfig)
    calendar, summary = calendar_from_observations(read_observations(paths), sessions)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + ".tmp" + output.suffix)
    try:
        calendar.to_yaml(temporary)
        # Round-trip only this small generated artifact, not a market-data audit.
        ExchangeCalendar.from_path(temporary)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    summary.update({"file_count": len(paths), "output": str(output)})
    report_path = output.with_suffix(".summary.json")
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    """Standalone one-time preparation command; no agent or research run is started."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-root", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, default=Path("config/local_calendar_as4fts.yaml"))
    parser.add_argument("--sessions", type=Path, default=Path("config/sessions.yaml"))
    args = parser.parse_args()
    try:
        result = build_calendar_from_gold(args.gold_root, args.output, args.sessions)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"calendar generation failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
