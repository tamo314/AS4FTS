"""Pure CLI decoding: recover a unique JSON answer, never guess between answers."""
from __future__ import annotations

import json
import re
from typing import Any


class AgentOutputError(ValueError):
    """Output format problem, NOT a request to rewrite the strategy."""


class AgentReportedError(AgentOutputError):
    """The CLI explicitly reported an error or a waiting state."""


def encode_stdin(prompt: str, role: dict[str, Any]) -> str:
    mode = role.get("stdin_format", "text")
    if mode == "text":
        return prompt
    if mode == "agy_stream_json":
        return json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=False) + "\n"
    raise AgentOutputError(f"unsupported role.stdin_format: {mode}")


def _read_json(text: str) -> Any:
    text = text.lstrip("\ufeff").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Explanation before/after one fenced answer is harmless. Multiple candidate
    # answers are ambiguous even when one appears to have the preferred shape.
    blocks = re.findall(r"^\s*```(?:json)?\s*\n(.*?)^\s*```\s*$", text,
                        flags=re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if blocks:
        if len(blocks) != 1:
            raise AgentOutputError("multiple JSON code blocks; refusing to choose an answer")
        try:
            return json.loads(blocks[0])
        except json.JSONDecodeError as exc:
            raise AgentOutputError("invalid JSON inside the answer block") from exc
    events = []
    for line in text.splitlines():
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            events.append(candidate)
    finals = [e for e in events if e.get("event") == "result" or e.get("type") == "result"
              or any(k in e for k in ("structured_output", "result", "response"))
              or (isinstance(e.get("item"), dict) and e["item"].get("type") == "agent_message")]
    if finals:
        # Explicit final envelopes take precedence over intermediate agent text.
        terminal = [e for e in finals if e.get("event") == "result" or e.get("type") == "result"]
        return (terminal or finals)[-1]
    raise AgentOutputError("agent did not return a final JSON object")


def decode_payload(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return _decode(text, 0)


def _decode(text: str, depth: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if depth > 8:
        raise AgentOutputError("too many nested agent envelopes")
    raw = _read_json(text)
    if not isinstance(raw, dict):
        raise AgentOutputError("agent output must be a JSON object")
    if raw.get("is_error") is True:
        raise AgentReportedError(f"agent reported an error: {raw.get('result') or raw.get('error')}")
    agy = "conversation_id" in raw or "response" in raw
    if agy and "status" in raw and raw["status"] != "SUCCESS":
        raise AgentReportedError(f"agy status={raw['status']}: {raw.get('error') or raw.get('response')}")
    metadata = {"usage": raw.get("usage"), "reported_cost_usd": raw.get("total_cost_usd"),
                "model": raw.get("model"), "session_id": raw.get("session_id"),
                "conversation_id": raw.get("conversation_id"), "status": raw.get("status")}
    if isinstance(raw.get("structured_output"), dict):
        return raw["structured_output"], metadata
    item = raw.get("item")
    nested: Any = None
    if raw.get("event") == "result" and isinstance(raw.get("result"), dict):
        nested = json.dumps(raw["result"])
    elif isinstance(item, dict) and item.get("type") == "agent_message":
        nested = item.get("text")
    else:
        nested = next((raw[k] for k in ("result", "response") if isinstance(raw.get(k), str)), None)
    if nested is not None:
        payload, inner = _decode(nested, depth + 1)
        return payload, inner | {k: v for k, v in metadata.items() if v is not None}
    return raw, metadata
