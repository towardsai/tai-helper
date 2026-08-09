from __future__ import annotations

import json

import pytest

from tai_helper import llm

MENTORSHIP_PAGE = {
    "title": "Towards AI Mentorship",
    "kind": "mentorship",
    "url": "https://towardsai.com/academy/mentorship/",
    "headings": ["Everything Inside the Mentorship"],
    "text": (
        "The Mentorship program includes one course: the 10-Hour LLM "
        "Fundamentals course. Members also receive two live sessions every week."
    ),
}


def _model_json(*, text: str, quote: str, chunk_id: str | None = None) -> str:
    return json.dumps(
        {
            "status": "answered",
            "claims": [
                {
                    "text": text,
                    "chunk_id": chunk_id or llm.chunk_id_for_page(MENTORSHIP_PAGE),
                    "quote": quote,
                }
            ],
        }
    )


def test_prompt_uses_stable_chunk_ids_and_marks_notes_as_non_evidence() -> None:
    prompt = llm.build_prompt(
        query="Does mentorship include a course?",
        selected_prompt="I want to find mentors",
        current_url="https://towardsai.com/academy/mentorship/",
        page_title="Towards AI Mentorship",
        history=[("assistant", "Earlier unverified answer: two courses")],
        selected_pages=[MENTORSHIP_PAGE],
    )
    chunk_id = llm.chunk_id_for_page(MENTORSHIP_PAGE)

    assert llm.chunk_id_for_page(dict(MENTORSHIP_PAGE)) == chunk_id
    assert f'<EVIDENCE_CHUNK chunk_id="{chunk_id}">' in prompt
    assert "<NON_EVIDENCE_ROUTING_NOTES>" in prompt
    assert "must not be cited" in prompt
    assert "visitor-provided and NOT evidence" in prompt
    assert "return not_found" in prompt


def test_valid_mentorship_claim_returns_only_validated_text_and_cited_chunk() -> None:
    sentence = (
        "The Mentorship program includes one course: the 10-Hour LLM "
        "Fundamentals course."
    )
    raw = llm.LLMResult(
        answer=_model_json(text=sentence, quote=sentence),
        usage={"provider": "deepseek"},
        latency_ms=42,
    )

    result = llm.validate_grounded_result(raw, [MENTORSHIP_PAGE])

    assert result.valid
    assert result.is_answered
    assert result.status == "answered"
    assert result.answer == sentence
    assert result.cited_chunk_ids == (llm.chunk_id_for_page(MENTORSHIP_PAGE),)
    assert result.cited_chunks[0].url == MENTORSHIP_PAGE["url"]
    assert result.usage == {"provider": "deepseek"}
    assert result.latency_ms == 42


def test_mentorship_table_supports_two_separate_correcting_claims() -> None:
    table_text = (
        "What Full price As a member 10-Hour LLM Fundamentals video course "
        "Five in-depth 2-hour video sessions $199 Included from day one "
        "Full Stack AI Engineering · Agent Engineering · Master AI for Work "
        "$349–499 each 25% off, always"
    )
    table_page = {
        "chunk_id": "mentorship-curriculum-table",
        "title": "Towards AI Mentorship",
        "kind": "mentorship",
        "url": "https://towardsai.com/academy/mentorship/",
        "headings": ["The curriculum comes with the team"],
        "text": table_text,
    }
    included_quote = (
        "10-Hour LLM Fundamentals video course Five in-depth 2-hour video "
        "sessions $199 Included from day one"
    )
    discount_quote = (
        "Full Stack AI Engineering · Agent Engineering · Master AI for Work "
        "$349–499 each 25% off, always"
    )
    raw = json.dumps(
        {
            "status": "answered",
            "claims": [
                {
                    "text": f"{included_quote}.",
                    "chunk_id": "mentorship-curriculum-table",
                    "quote": included_quote,
                },
                {
                    "text": f"{discount_quote}.",
                    "chunk_id": "mentorship-curriculum-table",
                    "quote": discount_quote,
                },
            ],
        }
    )

    result = llm.validate_grounded_result(raw, [table_page])

    assert result.valid
    assert result.is_answered
    assert len(result.claims) == 2
    assert "included from day one" in result.answer.lower()
    assert "25% off, always" in result.answer
    assert "only" not in result.answer.lower()
    assert result.cited_chunk_ids == ("mentorship-curriculum-table",)


def test_invalid_claim_text_is_replaced_by_its_exact_table_row_quotes() -> None:
    included_quote = (
        "10-Hour LLM Fundamentals video course $199 Included from day one"
    )
    discount_quote = (
        "Full Stack AI Engineering · Agent Engineering · Master AI for Work "
        "$349–499 each 25% off, always"
    )
    table_page = {
        "chunk_id": "mentorship-table",
        "title": "Towards AI Mentorship",
        "kind": "mentorship",
        "url": "https://towardsai.com/academy/mentorship/",
        "headings": ["The curriculum comes with the team"],
        "text": f"{included_quote} {discount_quote}",
    }
    raw = json.dumps(
        {
            "status": "answered",
            "claims": [
                {
                    "text": (
                        "The mentorship includes the LLM Fundamentals course, "
                        "not two courses of your choice."
                    ),
                    "chunk_id": "mentorship-table",
                    "quote": included_quote,
                },
                {
                    "text": (
                        "Full Stack AI Engineering, Agent Engineering, and Master "
                        "AI for Work are not included; they are discounted."
                    ),
                    "chunk_id": "mentorship-table",
                    "quote": discount_quote,
                },
            ],
        }
    )

    result = llm.validate_grounded_result(raw, [table_page])

    assert result.valid
    assert result.is_answered
    assert result.answer == f"{included_quote}. {discount_quote}."
    assert "two courses" not in result.answer.lower()
    assert "not included" not in result.answer.lower()
    assert all(claim.text.removesuffix(".") == claim.quote for claim in result.claims)


def test_claim_framing_is_discarded_in_favor_of_the_exact_quote() -> None:
    quote = (
        "10-Hour LLM Fundamentals video course $199 Included from day one"
    )
    table_page = {
        "chunk_id": "mentorship-table",
        "title": "Towards AI Mentorship",
        "kind": "mentorship",
        "url": "https://towardsai.com/academy/mentorship/",
        "headings": ["The curriculum comes with the team"],
        "text": quote,
    }
    raw = _model_json(
        text=(
            "The mentorship includes the 10-Hour LLM Fundamentals video course "
            "from day one."
        ),
        quote=quote,
        chunk_id="mentorship-table",
    )

    result = llm.validate_grounded_result(raw, [table_page])

    assert result.valid
    assert result.status == "answered"
    assert result.answer == f"{quote}."
    assert "mentorship includes" not in result.answer.lower()


def test_salvage_never_surfaces_framing_from_an_unrelated_chunk() -> None:
    quote = (
        "10-Hour LLM Fundamentals video course $199 Included from day one"
    )
    table_page = {
        "chunk_id": "mentorship-table",
        "title": "Towards AI Mentorship",
        "kind": "mentorship",
        "url": "https://towardsai.com/academy/mentorship/",
        "headings": ["The curriculum comes with the team"],
        "text": quote,
    }
    unrelated_page = {
        "chunk_id": "unrelated-premium-page",
        "title": "Premium Executive Subscription",
        "kind": "course",
        "url": "https://towardsai.com/academy/unrelated/",
        "headings": ["Guaranteed career accelerator"],
        "text": "Unrelated material.",
    }
    raw = _model_json(
        text=(
            "The premium executive subscription includes the 10-Hour LLM "
            "Fundamentals video course from day one."
        ),
        quote=quote,
        chunk_id="mentorship-table",
    )

    result = llm.validate_grounded_result(raw, [table_page, unrelated_page])

    assert result.valid
    assert result.status == "answered"
    assert result.answer == f"{quote}."
    assert "premium executive subscription" not in result.answer.lower()


def test_not_found_is_valid_but_has_no_user_answer_or_citations() -> None:
    result = llm.validate_grounded_result(
        '{"status":"not_found","claims":[]}', [MENTORSHIP_PAGE]
    )

    assert result.valid
    assert not result.is_answered
    assert result.status == "not_found"
    assert result.answer == ""
    assert result.cited_chunks == ()


@pytest.mark.parametrize(
    "raw",
    [
        "The mentorship includes two courses.",
        '```json\n{"status":"not_found","claims":[]}\n```',
        '{"status":"answered","claims":[}',
        '{"status":"not_found","claims":[],"answer":"invented"}',
        '{"status":"answered","status":"not_found","claims":[]}',
        '{"status":"answered","claims":[],"confidence":1}',
    ],
)
def test_malformed_or_non_schema_output_fails_closed(raw: str) -> None:
    result = llm.validate_grounded_result(raw, [MENTORSHIP_PAGE])

    assert not result.valid
    assert result.status == "validation_failure"
    assert result.answer == ""
    assert result.cited_chunks == ()
    assert result.validation_error


def test_invented_quote_fails_closed() -> None:
    result = llm.validate_grounded_result(
        _model_json(
            text="The Mentorship program includes two courses.",
            quote="The Mentorship program includes two courses.",
        ),
        [MENTORSHIP_PAGE],
    )

    assert result.status == "validation_failure"
    assert result.answer == ""
    assert "quote" in result.validation_error


def test_bad_chunk_id_fails_closed_even_when_quote_exists_elsewhere() -> None:
    sentence = (
        "The Mentorship program includes one course: the 10-Hour LLM "
        "Fundamentals course."
    )
    result = llm.validate_grounded_result(
        _model_json(text=sentence, quote=sentence, chunk_id="chunk_not_retrieved"),
        [MENTORSHIP_PAGE],
    )

    assert result.status == "validation_failure"
    assert result.answer == ""
    assert "unknown chunk_id" in result.validation_error


@pytest.mark.parametrize(
    ("claim", "quote"),
    [
        (
            "The Mentorship program includes 2 courses.",
            "The Mentorship program includes 1 course",
        ),
        (
            "The Mentorship program includes two courses.",
            "The Mentorship program includes one course",
        ),
        (
            "Members receive 3 live sessions every week.",
            "Members also receive two live sessions every week.",
        ),
        (
            "The yearly plan saves 25%.",
            "The yearly plan saves 24%",
        ),
        (
            "The plan costs $199.",
            "The plan costs $99",
        ),
        (
            "Details are at https://towardsai.com/invented.",
            "Details are at https://towardsai.com/academy/mentorship/",
        ),
    ],
)
def test_unsupported_critical_facts_are_discarded_for_the_exact_quote(
    claim: str, quote: str
) -> None:
    page = {**MENTORSHIP_PAGE, "text": f"{MENTORSHIP_PAGE['text']} {quote}"}
    result = llm.validate_grounded_result(
        _model_json(
            text=claim,
            quote=quote,
            chunk_id=llm.chunk_id_for_page(page),
        ),
        [page],
    )

    expected = quote if quote.endswith(".") else f"{quote}."
    assert result.valid
    assert result.status == "answered"
    assert result.answer == expected
    assert result.answer != claim


def test_loose_paraphrase_is_discarded_for_the_exact_quote() -> None:
    quote = "Members also receive two live sessions every week."
    claim = "Experts provide unlimited private coaching and personal hiring referrals."
    result = llm.validate_grounded_result(
        _model_json(text=claim, quote=quote), [MENTORSHIP_PAGE]
    )

    assert result.valid
    assert result.status == "answered"
    assert result.answer == quote
    assert "private coaching" not in result.answer


def test_changed_negation_is_discarded_for_the_exact_quote() -> None:
    quote = "The Mentorship program does not include two courses."
    claim = "The Mentorship program does include two courses."
    page = {**MENTORSHIP_PAGE, "text": quote}
    result = llm.validate_grounded_result(
        _model_json(
            text=claim,
            quote=quote,
            chunk_id=llm.chunk_id_for_page(page),
        ),
        [page],
    )

    assert result.valid
    assert result.status == "answered"
    assert result.answer == quote
    assert "does not include" in result.answer


def test_oversized_exact_quote_cannot_be_salvaged() -> None:
    quote = "x" * (llm.MAX_SALVAGED_QUOTE_CHARS + 1)
    page = {**MENTORSHIP_PAGE, "text": quote}
    result = llm.validate_grounded_result(
        _model_json(
            text="Unsupported framing.",
            quote=quote,
            chunk_id=llm.chunk_id_for_page(page),
        ),
        [page],
    )

    assert not result.valid
    assert result.status == "validation_failure"
    assert result.answer == ""
    assert "safely salvaged" in result.validation_error


@pytest.mark.parametrize(
    "claim",
    [
        "Two courses are included.",
        "Full Stack AI Engineering is included from day one.",
        "Agent Engineering is included from day one.",
    ],
)
def test_claim_cannot_recombine_words_from_a_table_chunk(claim: str) -> None:
    quote = (
        "Two live Q&A calls every week Course Full price As a member "
        "10-Hour LLM Fundamentals video course $199 Included from day one "
        "Full Stack AI Engineering · Agent Engineering · Master AI for Work "
        "$349–499 each 25% off, always"
    )
    page = {
        **MENTORSHIP_PAGE,
        "chunk_id": "mentorship-table",
        "text": quote,
    }
    result = llm.validate_grounded_result(
        _model_json(text=claim, quote=quote, chunk_id="mentorship-table"),
        [page],
    )

    assert result.status == "validation_failure"
    assert result.answer == ""
    assert "verbatim" in result.validation_error


def test_evidence_quote_length_is_bounded() -> None:
    quote = "A" * (llm.MAX_EVIDENCE_QUOTE_CHARS + 1)
    page = {**MENTORSHIP_PAGE, "chunk_id": "oversized", "text": quote}
    result = llm.validate_grounded_result(
        _model_json(text=f"{quote}.", quote=quote, chunk_id="oversized"),
        [page],
    )

    assert result.status == "validation_failure"
    assert result.answer == ""
    assert "exceeds" in result.validation_error


def test_claim_must_be_a_single_complete_sentence() -> None:
    quote = (
        "The Mentorship program includes one course: the 10-Hour LLM "
        "Fundamentals course. Members also receive two live sessions every week."
    )
    result = llm.validate_grounded_result(
        _model_json(text=quote, quote=quote), [MENTORSHIP_PAGE]
    )

    assert result.status == "validation_failure"
    assert "one complete sentence" in result.validation_error


def test_generate_grounded_answer_never_returns_raw_unvalidated_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm,
        "generate_answer",
        lambda _prompt: llm.LLMResult("An unsupported provider sentence."),
    )

    result = llm.generate_grounded_answer("prompt", [MENTORSHIP_PAGE])

    assert result.status == "validation_failure"
    assert result.answer == ""
