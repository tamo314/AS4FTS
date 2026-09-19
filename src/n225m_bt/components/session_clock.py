"""Wall-clock session boundaries and phase time calculator from session configuration."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from n225m_bt.calendar.classifier import CalendarClassifier
from n225m_bt.calendar.model import ExchangeCalendar
from n225m_bt.components import component
from n225m_bt.config import SessionsConfig, load_yaml_model
from n225m_bt.domain import Session


@component(
    id="session_clock",
    kind="feature",
    summary="Wall-clock session boundaries and phase time calculator from session configuration",
    tags=["session", "clock", "calendar"],
    uses=[],
)
class SessionClock:
    """Calculates exchange session open times and wall-clock windows based on regime rules."""

    def __init__(
        self, sessions: SessionsConfig | str | Path = "config/sessions.yaml",
        *, exchange_calendar: ExchangeCalendar | None = None,
    ) -> None:
        """Use explicit trade-date mappings for night sessions; day-only callers stay compatible."""
        if isinstance(sessions, (str, Path)):
            path = Path(sessions)
            if not path.exists() and not path.is_absolute():
                for parent in (Path.cwd(), *Path.cwd().parents):
                    candidate = parent / path
                    if candidate.exists():
                        path = candidate
                        break
            self.sessions = load_yaml_model(path, SessionsConfig)
        elif isinstance(sessions, SessionsConfig):
            self.sessions = sessions
        else:
            raise TypeError("sessions must be SessionsConfig, str, or Path")
        self.classifier = CalendarClassifier(self.sessions, exchange_calendar)

    def session_open(self, trade_date: date, session: Session = Session.DAY) -> datetime:
        """Return the actual JST opening instant for one exchange session."""
        return self.classifier.session_open(trade_date, session)

    def session_close(self, trade_date: date, session: Session = Session.DAY) -> datetime:
        """Return the actual JST closing instant for one exchange session."""
        return self.classifier.session_close(trade_date, session)

    def opening_window(
        self, trade_date: date, opening_minutes: int, session: Session = Session.DAY
    ) -> tuple[datetime, datetime]:
        """Return [open_ts, open_ts + opening_minutes) for the given session."""
        start = self.session_open(trade_date, session)
        return start, start + timedelta(minutes=opening_minutes)

    def entry_window(
        self,
        trade_date: date,
        opening_minutes: int,
        entry_window_minutes: int,
        session: Session = Session.DAY,
    ) -> tuple[datetime, datetime]:
        """Return [open_ts + opening_minutes, open_ts + opening_minutes + entry_window_minutes)."""
        start = self.session_open(trade_date, session) + timedelta(minutes=opening_minutes)
        return start, start + timedelta(minutes=entry_window_minutes)
