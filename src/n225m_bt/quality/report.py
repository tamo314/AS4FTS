"""Machine-readable issue collection and deterministic report rendering."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import Enum
from pathlib import Path

import polars as pl


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    severity: Severity
    message: str
    source_file: str | None = None
    source_row_number: int | None = None
    ts_jst: str | None = None
    calendar_date: str | None = None
    session: str | None = None


class QualityReport:
    def __init__(self) -> None:
        self.issues: list[QualityIssue] = []

    def add(self, issue: QualityIssue) -> None:
        self.issues.append(issue)

    @property
    def has_fatal(self) -> bool:
        return any(issue.severity is Severity.FATAL for issue in self.issues)

    @property
    def has_error(self) -> bool:
        return any(issue.severity in {Severity.ERROR, Severity.FATAL} for issue in self.issues)

    def summary(self) -> dict[str, object]:
        counts = Counter(issue.code for issue in self.issues)
        severities = Counter(issue.severity.value for issue in self.issues)
        years: Counter[str] = Counter()
        months: Counter[str] = Counter()
        sessions = Counter(issue.session for issue in self.issues if issue.session is not None)
        for issue in self.issues:
            if issue.calendar_date is None:
                continue
            parsed = datetime.fromisoformat(issue.calendar_date)
            years[str(parsed.year)] += 1
            months[parsed.strftime("%Y-%m")] += 1
        return {
            "issue_count": len(self.issues),
            "by_code": dict(sorted(counts.items())),
            "by_severity": dict(sorted(severities.items())),
            "by_year": dict(sorted(years.items())),
            "by_month": dict(sorted(months.items())),
            "by_session": dict(sorted(sessions.items())),
        }

    def enrich_lineage(
        self,
        lineage_by_timestamp: dict[str, tuple[str, int, str, str]],
    ) -> None:
        """Attach bar lineage where an issue had a canonical timestamp."""
        self.issues = [
            replace(
                issue,
                source_file=lineage_by_timestamp[issue.ts_jst][0],
                source_row_number=lineage_by_timestamp[issue.ts_jst][1],
                calendar_date=lineage_by_timestamp[issue.ts_jst][2],
                session=lineage_by_timestamp[issue.ts_jst][3],
            )
            if issue.ts_jst in lineage_by_timestamp
            else issue
            for issue in self.issues
        ]

    def write(self, output_dir: Path) -> None:
        import json

        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "quality_summary.json").write_text(
            json.dumps(self.summary(), indent=2, sort_keys=True), encoding="utf-8"
        )
        rows = [asdict(item) for item in self.issues]
        schema = {
            "code": pl.String,
            "severity": pl.String,
            "message": pl.String,
            "source_file": pl.String,
            "source_row_number": pl.Int64,
            "ts_jst": pl.String,
            "calendar_date": pl.String,
            "session": pl.String,
        }
        pl.DataFrame(rows, schema=schema, strict=False).write_parquet(
            output_dir / "quality_issues.parquet"
        )
        lines = ["# Data quality report", "", f"Issues: {len(self.issues)}", ""]
        lines.extend(
            f"- `{issue.severity}` `{issue.code}` — {issue.message}" for issue in self.issues[:100]
        )
        (output_dir / "quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
