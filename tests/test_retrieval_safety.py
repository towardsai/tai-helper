from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tai_helper import api, catalog, llm
from tai_helper.schemas import HelperChatRequest


def _page(
    *,
    slug: str = "agent-engineering",
    text: str = "Build production-ready AI agents with practical engineering lessons.",
    fetched_at: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    fetched_at = fetched_at or datetime.now(UTC).isoformat()
    page: dict[str, Any] = {
        "url": f"https://towardsai.com/academy/{slug}/",
        "canonical_url": f"https://towardsai.com/academy/{slug}/",
        "host": "towardsai.com",
        "path": f"/academy/{slug}",
        "title": slug.replace("-", " ").title(),
        "kind": "course",
        "status": "included",
        "retrieval_eligible": True,
        "authority": "canonical_offer",
        "fetched_at": fetched_at,
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "http_status": 200,
        "text": text,
        "chunks": [
            {
                "chunk_id": f"{slug}:overview",
                "heading": "Overview",
                "text": text,
            }
        ],
    }
    page.update(overrides)
    return page


@pytest.fixture(autouse=True)
def clear_caches_between_tests() -> None:
    catalog.clear_catalog_caches()
    yield
    catalog.clear_catalog_caches()


@pytest.fixture
def install_catalog(monkeypatch: pytest.MonkeyPatch):
    def install(*pages: dict[str, Any]) -> None:
        monkeypatch.setattr(
            catalog,
            "pages_payload",
            lambda: {"pages": list(pages), "generated_at": {}},
        )
        catalog.clear_catalog_caches()

    return install


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("remove", "status"),
        ("set_status", "review_pending"),
    ],
    ids=["missing-status", "unknown-status"],
)
def test_only_explicit_active_status_can_supply_evidence(
    install_catalog, mutation: str, value: str
) -> None:
    valid = _page(slug="valid-course", text="Valid course teaches glacier models.")
    invalid = _page(slug="invalid-course", text="Invalid course teaches zeppelins.")
    if mutation == "remove":
        invalid.pop(value)
    else:
        invalid["status"] = value
    install_catalog(valid, invalid)

    assert [page["url"] for page in catalog.pages()] == [valid["url"]]
    assert catalog.retrieve("zeppelins") == []


@pytest.mark.parametrize("eligible", [None, False], ids=["missing", "false"])
def test_retrieval_eligibility_must_be_explicitly_true(
    install_catalog, eligible: bool | None
) -> None:
    page = _page(text="A course about orbital pottery.")
    if eligible is None:
        page.pop("retrieval_eligible")
    else:
        page["retrieval_eligible"] = eligible
    install_catalog(page)

    assert catalog.pages() == []
    assert catalog.retrieve("orbital pottery course") == []


@pytest.mark.parametrize(
    "fetched_at",
    [
        None,
        (
            datetime.now(UTC)
            - timedelta(days=max(catalog.settings.catalog_max_age_days, 0) + 1)
        ).isoformat(),
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    ],
    ids=["missing", "stale", "future"],
)
def test_missing_stale_or_future_fetch_time_cannot_supply_evidence(
    install_catalog, fetched_at: str | None
) -> None:
    page = _page(text="A course about lunar basket weaving.")
    if fetched_at is None:
        page.pop("fetched_at")
    else:
        page["fetched_at"] = fetched_at
    install_catalog(page)

    assert catalog.pages() == []
    assert catalog.retrieve("lunar basket weaving course") == []


def test_corrupt_catalog_reload_discards_previously_cached_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    academy_path = data_dir / "pages.json"
    website_path = data_dir / "towardsai_com_pages.json"
    academy_path.write_text(json.dumps({"pages": []}))
    website_path.write_text(
        json.dumps({"pages": [_page(text="Quantum origami course.")]})
    )
    monkeypatch.setattr(catalog, "repo_root", lambda: tmp_path)
    catalog.clear_catalog_caches()

    assert [page["url"] for page in catalog.pages()] == [
        "https://towardsai.com/academy/agent-engineering/"
    ]

    website_path.write_text("{ definitely not valid JSON")

    assert catalog.pages() == []
    assert catalog.retrieve("quantum origami course") == []


@pytest.mark.parametrize(
    "query",
    [
        "Does your course include scuba-diving lessons?",
        "Can company training certify helicopter pilots?",
        "Does the mentorship provide veterinary surgery?",
    ],
)
def test_unsupported_but_in_scope_subjects_return_no_chunks(
    install_catalog, query: str
) -> None:
    install_catalog(
        _page(text="This AI engineering course covers agents and deployment."),
    )

    assert catalog.in_scope(query)
    assert catalog.retrieve(query) == []


def test_punctuation_and_hyphens_do_not_break_relevant_retrieval(
    install_catalog,
) -> None:
    page = _page(
        text="The course teaches production-ready agent-engineering workflows in C++ and C#.",
    )
    install_catalog(page)

    assert {
        "production",
        "ready",
        "agent",
        "engineering",
        "c++",
        "c#",
    } <= catalog.tokenize("production-ready agent-engineering C++/C#")
    selected = catalog.retrieve("Is it production-ready for agent engineering?")

    assert selected
    assert selected[0]["url"] == page["url"]


def test_scope_uses_history_only_for_referential_followups() -> None:
    course_history = ["Tell me about the Towards AI mentorship and its courses."]

    assert catalog.in_scope("Is it included?", course_history)
    assert not catalog.in_scope("Who won the World Cup?", course_history)
    assert not catalog.in_scope("Is it included?", ["Who won the World Cup?"])


def test_retrieval_query_never_uses_prior_assistant_claims_as_evidence() -> None:
    payload = HelperChatRequest.model_validate(
        {
            "query": "Is that accurate?",
            "selectedPrompt": "I want to find mentors",
            "history": [
                {
                    "role": "assistant",
                    "content": "The mentorship includes two courses of your choice.",
                },
                {"role": "user", "content": "Tell me about mentorship."},
            ],
            "context": {"url": "https://towardsai.com/academy/mentorship/"},
        }
    )

    retrieval_query = api._retrieval_query(payload)

    assert "two courses" not in retrieval_query
    assert "Tell me about mentorship" in retrieval_query
    assert "Is that accurate" in retrieval_query


def test_api_exposes_only_sources_for_chunks_cited_by_validated_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = [
        {
            "chunk_id": "course-a:overview",
            "title": "Course A",
            "url": "https://towardsai.com/academy/course-a/",
            "kind": "course",
            "headings": ["Overview"],
            "text": "Course A is available.",
        },
        {
            "chunk_id": "course-b:pricing",
            "title": "Course B",
            "url": "https://towardsai.com/academy/course-b/",
            "kind": "course",
            "headings": ["Pricing"],
            "text": "Course B costs $20.",
        },
    ]
    cited = llm.EvidenceChunk(
        chunk_id="course-b:pricing",
        title="Course B",
        url="https://towardsai.com/academy/course-b/",
        kind="course",
        headings=("Pricing",),
        text="Course B costs $20.",
    )
    grounded = llm.GroundingResult(
        valid=True,
        status="answered",
        answer="Course B costs $20.",
        claims=(
            llm.GroundedClaim(
                text="Course B costs $20.",
                chunk_id="course-b:pricing",
                quote="Course B costs $20.",
            ),
        ),
        cited_chunks=(cited,),
    )
    monkeypatch.setattr(api, "page_is_allowed", lambda _url: True)
    monkeypatch.setattr(api, "in_scope", lambda _query, _history: True)
    monkeypatch.setattr(api, "_check_rate_limits", lambda _request, _payload: None)
    monkeypatch.setattr(api, "_schedule_monitor", lambda _monitor: None)
    monkeypatch.setattr(
        api,
        "retrieve",
        lambda _query, *, current_url="", limit=7: selected,
    )
    monkeypatch.setattr(api.llm, "build_prompt", lambda **_kwargs: "prompt")
    monkeypatch.setattr(
        api.llm,
        "generate_grounded_answer",
        lambda _prompt, _selected: grounded,
    )

    response = TestClient(api.app).post(
        "/api/helper/chat",
        headers={"Origin": "https://towardsai.com"},
        json={
            "query": "I want help deciding which course to take.",
            "selectedPrompt": "I want help deciding which course to take.",
            "visitorId": "retrieval-safety-test",
            "history": [],
            "context": {
                "url": "https://towardsai.com/academy/course-b/",
                "pageTitle": "Course B",
                "signedIn": False,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert response.json()["sources"] == [
        {
            "title": "Course B",
            "url": "https://towardsai.com/academy/course-b/",
            "kind": "course",
        }
    ]
