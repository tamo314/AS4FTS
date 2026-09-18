"""Pure helpers for selecting versioned session regimes."""

from __future__ import annotations

from datetime import date

from n225m_bt.config import SessionRegime, SessionsConfig


def regime_for_trade_date(config: SessionsConfig, trade_date: date) -> SessionRegime:
    for regime in config.regimes:
        if regime.effective_from <= trade_date and (
            regime.effective_to is None or trade_date <= regime.effective_to
        ):
            return regime
    raise ValueError(f"no session regime configured for trade_date={trade_date.isoformat()}")
