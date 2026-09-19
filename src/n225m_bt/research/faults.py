"""Failure routing keeps infrastructure repairs out of strategy generation."""
from __future__ import annotations

import sqlite3
import subprocess
import traceback
from concurrent.futures.process import BrokenProcessPool
from typing import Any

from n225m_bt.research.agent_output import AgentOutputError, AgentReportedError


class StrategyCodeError(RuntimeError):
    pass


class AgentCommandError(RuntimeError):
    pass


class BatchFailure(RuntimeError):
    def __init__(self, record: dict[str, Any]):
        self.record = record
        super().__init__(str(record.get("error", "batch failed")))


def fault_record(error: BaseException, *, default: str = "configuration") -> dict[str, Any]:
    if isinstance(error, BatchFailure):
        return {"kind": "configuration"} | error.record
    if isinstance(error, StrategyCodeError):
        kind = "strategy"
    elif isinstance(error, (MemoryError, BrokenProcessPool, subprocess.TimeoutExpired)):
        kind = "resource"
    elif isinstance(error, (OSError, sqlite3.Error)):
        kind = "io"
    elif isinstance(error, (AgentReportedError, AgentCommandError)):
        kind = "agent_cli"
    elif isinstance(error, (AgentOutputError, UnicodeError)):
        kind = "agent_output"
    else:
        kind = default
    return {"kind": kind, "exception": type(error).__name__,
            "error": "".join(traceback.format_exception(error, limit=8))}
