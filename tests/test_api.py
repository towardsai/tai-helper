from __future__ import annotations

import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from tai_helper import api
from tai_helper import catalog as catalog_module
from tai_helper.llm import EvidenceChunk, GroundingResult
from tai_helper.rate_limiter import FixedWindowRateLimiter, RateLimit

client = TestClient(api.app)
HEADERS = {"Origin": "https://towardsai.com"}
PUBLIC_URL = "https://towardsai.com/academy/agent-engineering/"
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


def assert_contact_handoff(body: dict, *, status: str = "insufficient_evidence") -> None:
    assert body["status"] == status
    assert body["sources"] == []
    assert body["answer"].count(api.CONTACT_FORM_URL) == 1
    assert "louis@towardsai.net" not in body["answer"]


def test_config_exposes_public_widget_contract() -> None:
    response = client.get("/api/helper/config")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Towards AI Helper"
    assert FIRST_PROMPT in data["forcedPrompts"]
    assert "towardsai.com" in data["allowedHosts"]
    assert "towardsai.com" in data["siteWideHosts"]
    assert "/academy/agent-engineering" in data["allowedPathsByHost"]["towardsai.com"]
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


def test_chat_returns_only_grounded_answer_and_cited_sources(monkeypatch) -> None:
    reset_limiters()
    prompts = []

    def fake_generate_grounded_answer(
        prompt: str, selected_pages: list[dict], **_kwargs
    ) -> GroundingResult:
        prompts.append(prompt)
        assert selected_pages
        cited = EvidenceChunk(
            chunk_id=str(selected_pages[0]["chunk_id"]),
            title=str(selected_pages[0]["title"]),
            url=str(selected_pages[0]["url"]),
            kind=str(selected_pages[0]["kind"]),
            headings=tuple(selected_pages[0].get("headings", [])),
            text=str(selected_pages[0]["text"]),
        )
        return GroundingResult(
            valid=True,
            status="answered",
            answer="Tell me your coding background and goal.",
            cited_chunks=(cited,),
            usage={"input_tokens": 10, "output_tokens": 8, "total_tokens": 18},
            latency_ms=123,
        )

    monkeypatch.setattr(
        api.llm, "generate_grounded_answer", fake_generate_grounded_answer
    )

    response = client.post("/api/helper/chat", json=payload(), headers=HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Tell me your coding background and goal."
    assert data["status"] == "answered"
    assert data["threadId"]
    assert data["sources"]
    assert data["usage"]["total_tokens"] == 18
    assert "Agent Engineering" in prompts[0]


def test_chat_still_accepts_legacy_net_origin(monkeypatch) -> None:
    reset_limiters()
    monkeypatch.setattr(
        api.llm,
        "generate_grounded_answer",
        lambda _prompt, selected, **_kwargs: GroundingResult(
            valid=True,
            status="answered",
            answer="Supported answer.",
            cited_chunks=(
                EvidenceChunk(
                    chunk_id=str(selected[0]["chunk_id"]),
                    title=str(selected[0]["title"]),
                    url=str(selected[0]["url"]),
                    kind=str(selected[0]["kind"]),
                    headings=(),
                    text=str(selected[0]["text"]),
                ),
            ),
        ),
    )

    response = client.post(
        "/api/helper/chat",
        json=payload(url="https://towardsai.net/b2b"),
        headers={"Origin": "https://towardsai.net"},
    )

    assert response.status_code == 200


def test_chat_abstains_without_retrieved_evidence(monkeypatch) -> None:
    reset_limiters()
    monkeypatch.setattr(api, "retrieve", lambda *_args, **_kwargs: [])

    def unexpected_model(*_args, **_kwargs):
        raise AssertionError("model must not run without retrieved evidence")

    monkeypatch.setattr(api.llm, "generate_grounded_answer", unexpected_model)

    response = client.post("/api/helper/chat", json=payload(), headers=HEADERS)

    assert response.status_code == 200
    assert_contact_handoff(response.json())
    assert "don't want to guess" in response.json()["answer"]


def test_chat_abstains_on_model_not_found_or_validation_failure(monkeypatch) -> None:
    reset_limiters()
    evidence = {
        "chunk_id": "mentorship-inclusions",
        "title": "Towards AI Mentorship",
        "url": "https://towardsai.com/academy/mentorship/",
        "kind": "mentorship",
        "headings": ["Course included"],
        "text": "10-Hour LLM Fundamentals video course — $199 — Included from day one.",
    }
    monkeypatch.setattr(api, "retrieve", lambda *_args, **_kwargs: [evidence])

    for grounded in (
        GroundingResult(valid=True, status="not_found"),
        GroundingResult(
            valid=False,
            status="validation_failure",
            validation_error="invented quote",
        ),
    ):
        monkeypatch.setattr(
            api.llm,
            "generate_grounded_answer",
            lambda *_args, result=grounded: result,
        )
        response = client.post("/api/helper/chat", json=payload(), headers=HEADERS)

        assert response.status_code == 200
        assert_contact_handoff(response.json())
        assert "don't want to guess" in response.json()["answer"]


def test_chat_abstains_when_model_omits_negation_from_an_evidence_span(
    monkeypatch,
) -> None:
    reset_limiters()
    selected = api.retrieve(FIRST_PROMPT)
    ai_work = next(page for page in selected if "No code required" in page["text"])
    raw = json.dumps(
        {
            "status": "answered",
            "claims": [
                {
                    "text": "code required.",
                    "chunk_id": ai_work["chunk_id"],
                    "quote": "code required",
                }
            ],
        }
    )
    monkeypatch.setattr(
        api.llm,
        "generate_answer",
        lambda _prompt: api.llm.LLMResult(answer=raw),
    )

    response = client.post("/api/helper/chat", json=payload(), headers=HEADERS)

    assert response.status_code == 200
    assert_contact_handoff(response.json())
    assert "don't want to guess" in response.json()["answer"]


@pytest.mark.parametrize(
    "query",
    [
        (
            "Do the 7 lessons in the Agent Engineering preview include "
            "lifetime access?"
        ),
        (
            "Do the 7 lessons in the Agent Engineering preview have a "
            "30-day refund guarantee?"
        ),
        "Do the 7 lessons in the Agent Engineering preview give a certificate?",
        "Do the 7 lessons in the Agent Engineering preview cost $499?",
        "Do the 7 lessons in the Agent Engineering preview get a 50% discount?",
    ],
)
def test_preview_count_cannot_borrow_other_paid_course_facts(
    monkeypatch, query: str
) -> None:
    reset_limiters()
    assert api.retrieve(query) == []

    def unexpected(*_args, **_kwargs):
        raise AssertionError("mixed preview facts must not invoke the model")

    monkeypatch.setattr(api.llm, "generate_grounded_answer", unexpected)
    request_payload = payload(query=query)
    request_payload["history"] = [{"role": "user", "content": FIRST_PROMPT}]

    response = client.post(
        "/api/helper/chat", json=request_payload, headers=HEADERS
    )

    assert response.status_code == 200
    assert_contact_handoff(response.json())


def test_preview_count_cannot_mask_an_unsupported_feature(monkeypatch) -> None:
    reset_limiters()
    query = (
        "Do the 7 lessons in the Agent Engineering preview include weekly "
        "code reviews?"
    )
    selected = api.retrieve(query)
    count_chunk = next(
        chunk
        for chunk in selected
        if any("7" in span["text"] for span in chunk["evidence_spans"])
    )
    count_span = next(
        span["text"]
        for span in count_chunk["evidence_spans"]
        if "7" in span["text"]
    )
    raw = json.dumps(
        {
            "status": "answered",
            "claims": [
                {
                    "text": count_span,
                    "chunk_id": count_chunk["chunk_id"],
                    "quote": count_span,
                }
            ],
        }
    )
    monkeypatch.setattr(
        api.llm,
        "generate_answer",
        lambda _prompt: api.llm.LLMResult(answer=raw),
    )
    request_payload = payload(query=query)
    request_payload["history"] = [{"role": "user", "content": FIRST_PROMPT}]

    response = client.post(
        "/api/helper/chat", json=request_payload, headers=HEADERS
    )

    assert response.status_code == 200
    assert_contact_handoff(response.json())


def test_mentorship_course_access_incident_uses_exact_retrieved_rows(
    monkeypatch,
) -> None:
    reset_limiters()

    def unexpected_model(*_args, **_kwargs):
        raise AssertionError("high-risk mentorship access answer must be extractive")

    monkeypatch.setattr(api.llm, "generate_grounded_answer", unexpected_model)
    request_payload = payload(
        query=(
            "The chatbot mentioned access to 2 courses of our choice as part of "
            "mentorship. Is that true?"
        ),
        url="https://towardsai.com/academy/mentorship/",
    )
    request_payload["history"] = [{"role": "user", "content": FIRST_PROMPT}]

    response = client.post("/api/helper/chat", json=request_payload, headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert "10-Hour LLM Fundamentals" in body["answer"]
    assert "Included from day one" in body["answer"]
    assert "25% off, always" in body["answer"]
    assert "two courses" not in body["answer"].lower()
    assert len(body["sources"]) == 1
    assert body["sources"][0]["url"] == ("https://towardsai.com/academy/mentorship/")
    assert body["sources"][0]["kind"] == "mentorship"


def test_enterprise_developer_conversion_uses_exact_public_capability(
    monkeypatch,
) -> None:
    reset_limiters()

    def unexpected_model(*_args, **_kwargs):
        raise AssertionError("explicit enterprise capability must be extractive")

    monkeypatch.setattr(api.llm, "generate_grounded_answer", unexpected_model)
    request_payload = payload(
        query=(
            "Can Towards AI train our software developers to become AI "
            "engineers?"
        ),
        url=(
            "https://towardsai.com/enterprise/"
            "software-developer-to-ai-engineer/"
        ),
    )
    request_payload["history"] = [
        {"role": "user", "content": "I want a training inside my company"}
    ]

    response = client.post("/api/helper/chat", json=request_payload, headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert "Every software developer, no AI background needed" in body["answer"]
    assert "design, evaluate, ship, and maintain production LLM systems" in body[
        "answer"
    ]
    assert {source["url"] for source in body["sources"]} == {
        (
            "https://towardsai.com/enterprise/"
            "software-developer-to-ai-engineer/"
        )
    }


def test_mentorship_cancellation_uses_exact_current_access_policy(
    monkeypatch,
) -> None:
    reset_limiters()

    def unexpected_model(*_args, **_kwargs):
        raise AssertionError("mentorship cancellation answer must be extractive")

    monkeypatch.setattr(api.llm, "generate_grounded_answer", unexpected_model)
    request_payload = payload(
        query=(
            "Do I keep LLM Fundamentals lifetime access after cancelling mentorship?"
        ),
        url="https://towardsai.com/academy/mentorship/",
    )
    request_payload["history"] = [{"role": "user", "content": FIRST_PROMPT}]

    response = client.post("/api/helper/chat", json=request_payload, headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert "Course access is active while your mentorship is active" in body["answer"]
    assert "If you cancel" in body["answer"]
    assert "lifetime access at a reduced price" in body["answer"]
    assert "Included from day one" not in body["answer"]
    assert {source["url"] for source in body["sources"]} == {
        "https://towardsai.com/academy/mentorship/"
    }


@pytest.mark.parametrize(
    "query",
    [
        "Does the monthly mentorship have a 30-day money-back guarantee?",
        "Does the month-to-month mentorship have a 30-day money-back guarantee?",
    ],
)
def test_monthly_mentorship_guarantee_names_the_yearly_qualification(
    monkeypatch, query: str
) -> None:
    reset_limiters()

    def unexpected_model(*_args, **_kwargs):
        raise AssertionError("mentorship guarantee answer must be extractive")

    monkeypatch.setattr(api.llm, "generate_grounded_answer", unexpected_model)
    request_payload = payload(
        query=query,
        url="https://towardsai.com/academy/mentorship/",
    )
    request_payload["history"] = [{"role": "user", "content": FIRST_PROMPT}]

    response = client.post("/api/helper/chat", json=request_payload, headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert "monthly mentorship can be cancelled at any time" in body["answer"]
    assert "yearly plan carries a 30-day money-back guarantee" in body["answer"]
    assert "Join the Mentorship 30-day" not in body["answer"]
    assert len(body["sources"]) == 1


def test_late_source_error_resets_answered_status_to_insufficient_evidence(
    monkeypatch,
) -> None:
    reset_limiters()
    selected = api.retrieve(FIRST_PROMPT)
    cited = EvidenceChunk(
        chunk_id=str(selected[0]["chunk_id"]),
        title=str(selected[0]["title"]),
        url=str(selected[0]["url"]),
        kind=str(selected[0]["kind"]),
        headings=tuple(selected[0].get("headings", [])),
        text=str(selected[0]["text"]),
    )
    monkeypatch.setattr(
        api.llm,
        "generate_grounded_answer",
        lambda *_args: GroundingResult(
            valid=True,
            status="answered",
            answer="Verified source span.",
            cited_chunks=(cited,),
        ),
    )
    monkeypatch.setattr(
        api,
        "sources_from_pages",
        lambda _pages: (_ for _ in ()).throw(RuntimeError("late source failure")),
    )

    response = client.post("/api/helper/chat", json=payload(), headers=HEADERS)

    assert response.status_code == 200
    assert_contact_handoff(response.json())
    assert "don't want to guess" in response.json()["answer"]


def test_prior_assistant_claim_is_not_added_to_retrieval_query(monkeypatch) -> None:
    reset_limiters()
    captured = []

    def fake_retrieve(query: str, **_kwargs):
        captured.append(query)
        return []

    monkeypatch.setattr(api, "retrieve", fake_retrieve)
    request_payload = payload(query="Is that true?")
    request_payload["history"] = [
        {"role": "user", "content": FIRST_PROMPT},
        {
            "role": "assistant",
            "content": "The mentorship includes two courses of your choice.",
        },
    ]

    response = client.post("/api/helper/chat", json=request_payload, headers=HEADERS)

    assert response.status_code == 200
    assert captured
    assert "two courses" not in captured[0].lower()
    assert response.json()["status"] == "insufficient_evidence"


def test_substantive_followup_drops_starter_prompt_from_retrieval(monkeypatch) -> None:
    reset_limiters()
    captured: list[str] = []
    query = "Does LLM Fundamentals include community support and an AI tutor?"

    def fake_retrieve(retrieval_query: str, **_kwargs):
        captured.append(retrieval_query)
        return []

    monkeypatch.setattr(api, "retrieve", fake_retrieve)
    request_payload = payload(query=query)
    request_payload["history"] = [{"role": "user", "content": FIRST_PROMPT}]

    response = client.post("/api/helper/chat", json=request_payload, headers=HEADERS)

    assert response.status_code == 200
    assert captured == [query]
    assert_contact_handoff(response.json())


def test_short_referential_followup_uses_only_last_substantive_user_turn(
    monkeypatch,
) -> None:
    reset_limiters()
    captured: list[str] = []

    def fake_retrieve(retrieval_query: str, **_kwargs):
        captured.append(retrieval_query)
        return []

    monkeypatch.setattr(api, "retrieve", fake_retrieve)
    request_payload = payload(query="What is its price?")
    request_payload["history"] = [
        {"role": "user", "content": FIRST_PROMPT},
        {"role": "user", "content": "Tell me about Agent Engineering."},
        {
            "role": "assistant",
            "content": "Unverified claim: it costs $1 and guarantees a job.",
        },
    ]

    response = client.post("/api/helper/chat", json=request_payload, headers=HEADERS)

    assert response.status_code == 200
    assert captured == ["Tell me about Agent Engineering.\nWhat is its price?"]
    assert "$1" not in captured[0]
    assert_contact_handoff(response.json())


def test_direct_contact_requests_bypass_retrieval_and_model(monkeypatch) -> None:
    reset_limiters()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("direct contact intent must not use retrieval or a model")

    monkeypatch.setattr(api, "retrieve", unexpected)
    monkeypatch.setattr(api.llm, "generate_grounded_answer", unexpected)
    request_payload = payload(query="Where is your contact form?")
    request_payload["history"] = [{"role": "user", "content": FIRST_PROMPT}]

    response = client.post("/api/helper/chat", json=request_payload, headers=HEADERS)

    assert response.status_code == 200
    assert_contact_handoff(response.json(), status="policy")


@pytest.mark.parametrize(
    "query",
    [
        "Does Agent Engineering free preview include lifetime access and require no card?",
        "Does the Full Stack free preview give me a certificate?",
        "Does Building LLMs for Production have a refund guarantee?",
        "How long is Agent Engineering?",
        "How many hours does Python for AI Engineering take?",
        "How many lessons are in LLM Fundamentals?",
        "Does mentorship include a certificate?",
        "Does the Get It All bundle get 50% off?",
        "What is the Get It All bundle price?",
        "Does monthly mentorship have a discount?",
    ],
)
def test_absent_offer_facts_go_directly_to_contact_form(
    monkeypatch, query: str
) -> None:
    reset_limiters()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("model must not run without target-qualified evidence")

    monkeypatch.setattr(api.llm, "generate_grounded_answer", unexpected)
    request_payload = payload(query=query)
    request_payload["history"] = [{"role": "user", "content": FIRST_PROMPT}]

    response = client.post("/api/helper/chat", json=request_payload, headers=HEADERS)

    assert response.status_code == 200
    assert_contact_handoff(response.json())


def test_coupon_answer_is_deterministic_and_does_not_call_model(monkeypatch) -> None:
    reset_limiters()

    def unexpected_generate_answer(
        _prompt: str, _selected: list[dict], **_kwargs
    ) -> GroundingResult:
        raise AssertionError("model should not be called for coupon intent")

    monkeypatch.setattr(api.llm, "generate_grounded_answer", unexpected_generate_answer)
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
    assert api.CONTACT_FORM_URL in first_response.json()["answer"]
    assert first_response.json()["status"] == "policy"
    assert second_response.status_code == 200
    assert api.CONTACT_FORM_URL in second_response.json()["answer"]


def test_rate_limit_is_hard(monkeypatch) -> None:
    api.visitor_limiter = FixedWindowRateLimiter((RateLimit("per_minute", 1, 60),))
    api.ip_limiter = FixedWindowRateLimiter((RateLimit("ip_per_minute", 100, 60),))
    api.global_limiter = FixedWindowRateLimiter(
        (RateLimit("global_per_minute", 100, 60),)
    )

    monkeypatch.setattr(
        api.llm,
        "generate_grounded_answer",
        lambda _prompt, selected, **_kwargs: GroundingResult(
            valid=True,
            status="answered",
            answer="Supported answer.",
            cited_chunks=(
                EvidenceChunk(
                    chunk_id=str(selected[0]["chunk_id"]),
                    title=str(selected[0]["title"]),
                    url=str(selected[0]["url"]),
                    kind=str(selected[0]["kind"]),
                    headings=(),
                    text=str(selected[0]["text"]),
                ),
            ),
        ),
    )

    first = client.post("/api/helper/chat", json=payload(), headers=HEADERS)
    second = client.post("/api/helper/chat", json=payload(), headers=HEADERS)

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) > 0


def test_healthz_reports_catalog_freshness_countdown() -> None:
    payload = client.get("/healthz").json()

    assert payload["status"] == "ok"
    catalog = payload["catalog"]
    assert catalog["fresh"] is True
    assert catalog["evidencePages"] > 0
    assert catalog["maxAgeDays"] > 0
    assert catalog["oldestFetchAgeDays"] is not None
    assert catalog["expiresInDays"] > 0


def test_healthz_reports_degraded_when_the_catalog_has_expired(monkeypatch) -> None:
    """An expired catalog leaves the API up but unable to answer anything.

    /healthz must stay 200 so the Space is not restarted for a container that
    is fine, while still saying plainly that there is no evidence left.
    """

    expired = dataclasses.replace(
        catalog_module.settings, catalog_max_age_days=0
    )
    monkeypatch.setattr(catalog_module, "settings", expired)

    response = client.get("/healthz")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "degraded"
    assert payload["catalog"]["fresh"] is False
    assert payload["catalog"]["evidencePages"] == 0
    assert payload["catalog"]["expiresInDays"] <= 0
