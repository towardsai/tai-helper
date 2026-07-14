from __future__ import annotations

from tai_helper.catalog import (
    allowed_paths_by_host,
    coupon_followup,
    coupon_intent,
    forced_prompts,
    in_scope,
    page_is_allowed,
    retrieve,
    sources_from_pages,
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
    assert page_is_allowed("https://www.towardsai.com/a-future-public-page/")
    assert not page_is_allowed(
        "https://academy.towardsai.net/courses/take/agent-engineering/lessons/x"
    )
    assert not page_is_allowed("https://academy.towardsai.net/enroll/123")
    assert not page_is_allowed("https://towardsai.com/wp-admin/edit.php")
    assert not page_is_allowed("https://towardsai.com/academy/?preview=true")
    assert "/b2b" in allowed_paths_by_host()["www.towardsai.net"]
    assert "/academy" in allowed_paths_by_host()["www.towardsai.com"]


def test_retrieval_routes_mentorship_b2b_and_bundle_queries() -> None:
    mentorship = sources_from_pages(retrieve("I want to find mentors"))
    b2b = sources_from_pages(retrieve("I want training inside my company"))
    bundle = sources_from_pages(retrieve("What is the best value bundle?"))

    assert any(
        "towardsai.com/academy/membership" in source["url"] for source in mentorship
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


def test_scope_and_coupon_detection() -> None:
    assert in_scope("Which course is best for learning agents?")
    assert not in_scope("Who won the world cup?")
    assert coupon_intent("Do you have a coupon code?")
    assert coupon_followup("Please I really need a discount code", ["coupon?"])
