"""Pure CLI response decoding and stdin encoding (no provider SDK)."""
from __future__ import annotations

import json
from typing import Any


def encode_stdin(prompt: str, role: dict[str, Any]) -> str:
    """For agy, send one user event then let communicate() close stdin."""
    mode = role.get("stdin_format", "text")
    if mode == "text":
        return prompt
    if mode == "agy_stream_json":
        return json.dumps({"event": "user", "message": {"content": prompt}},
                          ensure_ascii=False) + "\n"
    raise ValueError(f"unsupported role.stdin_format: {mode}")


def decode_payload(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Decode plain/fenced JSON, Claude envelopes, Codex or agy event streams.

    Do not mistake an agy ERROR/WAITING envelope for an empty implementation.
    Token counts and conversation ID belong to the envelope, not the code JSON.
    """
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1])
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        candidates = []
        for line in text.splitlines():
            try:
                candidates.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        for candidate in reversed(candidates):
            if not isinstance(candidate, dict):
                continue
            if any(key in candidate for key in ("structured_output", "result", "response")):
                return decode_payload(json.dumps(candidate))
            item = candidate.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                return decode_payload(item["text"])
        raise ValueError("agent did not return a final JSON object") from None
    if not isinstance(raw, dict):
        raise ValueError("agent output must be a JSON object")
    # agy stream-json puts its completed envelope under result.
    if raw.get("event") == "result" and isinstance(raw.get("result"), dict):
        return decode_payload(json.dumps(raw["result"]))
    agy = "conversation_id" in raw or "response" in raw
    if agy and "status" in raw and raw["status"] != "SUCCESS":
        raise ValueError(f"agy status={raw['status']}: {raw.get('error') or raw.get('response') or 'no completed response'}")
    if raw.get("is_error") is True:
        raise ValueError(f"agent reported an error: {raw.get('result') or raw.get('error')}")
    metadata = {"usage": raw.get("usage"), "reported_cost_usd": raw.get("total_cost_usd"),
                "model": raw.get("model"), "session_id": raw.get("session_id"),
                "conversation_id": raw.get("conversation_id"), "status": raw.get("status")}
    if isinstance(raw.get("structured_output"), dict):
        return raw["structured_output"], metadata
    for key in ("result", "response"):
        if isinstance(raw.get(key), str):
            payload, nested = decode_payload(raw[key])
            return payload, nested | {k: v for k, v in metadata.items() if v is not None}
    return raw, metadata
