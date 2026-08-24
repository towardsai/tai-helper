from __future__ import annotations

import json
from urllib.parse import urlparse

import pytest

from tai_helper import llm
from tai_helper.catalog import pages, retrieve
from tai_helper.settings import repo_root

CURRENT_COM_URLS = {
    "https://towardsai.com/",
    "https://towardsai.com/academy/",
    "https://towardsai.com/academy/full-stack-ai-engineering/",
    "https://towardsai.com/academy/agent-engineering/",
    "https://towardsai.com/academy/llm-primer/",
    "https://towardsai.com/academy/python-for-ai-engineering/",
    "https://towardsai.com/academy/ai-for-work/",
    "https://towardsai.com/academy/building-llms-for-production/",
    "https://towardsai.com/academy/bundles/",
    "https://towardsai.com/academy/mentorship/",
    "https://towardsai.com/academy/about/",
    "https://towardsai.com/academy/contact/",
    "https://towardsai.com/contribute/",
    "https://towardsai.com/enterprise/software-developer-to-ai-engineer/",
    "https://towardsai.com/enterprise/agentic-developer-conversion/",
    "https://towardsai.com/academy/affiliate/",
    "https://towardsai.com/academy/agent-engineering-free-preview/",
    "https://towardsai.com/academy/full-stack-ai-engineering-free-preview/",
    "https://towardsai.com/academy/book/",
    "https://towardsai.com/academy/bundles/get-it-all/",
    (
        "https://towardsai.com/academy/bundles/"
        "from-coding-novice-to-advanced-llm-developer/"
    ),
    (
        "https://towardsai.com/academy/bundles/"
        "10-hour-crash-course-into-llm-developer-expert/"
    ),
    "https://towardsai.com/enterpriseenablement/",
    "https://towardsai.com/valuecreation/",
    "https://towardsai.com/valuecreation/careers/",
    "https://towardsai.com/valuecreation/deployment-strategist/",
    "https://towardsai.com/valuecreation/junior-ai-engineer/",
    "https://towardsai.com/valuecreation/senior-ai-engineer/",
    "https://towardsai.com/theaitastegap/",
    "https://towardsai.com/webinars/agentengineering/",
}


def _catalog(name: str) -> dict:
    return json.loads((repo_root() / "data" / name).read_text())


def _page_text(url: str) -> str:
    matching = [page for page in pages() if page["url"] == url]
    assert len(matching) == 1, f"expected one active canonical page for {url}"
    return matching[0]["text"].lower()


def test_live_refresh_scans_every_current_towardsai_com_page() -> None:
    catalog = _catalog("towardsai_com_pages.json")

    assert {page["discovered_url"] for page in catalog["pages"]} == CURRENT_COM_URLS
    assert {page["url"] for page in catalog["pages"]} == CURRENT_COM_URLS
    assert catalog["status_counts"] == {"excluded": 3, "included": 27}
    excluded_urls = {
        page["url"] for page in catalog["pages"] if not page["retrieval_eligible"]
    }
    assert excluded_urls == {
        "https://towardsai.com/",
        "https://towardsai.com/academy/",
        "https://towardsai.com/academy/bundles/",
    }


def test_academy_refresh_scans_sitemap_and_excludes_unsafe_pages() -> None:
    catalog = _catalog("pages.json")
    academy_pages = [
        page
        for page in catalog["pages"]
        if page["discovered_url"].startswith("https://academy.towardsai.net")
    ]
    excluded_paths = {
        urlparse(page["discovered_url"]).path.rstrip("/") or "/"
        for page in academy_pages
        if not page["retrieval_eligible"]
    }

    # Lower bound, not an exact count: the Academy publishes new pages between
    # refreshes, and an exact total turns every legitimate addition into a red
    # build. The guard that matters is that a truncated or failed scan cannot
    # pass, and that the known-unsafe paths below stay excluded.
    assert len(academy_pages) >= 28
    assert {
        "/",
        "/pages/agent-course-landing-page",
        "/pages/towards-ai-insider",
        "/pages/agent-course-new-page-cro",
        "/pages/webinar",
        "/pages/new-home-page",
        "/pages/landing-page-free-email-course",
        "/pages/choose-your-course",
        "/collections",
        "/collections/products",
        "/collections/developers",
        "/collections/professionals",
        "/pages/free-resources",
    } <= excluded_paths
    assert not any(
        page["retrieval_eligible"]
        for page in catalog["pages"]
        if page["authority"] == "curated_external"
    )


def test_every_evidence_page_has_fresh_provenance_and_real_chunks() -> None:
    for filename in ("towardsai_com_pages.json", "pages.json"):
        for page in _catalog(filename)["pages"]:
            if not page["retrieval_eligible"]:
                continue
            assert page["status"] == "included"
            assert page["fetched_at"]
            assert len(page["content_hash"]) == 64
            assert page["http_status"] == 200
            assert page["chunks"]
            assert all(chunk["chunk_id"] and chunk["text"] for chunk in page["chunks"])
            assert all(len(chunk["text"]) <= 1800 for chunk in page["chunks"])
            assert all(chunk["evidence_spans"] for chunk in page["chunks"])
            assert all(
                span["text"] in " ".join(chunk["text"].split())
                for chunk in page["chunks"]
                for span in chunk["evidence_spans"]
            )


@pytest.mark.parametrize(
    ("url", "facts"),
    [
        (
            "https://towardsai.com/academy/full-stack-ai-engineering/",
            ("$349 one-time", "92 lessons", "60+ hrs"),
        ),
        (
            "https://towardsai.com/academy/agent-engineering/",
            ("$499 one-time", "35 lessons", "two production agents"),
        ),
        (
            "https://towardsai.com/academy/llm-primer/",
            ("$199 one-time", "5 in-depth 2-hour video sessions"),
        ),
        (
            "https://towardsai.com/academy/python-for-ai-engineering/",
            ("$149 one-time", "38 lessons", "complete beginners welcome"),
        ),
        (
            "https://towardsai.com/academy/ai-for-work/",
            ("$399 one-time", "98 lessons", "no code required"),
        ),
        (
            "https://towardsai.com/academy/building-llms-for-production/",
            ("$29.99", "470-page", "84 lessons"),
        ),
        (
            "https://towardsai.com/academy/mentorship/",
            (
                "10-hour llm fundamentals video course",
                "included from day one",
                "25% off, always",
            ),
        ),
        (
            "https://towardsai.com/academy/bundles/get-it-all/",
            ("6 products in the bundle", "$1,625 combined price"),
        ),
        (
            (
                "https://towardsai.com/academy/bundles/"
                "from-coding-novice-to-advanced-llm-developer/"
            ),
            ("$599 bundle price, was $727", "4 products"),
        ),
        (
            (
                "https://towardsai.com/academy/bundles/"
                "10-hour-crash-course-into-llm-developer-expert/"
            ),
            ("$948 bundle price, was $1,078", "4 products"),
        ),
        (
            "https://towardsai.com/academy/agent-engineering-free-preview/",
            ("free preview · 7 full lessons",),
        ),
        (
            "https://towardsai.com/academy/full-stack-ai-engineering-free-preview/",
            ("free preview lessons · no card required", "instant access"),
        ),
    ],
)
def test_current_course_and_bundle_facts_are_present(
    url: str, facts: tuple[str, ...]
) -> None:
    text = _page_text(url)

    for fact in facts:
        assert fact in text


@pytest.mark.parametrize(
    ("query", "expected_url"),
    [
        (
            "What is included in the Full Stack AI Engineering course and what does it cost?",
            "https://towardsai.com/academy/full-stack-ai-engineering/",
        ),
        (
            "How many lessons and what price is the Agent Engineering course?",
            "https://towardsai.com/academy/agent-engineering/",
        ),
        (
            "What is the 10-Hour LLM Fundamentals course price?",
            "https://towardsai.com/academy/llm-primer/",
        ),
        (
            "Is Beginner Python for AI Engineering for non-coders?",
            "https://towardsai.com/academy/python-for-ai-engineering/",
        ),
        (
            "What is Master AI for Work for professionals?",
            "https://towardsai.com/academy/ai-for-work/",
        ),
        (
            "What is the Building LLMs for Production course and ebook?",
            "https://towardsai.com/academy/building-llms-for-production/",
        ),
        (
            "Where are the Building LLMs book companion resources?",
            "https://towardsai.com/academy/book/",
        ),
        (
            "What course is included in mentorship?",
            "https://towardsai.com/academy/mentorship/",
        ),
        (
            "What does the Get It All bundle include?",
            "https://towardsai.com/academy/bundles/get-it-all/",
        ),
        (
            "What is in the From Non-Coder to AI Engineer bundle?",
            (
                "https://towardsai.com/academy/bundles/"
                "from-coding-novice-to-advanced-llm-developer/"
            ),
        ),
        (
            "What is in the From Developer to Advanced AI Engineer bundle?",
            (
                "https://towardsai.com/academy/bundles/"
                "10-hour-crash-course-into-llm-developer-expert/"
            ),
        ),
        (
            "Where is the Full Stack free course preview?",
            "https://towardsai.com/academy/full-stack-ai-engineering-free-preview/",
        ),
        (
            "How many Agent Engineering free preview lessons are there?",
            "https://towardsai.com/academy/agent-engineering-free-preview/",
        ),
        (
            "Where is the free Agent Engineering webinar?",
            "https://towardsai.com/webinars/agentengineering/",
        ),
        (
            "Where can I get the free agents cheatsheet?",
            (
                "https://academy.towardsai.net/products/"
                "digital_downloads/agents-cheatsheet"
            ),
        ),
        (
            "Where can I get the Anti-Slop Framework?",
            (
                "https://academy.towardsai.net/products/"
                "digital_downloads/anti-slop-framework"
            ),
        ),
        (
            "What enterprise AI enablement and training do you offer?",
            "https://towardsai.com/enterpriseenablement/",
        ),
        (
            "Can you convert software developers into AI engineers?",
            ("https://towardsai.com/enterprise/software-developer-to-ai-engineer/"),
        ),
        (
            "Do you offer Claude Code and Codex training?",
            ("https://towardsai.com/enterprise/agentic-developer-conversion/"),
        ),
        (
            "Do you do AI deployment value creation consulting?",
            "https://towardsai.com/valuecreation/",
        ),
    ],
)
def test_every_current_offer_routes_to_its_canonical_page(
    query: str, expected_url: str
) -> None:
    selected = retrieve(query)

    assert selected, query
    assert selected[0]["url"] == expected_url


def test_course_decider_starter_returns_one_canonical_hero_per_course() -> None:
    selected = retrieve("I want help deciding which course to take.")

    assert len(selected) == 6
    assert len({page["url"] for page in selected}) == 6
    assert all(page["chunk_index"] == 0 for page in selected)
    assert {page["path"] for page in selected} == {
        "/academy/full-stack-ai-engineering",
        "/academy/agent-engineering",
        "/academy/llm-primer",
        "/academy/python-for-ai-engineering",
        "/academy/ai-for-work",
        "/academy/building-llms-for-production",
    }
    assert len(llm.evidence_chunks(selected)) == len(selected)


def test_company_starters_return_only_canonical_b2b_evidence() -> None:
    integration = retrieve("I want help to integrate AI into my company")
    training = retrieve("I want a training inside my company")

    assert integration[0]["path"] == "/valuecreation"
    assert integration[1]["path"] == "/enterpriseenablement"
    assert all(page["kind"] == "b2b" for page in integration)
    assert training[0]["path"] == "/enterpriseenablement"
    assert all(page["kind"] == "b2b" for page in training)


def test_free_resource_starter_does_not_retrieve_paid_offer_evidence() -> None:
    selected = retrieve(
        "I'm looking for more free resources to learn before committing to buying "
        "a course"
    )

    assert selected
    assert selected[0]["kind"] == "free_resource"
    assert all(
        page["kind"] in {"free_resource", "digital_download"}
        or page["path"] == "/academy/book"
        for page in selected
    )
    assert len(llm.evidence_chunks(selected)) == len(selected)


def test_mentor_starter_returns_only_mentorship_evidence() -> None:
    selected = retrieve("I want to find mentors")

    assert selected
    assert all(page["path"] == "/academy/mentorship" for page in selected)


def test_canonical_offer_pages_suppress_lower_authority_mirrors() -> None:
    com_offer_ids = {
        page["offer_id"]
        for page in _catalog("towardsai_com_pages.json")["pages"]
        if page.get("offer_id")
    }

    for page in pages():
        if page.get("offer_id") in com_offer_ids:
            assert page["authority"] == "official_site"


def test_mentorship_incident_is_answered_only_from_exact_current_evidence() -> None:
    selected = retrieve(
        "The chatbot mentioned access to 2 courses of our choice as part of "
        "mentorship. Is that true?",
        current_url="https://towardsai.com/academy/mentorship/",
    )

    assert selected[0]["url"] == "https://towardsai.com/academy/mentorship/"
    assert "Included from day one" in selected[0]["text"]
    quote = (
        "10-Hour LLM Fundamentals video course Five in-depth 2-hour video "
        "sessions, from a basic prompt to a full production rollout $199 "
        "Included from day one"
    )
    claim = f"{quote}."
    raw = json.dumps(
        {
            "status": "answered",
            "claims": [
                {
                    "text": claim,
                    "chunk_id": selected[0]["chunk_id"],
                    "quote": quote,
                }
            ],
        }
    )

    result = llm.validate_grounded_result(raw, selected)

    assert result.is_answered
    assert result.answer == claim
    assert "two courses" not in result.answer.lower()


def test_no_active_chunk_contains_the_retired_two_course_offer() -> None:
    retired_phrases = (
        "two courses included",
        "pick one from these options",
        "ai coding: a fixed course",
    )
    active_text = "\n".join(
        chunk["text"] for page in pages() for chunk in page["chunks"]
    ).lower()

    assert not any(phrase in active_text for phrase in retired_phrases)
    assert not any(
        page["url"] == "https://towardsai.com/academy/membership/" for page in pages()
    )


def test_stale_academy_summaries_are_not_retrieval_evidence() -> None:
    blocked_urls = {
        "https://towardsai.com/",
        "https://towardsai.com/academy/",
        "https://towardsai.com/academy/bundles/",
        "https://academy.towardsai.net/collections",
        "https://academy.towardsai.net/collections/products",
        "https://academy.towardsai.net/collections/developers",
        "https://academy.towardsai.net/collections/professionals",
        "https://academy.towardsai.net/pages/free-resources",
    }
    active_pages = pages()
    active_urls = {page["url"] for page in active_pages}
    active_text = "\n".join(page["text"] for page in active_pages).lower()

    assert blocked_urls.isdisjoint(active_urls)
    assert "124 lessons" not in active_text
    assert "free resources from 8-hour llm primer" not in active_text
    assert "465-page reference" not in active_text


def test_navigation_and_announcement_boilerplate_is_not_evidence() -> None:
    active_text = "\n".join(page["text"] for page in pages()).lower()

    assert "new: towards ai mentorship" not in active_text
    assert "skip to main content" not in active_text
    assert "toggle menu" not in active_text


@pytest.mark.parametrize(
    ("query", "expected_url", "retired_fact"),
    [
        (
            "How many lessons are in Full Stack AI Engineering?",
            "https://towardsai.com/academy/full-stack-ai-engineering/",
            "124 lessons",
        ),
        (
            "How many lessons are in Agent Engineering?",
            "https://towardsai.com/academy/agent-engineering/",
            "50 lessons",
        ),
        (
            "Do you have an 8-hour LLM Primer?",
            "https://towardsai.com/academy/llm-primer/",
            "8-hour llm primer",
        ),
    ],
)
def test_named_offer_queries_use_current_canonical_evidence(
    query: str, expected_url: str, retired_fact: str
) -> None:
    selected = retrieve(query)

    assert selected
    assert selected[0]["url"] == expected_url
    assert retired_fact not in "\n".join(page["text"] for page in selected).lower()


def test_book_page_count_is_an_answerable_atomic_span() -> None:
    selected = retrieve("How many pages is Building LLMs for Production?")

    assert selected
    assert selected[0]["url"] == (
        "https://towardsai.com/academy/building-llms-for-production/"
    )
    assert any("470-page" in span["text"] for span in selected[0]["evidence_spans"])


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
    ],
)
def test_unpublished_high_risk_offer_facts_have_no_citable_evidence(
    query: str,
) -> None:
    assert retrieve(query) == []


def test_named_llm_fundamentals_feature_query_cannot_retrieve_another_offer() -> None:
    selected = retrieve(
        "Does LLM Fundamentals include community support and an AI tutor?"
    )

    assert selected
    assert {chunk["offer_id"] for chunk in selected} == {"llm-primer"}
    assert any(
        "community" in span["text"].casefold()
        and "ai tutor" in span["text"].casefold()
        for chunk in selected
        for span in chunk["evidence_spans"]
    )


def test_get_it_all_exact_price_abstains_when_only_checkout_policy_is_published() -> None:
    assert retrieve("What is the Get It All bundle price?") == []

    location = retrieve("Where is the Get It All bundle price shown at checkout?")
    spans = [
        span["text"]
        for chunk in location
        for span in chunk.get("evidence_spans", [])
    ]
    assert location
    assert {chunk["offer_id"] for chunk in location} == {"get-it-all"}
    assert spans
    assert all("Bundle price shown at checkout" in span for span in spans)
    assert all("$1,625" not in span and "$948" not in span for span in spans)


def test_full_stack_preview_count_uses_only_explicit_preview_count_evidence() -> None:
    selected = retrieve("How many Full Stack free preview lessons are there?")
    spans = [
        span["text"]
        for chunk in selected
        for span in chunk.get("evidence_spans", [])
    ]

    assert selected
    assert {chunk["offer_id"] for chunk in selected} <= {
        "full-stack-ai-engineering-free-preview",
        "full-stack-ai-engineering",
    }
    assert spans
    assert all("6" in span or "six" in span.casefold() for span in spans)
    assert all("92 lessons" not in span for span in spans)


def test_preview_count_exception_never_exposes_paid_access_evidence() -> None:
    selected = retrieve("How many Agent Engineering preview lessons are there?")
    evidence = [
        span["text"].casefold()
        for chunk in selected
        for span in chunk["evidence_spans"]
    ]

    assert selected
    assert any("7" in span and "lesson" in span for span in evidence)
    assert all("lifetime access" not in span for span in evidence)


@pytest.mark.parametrize(
    "query",
    [
        (
            "How many Agent Engineering preview lessons are there, and what does "
            "the full course cost?"
        ),
        (
            "How many Full Stack preview lessons are there, and does the full "
            "course include lifetime access?"
        ),
    ],
)
def test_mixed_preview_and_paid_fact_questions_fail_closed(query: str) -> None:
    assert retrieve(query) == []


def test_lifetime_access_requires_an_explicit_permanent_access_qualifier() -> None:
    selected = retrieve("Does the Full Stack free preview include lifetime access?")
    evidence = [
        span["text"].casefold()
        for chunk in selected
        for span in chunk["evidence_spans"]
    ]

    assert selected
    assert evidence
    assert all(
        any(term in span for term in ("lifetime", "forever", "keep", "retain"))
        for span in evidence
    )


def test_mentorship_cancellation_retrieves_only_the_exact_access_policy() -> None:
    selected = retrieve(
        "Do I keep LLM Fundamentals lifetime access after cancelling mentorship?"
    )
    spans = {
        span["text"]
        for chunk in selected
        for span in chunk.get("evidence_spans", [])
    }

    assert selected
    assert {chunk["offer_id"] for chunk in selected} == {"mentorship"}
    assert any("Course access is active while" in span for span in spans)
    assert any("If you cancel" in span and "lifetime access" in span for span in spans)
    assert all("Included from day one" not in span for span in spans)


@pytest.mark.parametrize(
    "query",
    [
        "Does the monthly mentorship plan have a 30-day money-back guarantee?",
        "Does the month-to-month mentorship have a 30-day money-back guarantee?",
    ],
)
def test_monthly_mentorship_guarantee_retrieves_both_plan_qualifiers(
    query: str,
) -> None:
    selected = retrieve(query)
    spans = {
        span["text"]
        for chunk in selected
        for span in chunk.get("evidence_spans", [])
    }

    assert selected
    assert any("monthly mentorship" in span.casefold() for span in spans)
    assert any(
        "yearly" in span.casefold() and "money-back" in span.casefold()
        for span in spans
    )
    assert all("Join the Mentorship 30-day" not in span for span in spans)


def test_mentorship_plan_prices_require_exact_plan_denominations() -> None:
    monthly_queries = (
        "What is the monthly mentorship price?",
        "Mentorship month price?",
        "What is the month-to-month mentorship price?",
        "What is the mentorship price per month?",
        "What does mentorship cost each month?",
    )
    monthly_results = [
        [
            span["text"]
            for chunk in retrieve(query)
            for span in chunk["evidence_spans"]
        ]
        for query in monthly_queries
    ]
    yearly_queries = (
        "What is the yearly mentorship price?",
        "Mentorship year price?",
        "What is the annual mentorship price?",
        "What is the mentorship price per year?",
    )
    yearly_results = [
        [
            span["text"]
            for chunk in retrieve(query)
            for span in chunk["evidence_spans"]
        ]
        for query in yearly_queries
    ]

    assert all(monthly_results)
    for monthly in monthly_results:
        assert all("Guest workshop monthly" not in span for span in monthly)
        assert all("Production blueprint monthly" not in span for span in monthly)
        assert all("From $75/month" not in span for span in monthly)
        assert any("$99" in span for span in monthly)
    assert all(yearly_results)
    for yearly in yearly_results:
        assert all("$289 off" not in span for span in yearly)
        assert all("$75 a month billed yearly" not in span for span in yearly)
        assert any("$899" in span and "/year" in span for span in yearly)


def test_mentorship_discounts_are_bound_to_the_requested_plan_or_courses() -> None:
    yearly = [
        span["text"]
        for chunk in retrieve("Is the yearly mentorship plan 24% off?")
        for span in chunk["evidence_spans"]
    ]
    saved = [
        span["text"]
        for chunk in retrieve("Does mentorship save 24%?")
        for span in chunk["evidence_spans"]
    ]
    courses = [
        span["text"]
        for chunk in retrieve(
            "What discount does mentorship give on Full Stack AI Engineering?"
        )
        for span in chunk["evidence_spans"]
    ]

    assert yearly
    assert all(
        "save 24%" in span.casefold() or "24% less" in span.casefold()
        for span in yearly
    )
    assert all("25% off" not in span for span in yearly)
    assert saved
    assert all(
        "save 24%" in span.casefold() or "24% less" in span.casefold()
        for span in saved
    )
    assert courses
    assert all("25% off" in span for span in courses)
    assert retrieve("Does monthly mentorship have a discount?") == []


def test_mentorship_access_and_features_exclude_comparison_entities() -> None:
    access = [
        span["text"]
        for chunk in retrieve("Does mentorship include lifetime course access?")
        for span in chunk["evidence_spans"]
    ]
    reviews = [
        span["text"]
        for chunk in retrieve("Does mentorship include resume and project reviews?")
        for span in chunk["evidence_spans"]
    ]

    assert access
    assert all("retainers" not in span.casefold() for span in access)
    assert any("lifetime access" in span.casefold() for span in access)
    assert reviews
    assert any(
        "resume" in span.casefold()
        and "project" in span.casefold()
        and "reviews" in span.casefold()
        for span in reviews
    )
    assert all("single mentor" not in span.casefold() for span in reviews)
