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
    assert not page_is_allowed(
        "https://academy.towardsai.net/courses/take/agent-engineering/lessons/x"
    )
    assert not page_is_allowed("https://academy.towardsai.net/enroll/123")
    assert "/b2b" in allowed_paths_by_host()["www.towardsai.net"]


def test_retrieval_routes_mentorship_b2b_and_bundle_queries() -> None:
    mentorship = sources_from_pages(retrieve("I want to find mentors"))
    b2b = sources_from_pages(retrieve("I want training inside my company"))
    bundle = sources_from_pages(retrieve("What is the best value bundle?"))

    assert any("tai-mentorship" in source["url"] for source in mentorship)
    assert any("towardsai.net/b2b" in source["url"] for source in b2b)
    assert any("get-it-all" in source["url"] for source in bundle)


def test_scope_and_coupon_detection() -> None:
    assert in_scope("Which course is best for learning agents?")
    assert not in_scope("Who won the world cup?")
    assert coupon_intent("Do you have a coupon code?")
    assert coupon_followup("Please I really need a discount code", ["coupon?"])
