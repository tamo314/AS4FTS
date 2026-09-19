import json

import pytest

from n225m_bt.research.agent_output import AgentOutputError, AgentReportedError, decode_payload


@pytest.mark.parametrize("prefix,suffix", [("", ""), ("Here is the implementation.\n", ""),
                                           ("説明\n", "\n以上です。")])
def test_unique_fence_with_explanation(prefix, suffix):
    payload = {"files": [{"path": "x.py", "content": "print('日本語')\n"}]}
    text = prefix + '```json\n' + json.dumps(payload) + '\n```' + suffix
    assert decode_payload(text)[0] == payload


def test_claude_metadata_survives_recovery():
    text = json.dumps({"result": 'Explanation\n```json\n{"files": []}\n```',
                       "total_cost_usd": .25, "usage": {"input_tokens": 8}})
    payload, metadata = decode_payload(text)
    assert payload == {"files": []}
    assert metadata["reported_cost_usd"] == .25


@pytest.mark.parametrize("text", [
    '```json\n{"files": []}\n```\n```json\n{"files": []}\n```',
    '```json\n{"files": [}\n```', '[]', 'no JSON here'])
def test_no_ambiguous_or_invalid_repair(text):
    with pytest.raises(AgentOutputError):
        decode_payload(text)


@pytest.mark.parametrize("payload", [
    {"is_error": True, "result": '{"files": []}'},
    {"status": "ERROR", "response": '{"files": []}'},
    {"status": "WAITING", "conversation_id": "a", "structured_output": {"files": []}}])
def test_error_envelope_cannot_be_bypassed(payload):
    with pytest.raises(AgentReportedError):
        decode_payload(json.dumps(payload))


def test_agy_and_codex_streams():
    agy = '\n'.join([json.dumps({"event": "agent_response", "response": "progress"}),
        json.dumps({"event": "result", "result": {"status": "SUCCESS", "conversation_id": "x",
                                                      "structured_output": {"files": []}}})])
    assert decode_payload(agy)[0] == {"files": []}
    codex = json.dumps({"type": "progress"}) + '\n' + json.dumps({"item": {
        "type": "agent_message", "text": '{"files": []}'}})
    assert decode_payload(codex)[0] == {"files": []}
