from datetime import UTC, datetime

import pytest

from tai_helper import academy_guidance as guide


@pytest.mark.parametrize(("query","expected"), [
    ("Is there blackfriday discount for all courses?", "blackfriday40"),
    ("Do you still support gift +1?", "50%"),
    ("transition from Senir dev to AI engineer", "Full Stack AI Engineering"),
    ("become ai engineer and fairly comfortable in python", "Get It All"),
    ("Which course for building MCP agents?", "Agent Engineering"),
    ("Which course for AI engineering with no Python?", "Beginner Python"),
    ("How do I find my receipt?", "Order History"),
])
def test_learner_questions(monkeypatch, query, expected):
    monkeypatch.setattr(guide, "_refresh", lambda: None)
    assert expected in guide.guidance_answer(query, instant=datetime(2026, 11, 28, tzinfo=UTC))[0]


def test_expiry_and_unrelated_questions(monkeypatch):
    monkeypatch.setattr(guide, "_refresh", lambda: None)
    for hour, expected in [(4, "blackfriday40"), (5, "ended")]:
        answer, _ = guide.guidance_answer("Black Friday?", instant=datetime(2026,12,7,hour,0,tzinfo=UTC))
        assert expected in answer
    for query in ["What is a discount factor in RL?", "Can you train our software developers to become AI engineers?"]:
        assert guide.guidance_answer(query) is None
