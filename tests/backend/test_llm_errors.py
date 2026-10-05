"""OpenAI error handling, exercised through the real OpenAI SDK against a local stub server.

The stub imitates the Chat Completions endpoint; the requested model name picks the behaviour.
No network access or API key is needed, and nothing falls back to mock output silently.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core.config import get_settings

GOOD_INSIGHT = {
    "summary": "Customer was charged twice for an order of ₹12,500.",
    "root_cause": "Likely a duplicate capture at the payment gateway.",
    "key_issues": ["Duplicate charge"],
    "recommended_actions": ["Verify the duplicate debit", "Refund the extra charge"],
    "customer_reply": "Hello, we are looking into the duplicate charge.",
    "references_used": ["A1"],
}


class StubOpenAI(BaseHTTPRequestHandler):
    last_body: dict | None = None

    def log_message(self, *args: object) -> None:  # keep test output quiet
        pass

    def _send(self, status: int, body: dict, headers: dict[str, str] | None = None) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        StubOpenAI.last_body = body
        model = body["model"]
        if model == "auth":
            self._send(
                401,
                {
                    "error": {
                        "message": "Incorrect API key provided",
                        "type": "invalid_request_error",
                        "code": "invalid_api_key",
                    }
                },
            )
        elif model == "ratelimit":
            self._send(
                429,
                {"error": {"message": "Rate limit reached", "type": "requests", "code": "rate_limit_exceeded"}},
                {"retry-after": "20"},
            )
        elif model == "quota":
            self._send(
                429,
                {
                    "error": {
                        "message": "You exceeded your current quota",
                        "type": "insufficient_quota",
                        "code": "insufficient_quota",
                    }
                },
            )
        elif model == "missing":
            self._send(
                404,
                {
                    "error": {
                        "message": "The model does not exist",
                        "type": "invalid_request_error",
                        "code": "model_not_found",
                    }
                },
            )
        elif model == "malformed":  # e.g. a compatible endpoint that ignores the schema
            self._completion({"summary": "only a summary"})
        elif model == "slow":
            time.sleep(2)
            self._send(200, {})
        else:
            self._completion(GOOD_INSIGHT)

    def _completion(self, content: dict) -> None:  # type: ignore[type-arg]
        self._send(
            200,
            {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-4o-mini-2024-07-18",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(content)},
                    }
                ],
                "usage": {"prompt_tokens": 300, "completion_tokens": 150, "total_tokens": 450},
            },
        )


@pytest.fixture(scope="module")
def stub_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubOpenAI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


@pytest.fixture
def use_openai(monkeypatch: pytest.MonkeyPatch, stub_url: str):  # type: ignore[no-untyped-def]
    def configure(model: str) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
        monkeypatch.setenv("OPENAI_BASE_URL", stub_url)
        monkeypatch.setenv("OPENAI_MODEL", model)
        monkeypatch.setenv("OPENAI_MAX_RETRIES", "0")
        monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "0.5")
        get_settings.cache_clear()

    yield configure
    monkeypatch.undo()
    get_settings.cache_clear()


async def create(client) -> int:  # type: ignore[no-untyped-def]
    res = await client.post(
        "/api/v1/tickets",
        json={
            "description": "I was charged twice for ₹12,500. Call me on 9876543210 or mail ravi@gmail.com",
            "customer_name": "Ravi Kumar",
        },
    )
    return res.json()["id"]


async def test_success_stores_usage_and_cost_and_masks_pii(client, use_openai):
    cid = await create(client)
    use_openai("gpt-4o-mini")
    res = await client.post("/api/v1/ai/draft-response", json={"ticket_id": cid})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["provider"] == "openai" and body["model"] == "gpt-4o-mini-2024-07-18"
    assert body["summary"] == GOOD_INSIGHT["summary"] and body["root_cause"] == GOOD_INSIGHT["root_cause"]
    assert body["prompt_version"] == "copilot-v3" and body["draft_status"] == "pending"
    u = body["usage"]
    assert (u["prompt_tokens"], u["completion_tokens"], u["total_tokens"]) == (300, 150, 450)
    assert u["estimated_cost_usd"] == pytest.approx((300 * 0.15 + 150 * 0.60) / 1e6)
    sent = json.dumps(StubOpenAI.last_body)
    for secret in ("9876543210", "ravi@gmail.com", "Ravi Kumar"):
        assert secret not in sent
    assert "[PHONE]" in sent and "[EMAIL]" in sent


@pytest.mark.parametrize(
    ("model", "status", "code", "phrase"),
    [
        ("auth", 502, "llm_auth_failed", "rejected the API key"),
        ("ratelimit", 429, "llm_rate_limited", "Try again in about 20 s"),
        ("quota", 429, "llm_quota_exceeded", "quota exhausted"),
        ("missing", 502, "llm_model_not_found", "was not found"),
        ("slow", 504, "llm_timeout", "did not respond within 0.5 s"),
        ("malformed", 502, "llm_invalid_output", "malformed"),
    ],
)
async def test_openai_failures_return_clear_errors(client, use_openai, model, status, code, phrase):
    cid = await create(client)
    use_openai(model)
    res = await client.post("/api/v1/ai/draft-response", json={"ticket_id": cid})
    assert res.status_code == status
    detail = res.json()["detail"]
    assert detail["code"] == code and phrase in detail["message"]
    if model == "ratelimit":
        assert res.headers["retry-after"] == "20"
    # Nothing was stored and no mock output was substituted.
    assert (await client.get(f"/api/v1/tickets/{cid}")).json()["copilot"] is None


async def test_missing_key_is_a_configuration_error(client, monkeypatch):
    cid = await create(client)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    try:
        res = await client.post("/api/v1/ai/draft-response", json={"ticket_id": cid})
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert res.status_code == 503 and res.json()["detail"]["code"] == "llm_not_configured"
