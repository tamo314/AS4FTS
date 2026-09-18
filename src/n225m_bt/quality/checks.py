"""Pure canonical bar validations; nothing is silently repaired."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import fmean, pstdev

from n225m_bt.calendar.classifier import CalendarClassifier
from n225m_bt.domain import Bar, Session
from n225m_bt.quality.report import QualityIssue, QualityReport, Severity


def bar_flags(bar: Bar, tick_size: int) -> tuple[str, ...]:
    flags: list[str] = []
    if any(price <= 0 for price in (bar.open, bar.high, bar.low, bar.close)):
        flags.append("NON_POSITIVE_PRICE")
    if not (
        bar.high >= bar.open
        and bar.high >= bar.close
        and bar.low <= bar.open
        and bar.low <= bar.close
        and bar.high >= bar.low
    ):
        flags.append("OHLC_INVARIANT")
    if any(price % tick_size for price in (bar.open, bar.high, bar.low, bar.close)):
        flags.append("TICK_GRID_VIOLATION")
    if bar.volume is not None and bar.volume < 0:
        flags.append("INVALID_VOLUME")
    return tuple(flags)


def validate_bars(
    bars: list[Bar],
    tick_size: int,
    report: QualityReport,
    classifier: CalendarClassifier | None = None,
    detect_missing_minutes: bool = True,
    detect_statistical_outliers: bool = True,
    outlier_return_sigma: float = 12.0,
) -> dict[int, tuple[str, ...]]:
    """Return flags by list index and add structural/continuity findings."""
    flags = {index: list(bar_flags(bar, tick_size)) for index, bar in enumerate(bars)}
    seen: dict[datetime, int] = {}
    for index, bar in enumerate(bars):
        previous = seen.get(bar.ts_jst)
        if previous is not None:
            flags[index].append("DUPLICATE_TIMESTAMP")
            flags[previous].append("DUPLICATE_TIMESTAMP")
            previous_bar = bars[previous]
            same_prices = (
                previous_bar.open,
                previous_bar.high,
                previous_bar.low,
                previous_bar.close,
                previous_bar.volume,
            ) == (bar.open, bar.high, bar.low, bar.close, bar.volume)
            report.add(
                QualityIssue(
                    "DUPLICATE_TIMESTAMP",
                    Severity.WARN if same_prices else Severity.ERROR,
                    "duplicate minute timestamp"
                    if same_prices
                    else "duplicate minute timestamp with conflicting OHLCV",
                    ts_jst=bar.ts_jst.isoformat(),
                )
            )
        seen[bar.ts_jst] = index
        for flag in flags[index]:
            severity = (
                Severity.ERROR
                if flag in {"OHLC_INVARIANT", "NON_POSITIVE_PRICE", "INVALID_VOLUME"}
                else Severity.WARN
            )
            report.add(
                QualityIssue(
                    flag, severity, f"validation failed: {flag}", ts_jst=bar.ts_jst.isoformat()
                )
            )
    if detect_missing_minutes:
        _check_expected_minutes(bars, flags, report, classifier)
    if detect_statistical_outliers:
        _check_price_jumps(bars, flags, report, outlier_return_sigma)
    return {index: tuple(sorted(set(value))) for index, value in flags.items()}


def _check_expected_minutes(
    bars: list[Bar],
    flags: dict[int, list[str]],
    report: QualityReport,
    classifier: CalendarClassifier | None,
) -> None:
    grouped: dict[tuple[date, Session], list[tuple[int, Bar]]] = defaultdict(list)
    for index, bar in enumerate(bars):
        grouped[(bar.trade_date, bar.session)].append((index, bar))
    for (trade_date, session), entries in grouped.items():
        ordered = sorted(entries, key=lambda item: item[1].ts_jst)
        if classifier is None:
            start, end = ordered[0][1].ts_jst, ordered[-1][1].ts_jst
        else:
            start = classifier.session_open(trade_date, session)
            end = classifier.session_close(trade_date, session)
        observed = {bar.ts_jst for _, bar in ordered}
        missing = [expected for expected in _minute_grid(start, end) if expected not in observed]
        if not missing:
            continue
        missing_set = set(missing)
        for index, bar in ordered:
            if bar.ts_jst - timedelta(minutes=1) in missing_set:
                flags[index].append("MISSING_PREV_EXPECTED")
        report.add(
            QualityIssue(
                "MISSING_EXPECTED_MINUTES",
                Severity.WARN,
                f"{len(missing)} missing expected minute(s) in {session.value} session",
                ts_jst=missing[0].isoformat(),
            )
        )


def _minute_grid(start: datetime, end: datetime) -> list[datetime]:
    count = int((end - start).total_seconds() // 60)
    return [start + timedelta(minutes=offset) for offset in range(count + 1)]


def _check_price_jumps(
    bars: list[Bar],
    flags: dict[int, list[str]],
    report: QualityReport,
    sigma_threshold: float,
) -> None:
    ordered = sorted(enumerate(bars), key=lambda item: item[1].ts_jst)
    changes = [
        right.close - left.close
        for (_, left), (_, right) in zip(ordered, ordered[1:], strict=False)
    ]
    if len(changes) < 3:
        return
    deviation = pstdev(changes)
    if deviation == 0:
        return
    average = fmean(changes)
    for (_, left), (index, right) in zip(ordered, ordered[1:], strict=False):
        change = right.close - left.close
        if abs(change - average) > sigma_threshold * deviation:
            flags[index].append("STATISTICAL_PRICE_JUMP")
            report.add(
                QualityIssue(
                    "STATISTICAL_PRICE_JUMP",
                    Severity.WARN,
                    f"close change {change} exceeds {sigma_threshold:g} standard-deviation threshold",
                    ts_jst=right.ts_jst.isoformat(),
                )
            )
