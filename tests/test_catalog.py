from __future__ import annotations

import pytest

from tai_helper import catalog
from tai_helper.catalog import (
    allowed_paths_by_host,
    coupon_followup,
    coupon_intent,
    forced_prompts,
    in_scope,
    page_is_allowed,
    pages,
    retrieve,
    sources_from_pages,
)

CANONICAL_OFFER_RETRIEVAL_CASES = (
    (
        "Full Stack AI Engineering production LLM product course",
        "https://towardsai.com/academy/full-stack-ai-engineering/",
    ),
    (
        "Agent Engineering production AI agents course",
        "https://towardsai.com/academy/agent-engineering/",
    ),
    (
        "10-Hour LLM Fundamentals video crash course",
        "https://towardsai.com/academy/llm-primer/",
    ),
    (
        "Beginner Python for AI Engineering LLM-native course",
        "https://towardsai.com/academy/python-for-ai-engineering/",
    ),
    (
        "Master AI for Work no-code professionals course",
        "https://towardsai.com/academy/ai-for-work/",
    ),
    (
        "Building LLMs for Production ebook taught as a course",
        "https://towardsai.com/academy/building-llms-for-production/",
    ),
    (
        "Get It All every course one bundle",
        "https://towardsai.com/academy/bundles/get-it-all/",
    ),
    (
        "From Non-Coder to AI Engineer course bundle",
        "https://towardsai.com/academy/bundles/from-coding-novice-to-advanced-llm-developer/",
    ),
    (
        "From Developer to Advanced AI Engineer course bundle",
        "https://towardsai.com/academy/bundles/10-hour-crash-course-into-llm-developer-expert/",
    ),
    (
        "Towards AI Mentorship senior engineers on call",
        "https://towardsai.com/academy/mentorship/",
    ),
    (
        "Agent Engineering course preview 7 free lessons",
        "https://towardsai.com/academy/agent-engineering-free-preview/",
    ),
    (
        "Full Stack AI Engineering free preview lessons",
        "https://towardsai.com/academy/full-stack-ai-engineering-free-preview/",
    ),
    (
        "Agentic AI engineering webinar",
        "https://towardsai.com/webinars/agentengineering/",
    ),
    (
        "Towards AI free Building LLMs book resources and learning toolkit",
        "https://towardsai.com/academy/book/",
    ),
    (
        "Towards AI ultimate agents cheatsheet digital download",
        "https://academy.towardsai.net/products/digital_downloads/agents-cheatsheet",
    ),
    (
        "Anti-slop framework digital download",
        "https://academy.towardsai.net/products/digital_downloads/anti-slop-framework",
    ),
    (
        "Building AI for Production book resources and links",
        "https://towardsai.com/academy/book/",
    ),
    (
        "The AI Taste Gap",
        "https://towardsai.com/theaitastegap/",
    ),
    (
        "Claude Code Codex one-day agentic developer bootcamp team training",
        "https://towardsai.com/enterprise/agentic-developer-conversion/",
    ),
    (
        "Convert software developers into AI engineers enterprise bootcamp",
        "https://towardsai.com/enterprise/software-developer-to-ai-engineer/",
    ),
    (
        "enterprise enablement academy",
        "https://towardsai.com/enterpriseenablement/",
    ),
    (
        "Custom AI development deployment private equity value creation consulting",
        "https://towardsai.com/valuecreation/",
    ),
)


def test_forced_prompts_match_expected_options() -> None:
    assert forced_prompts() == [
        "I want help deciding which course to take.",
        "I want help to integrate AI into my company",
        "I want a training inside my company",
        "I'm looking for more free resources to learn before committing to buying a course",
        "I want to find mentors",
    ]


def test_allowed_public_pages_include_sitemap_urls_and_exclude_private_paths() -> None:
    assert page_is_allowed("https://academy.towardsai.net/courses/agent-engineering")
    assert page_is_allowed("https://towardsai.net/b2b")
    assert page_is_allowed("https://www.towardsai.net/b2b")
    assert page_is_allowed("https://towardsai.com/academy/full-stack-ai-engineering/")
    assert page_is_allowed("https://towardsai.com/academy/mentorship/")
    assert page_is_allowed("https://www.towardsai.com/a-future-public-page/")
    assert not page_is_allowed(
        "https://academy.towardsai.net/courses/take/agent-engineering/lessons/x"
    )
    assert not page_is_allowed("https://academy.towardsai.net/enroll/123")
    assert not page_is_allowed("https://towardsai.com/wp-admin/edit.php")
    assert not page_is_allowed("https://towardsai.com/academy/?preview=true")
    assert "/b2b" in allowed_paths_by_host()["www.towardsai.net"]
    assert "/academy/mentorship" in allowed_paths_by_host()["www.towardsai.com"]


def test_routing_keeps_fetched_sitemap_url_when_canonical_crosses_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovered_url = "https://academy.towardsai.net/courses/agent-engineering"
    monkeypatch.setattr(
        catalog,
        "pages_payload",
        lambda: {
            "pages": [
                {
                    "discovered_url": discovered_url,
                    "url": "https://towardsai.com/academy/agent-engineering/",
                    "canonical_url": "https://towardsai.com/academy/agent-engineering/",
                    "host": "towardsai.com",
                    "path": "/academy/agent-engineering",
                    "status": "excluded",
                    "retrieval_eligible": False,
                    "http_status": 200,
                    "excluded_reason": "canonical URL is outside the sitemap authority",
                }
            ]
        },
    )

    assert allowed_paths_by_host() == {
        "academy.towardsai.net": ["/courses/agent-engineering"],
        "towardsai.net": sorted(catalog.LEGACY_PUBLIC_PATHS_BY_HOST["towardsai.net"]),
        "www.towardsai.net": sorted(
            catalog.LEGACY_PUBLIC_PATHS_BY_HOST["towardsai.net"]
        ),
    }
    assert page_is_allowed(discovered_url)


def test_retrieval_routes_mentorship_b2b_and_bundle_queries() -> None:
    mentorship = sources_from_pages(retrieve("I want to find mentors"))
    b2b = sources_from_pages(retrieve("I want training inside my company"))
    bundle = sources_from_pages(retrieve("What is the best value bundle?"))

    assert any(
        "towardsai.com/academy/mentorship" in source["url"] for source in mentorship
    )
    assert any(source["url"].startswith("https://towardsai.com/") for source in b2b)
    assert any(
        source["url"] == "https://towardsai.com/academy/bundles/get-it-all/"
        for source in bundle
    )


def test_retrieval_routes_specialized_enterprise_queries() -> None:
    coding_agents = sources_from_pages(
        retrieve("We need Claude Code and Codex training for our engineering team")
    )
    developer_conversion = sources_from_pages(
        retrieve("Convert our software developers into AI engineers")
    )
    consulting = sources_from_pages(
        retrieve("We need AI deployment and value creation consulting")
    )

    assert coding_agents[0]["url"].endswith("/agentic-developer-conversion/")
    assert developer_conversion[0]["url"].endswith(
        "/software-developer-to-ai-engineer/"
    )
    assert consulting[0]["url"] == "https://towardsai.com/valuecreation/"


@pytest.mark.parametrize(
    ("query", "expected_url"),
    CANONICAL_OFFER_RETRIEVAL_CASES,
    ids=[
        expected_url.rstrip("/").rsplit("/", 1)[-1]
        for _, expected_url in CANONICAL_OFFER_RETRIEVAL_CASES
    ],
)
def test_every_current_offer_routes_to_its_canonical_page(
    query: str, expected_url: str
) -> None:
    selected = retrieve(query, limit=1)

    assert selected
    assert selected[0]["url"] == expected_url


def test_current_mentorship_offer_replaces_stale_membership_claim() -> None:
    mentorship_pages = [
        page
        for page in pages()
        if page.get("url") == "https://towardsai.com/academy/mentorship/"
    ]

    assert len(mentorship_pages) == 1
    mentorship = mentorship_pages[0]
    searchable_text = " ".join(
        [
            str(mentorship.get("meta_description", "")),
            " ".join(str(item) for item in mentorship.get("headings", [])),
            str(mentorship.get("text", "")),
        ]
    )
    assert "10-Hour LLM Fundamentals" in searchable_text
    assert "Two courses included" not in searchable_text
    chunks = mentorship.get("chunks", [])
    assert chunks
    assert all(len(str(chunk.get("text", ""))) <= 2400 for chunk in chunks)
    offer_chunks = [
        str(chunk.get("text", ""))
        for chunk in chunks
        if chunk.get("heading") == "The curriculum comes with the team"
    ]
    assert len(offer_chunks) == 1
    offer_table = offer_chunks[0]
    assert offer_table.count("Included from day one") == 1
    assert (
        "10-Hour LLM Fundamentals video course Five in-depth 2-hour video "
        "sessions, from a basic prompt to a full production rollout $199 "
        "Included from day one"
    ) in offer_table
    assert (
        "Full Stack AI Engineering · Agent Engineering · Master AI for Work "
        "$349–499 each 25% off, always"
    ) in offer_table
    assert not any(
        page.get("url") == "https://towardsai.com/academy/membership/"
        for page in pages()
    )


def test_scope_and_coupon_detection() -> None:
    assert in_scope("Which course is best for learning agents?")
    assert not in_scope("Who won the world cup?")
    assert coupon_intent("Do you have a coupon code?")
    assert coupon_followup("Please I really need a discount code", ["coupon?"])
