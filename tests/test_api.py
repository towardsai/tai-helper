from __future__ import annotations

from fastapi.testclient import TestClient

from tai_helper import api
from tai_helper.llm import LLMResult
from tai_helper.rate_limiter import FixedWindowRateLimiter, RateLimit

client = TestClient(api.app)
HEADERS = {"Origin": "https://towardsai.com"}
PUBLIC_URL = "https://towardsai.com/academy/agentic-ai-engineering/"
FIRST_PROMPT = "I want help deciding which course to take."


def reset_limiters() -> None:
    api.visitor_limiter = FixedWindowRateLimiter(
        (
            RateLimit("per_minute", 100, 60),
            RateLimit("per_day", 1000, 24 * 60 * 60),
        )
    )
    api.ip_limiter = FixedWindowRateLimiter(
        (
            RateLimit("ip_per_minute", 100, 60),
            RateLimit("ip_per_day", 1000, 24 * 60 * 60),
        )
    )
    api.global_limiter = FixedWindowRateLimiter(
        (RateLimit("global_per_minute", 1000, 60),)
    )


def payload(
    query: str = FIRST_PROMPT, *, url: str = PUBLIC_URL, signed_in: bool = False
):
    return {
        "query": query,
        "selectedPrompt": query if query == FIRST_PROMPT else FIRST_PROMPT,
        "visitorId": "test-visitor",
        "threadId": "",
        "history": [],
        "context": {
            "url": url,
            "pageTitle": "Agent course",
            "signedIn": signed_in,
        },
    }


def test_config_exposes_public_widget_contract() -> None:
    response = client.get("/api/helper/config")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Towards AI Helper"
    assert FIRST_PROMPT in data["forcedPrompts"]
    assert "towardsai.com" in data["allowedHosts"]
    assert "towardsai.com" in data["siteWideHosts"]
    assert (
        "/academy/agentic-ai-engineering" in data["allowedPathsByHost"]["towardsai.com"]
    )
    assert (
        "/courses/agent-engineering"
        in data["allowedPathsByHost"]["academy.towardsai.net"]
    )


def test_footer_compatible_widget_path_is_served() -> None:
    response = client.get("/helper-widget.js")

    assert response.status_code == 200
    assert "Towards AI Helper" in response.text


def test_cors_preflight_accepts_towardsai_com() -> None:
    response = client.options(
        "/api/helper/chat",
        headers={
            "Origin": "https://towardsai.com",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://towardsai.com"


def test_chat_requires_allowed_origin_public_page_signed_out_and_first_prompt() -> None:
    reset_limiters()

    assert client.post("/api/helper/chat", json=payload()).status_code == 403
    assert (
        client.post(
            "/api/helper/chat",
            json=payload(url="https://towardsai.com/wp-admin/edit.php"),
            headers=HEADERS,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/helper/chat",
            json=payload(signed_in=True),
            headers=HEADERS,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/helper/chat",
            json=payload(query="Can I type first?"),
            headers=HEADERS,
        ).status_code
        == 400
    )


def test_chat_calls_gemini_with_retrieved_sources(monkeypatch) -> None:
    reset_limiters()
    prompts = []

    def fake_generate_answer(prompt: str) -> LLMResult:
        prompts.append(prompt)
        return LLMResult(
            answer="Tell me your coding background and goal.",
            usage={"input_tokens": 10, "output_tokens": 8, "total_tokens": 18},
            latency_ms=123,
        )

    monkeypatch.setattr(api.llm, "generate_answer", fake_generate_answer)

    response = client.post("/api/helper/chat", json=payload(), headers=HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Tell me your coding background and goal."
    assert data["threadId"]
    assert data["sources"]
    assert data["usage"]["total_tokens"] == 18
    assert "Agent Engineering" in prompts[0]


def test_chat_still_accepts_legacy_net_origin(monkeypatch) -> None:
    reset_limiters()
    monkeypatch.setattr(
        api.llm,
        "generate_answer",
        lambda _prompt: LLMResult(answer="ok"),
    )

    response = client.post(
        "/api/helper/chat",
        json=payload(url="https://towardsai.net/b2b"),
        headers={"Origin": "https://towardsai.net"},
    )

    assert response.status_code == 200


def test_coupon_answer_is_deterministic_and_does_not_call_model(monkeypatch) -> None:
    reset_limiters()

    def unexpected_generate_answer(_prompt: str) -> LLMResult:
        raise AssertionError("model should not be called for coupon intent")

    monkeypatch.setattr(api.llm, "generate_answer", unexpected_generate_answer)
    first = payload(query="Do you have a coupon code?")
    first["selectedPrompt"] = FIRST_PROMPT
    first["history"] = [{"role": "user", "content": FIRST_PROMPT}]
    second = payload(query="Please I really need a coupon code")
    second["selectedPrompt"] = FIRST_PROMPT
    second["history"] = [
        {"role": "user", "content": FIRST_PROMPT},
        {"role": "assistant", "content": "I can't provide a coupon code here."},
    ]

    first_response = client.post("/api/helper/chat", json=first, headers=HEADERS)
    second_response = client.post("/api/helper/chat", json=second, headers=HEADERS)

    assert first_response.status_code == 200
    assert "Get It All bundle" in first_response.json()["answer"]
    assert (
        "towardsai.com/academy/bundles/get-it-all/" in first_response.json()["answer"]
    )
    assert second_response.status_code == 200
    assert "louis@towardsai.net" in second_response.json()["answer"]


def test_rate_limit_is_hard(monkeypatch) -> None:
    api.visitor_limiter = FixedWindowRateLimiter((RateLimit("per_minute", 1, 60),))
    api.ip_limiter = FixedWindowRateLimiter((RateLimit("ip_per_minute", 100, 60),))
    api.global_limiter = FixedWindowRateLimiter(
        (RateLimit("global_per_minute", 100, 60),)
    )

    monkeypatch.setattr(
        api.llm,
        "generate_answer",
        lambda _prompt: LLMResult(answer="ok"),
    )

    first = client.post("/api/helper/chat", json=payload(), headers=HEADERS)
    second = client.post("/api/helper/chat", json=payload(), headers=HEADERS)

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) > 0
