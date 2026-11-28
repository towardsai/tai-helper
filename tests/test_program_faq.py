import pytest

from tai_helper.program_faq import program_answer, public_page


@pytest.mark.parametrize(("query", "history", "contains"), [
    ("How long does Agent Engineering take including the capstone?", [], "40–70 hours"),
    ("Can I get feedback on my own project?", ["I want to find mentors"], "personal projects"),
    ("Does mentorship include interview prep?", [], "job description"),
    ("Does mentorship guarantee internships?", [], "None of those"),
    ("Are the mentorship calls private?", [], "45-minute group"),
    ("Do you offer a mentorship?", [], "Yes."),
])
def test_public_faq_answers(query, history, contains):
    answer, anchor = program_answer(query, history, "https://towardsai.com/")
    assert contains in answer
    assert f'id="{anchor}"' in public_page()


@pytest.mark.parametrize("query", ["How long is Full Stack?", "What is the mentorship price?",
                                   "Does Agent Engineering include mentorship?", "Is there a refund?"])
def test_catalog_keeps_ownership_of_unrelated_questions(query):
    assert program_answer(query, [], "https://towardsai.com/") is None
