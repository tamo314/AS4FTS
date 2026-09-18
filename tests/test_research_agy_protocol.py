from __future__ import annotations

import json
import subprocess
import sys

import pytest

from n225m_bt.research.agent_output import decode_payload, encode_stdin

PAYLOAD = {"files": [{"path": "src/n225m_bt/components/demo.py", "content": "value = 1\n"}], "uses": [], "note": "test"}


@pytest.mark.parametrize("kind", ["plain", "fenced", "claude", "agy", "agy_schema", "agy_stream", "codex"])
def test_formats_decode_code_not_envelope(kind):
    text = json.dumps(PAYLOAD)
    if kind == "fenced":
        text = "```json\n" + text + "\n```"
    elif kind == "claude":
        text = json.dumps({"result": text, "usage": {"input_tokens": 9}})
    elif kind in {"agy", "agy_schema", "agy_stream"}:
        envelope = {"conversation_id": "test-id", "status": "SUCCESS", "response": text,
                    "usage": {"input_tokens": 9}}
        if kind == "agy_schema":
            envelope["structured_output"] = PAYLOAD
        text = json.dumps(envelope)
        if kind == "agy_stream":
            text = '{"event":"init"}\n' + json.dumps({"event": "result", "result": envelope})
    elif kind == "codex":
        text = '{"type":"thread.started"}\n' + json.dumps({"item": {"type": "agent_message", "text": text}})
    result, meta = decode_payload(text)
    assert result == PAYLOAD
    if kind.startswith("agy"):
        assert meta["conversation_id"] == "test-id"
        assert meta["usage"]["input_tokens"] == 9
        assert meta["reported_cost_usd"] is None


@pytest.mark.parametrize("status", ["ERROR", "WAITING", "CANCELED", "INVALID", "RUNNING", "INTERRUPTED"])
def test_agy_non_success_is_not_empty_implementation(status):
    text = json.dumps({"conversation_id": "id", "status": status, "response": "", "error": "detail"})
    with pytest.raises(ValueError, match=status):
        decode_payload(text)


@pytest.mark.parametrize("text", ["", "not json", "[]", "{\"event\":\"init\"}\n{\"event\":\"step_update\"}"])
def test_missing_final_payload_is_rejected(text):
    with pytest.raises(ValueError):
        decode_payload(text)


def test_error_even_with_structured_output():
    with pytest.raises(ValueError, match="ERROR"):
        decode_payload(json.dumps({"status": "ERROR", "conversation_id": "id", "structured_output": PAYLOAD}))
    with pytest.raises(ValueError, match="agent reported"):
        decode_payload(json.dumps({"is_error": True, "result": "failed"}))


def test_multiline_unicode_and_braces_are_one_stdin_event():
    prompt = '日本語\n{"model":"literal {model}"}\n' * 3000
    text = encode_stdin(prompt, {"stdin_format": "agy_stream_json"})
    assert len(text.splitlines()) == 1
    assert json.loads(text) == {"event": "user", "message": {"content": prompt}}
    assert encode_stdin(prompt, {}) == prompt
    with pytest.raises(ValueError):
        encode_stdin(prompt, {"stdin_format": "typo"})


def test_fake_cli_stream_eof_round_trip(tmp_path):
    # Protocol test: actual subprocess and pipes, no live CLI or model call.
    path = tmp_path / "fake_agy.py"
    path.write_text('''import json,sys
message=json.loads(sys.stdin.readline())
assert sys.stdin.read()==""
payload={"files":[], "note":message["message"]["content"]}
print(json.dumps({"event":"init"}))
print(json.dumps({"event":"result","result":{"status":"SUCCESS","conversation_id":"mock", "response":json.dumps(payload),"usage":{"input_tokens":2}}}))
''', encoding="utf-8")
    prompt = "全ケースを実行する\n{prompt}"
    completed = subprocess.run([sys.executable, str(path)], input=encode_stdin(prompt, {"stdin_format": "agy_stream_json"}),
                               capture_output=True, text=True, encoding="utf-8", timeout=10, check=True)
    payload, metadata = decode_payload(completed.stdout)
    assert payload == {"files": [], "note": prompt}
    assert metadata["conversation_id"] == "mock"
