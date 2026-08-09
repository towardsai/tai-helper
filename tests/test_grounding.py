from __future__ import annotations

import json

import pytest

from tai_helper import llm
from tai_helper.catalog import forced_prompts

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


def _with_spans(page: dict, *spans: str) -> dict:
    return {
        **page,
        "evidence_spans": [
            {"span_id": f"{page['chunk_id']}:span-{index}", "text": span}
            for index, span in enumerate(spans)
        ],
    }


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


def test_valid_unpunctuated_atomic_span_gets_only_a_server_added_period() -> None:
    quote = "10-Hour LLM Fundamentals course $199 Included from day one"
    page = _with_spans(
        {
            **MENTORSHIP_PAGE,
            "chunk_id": "mentorship-row",
            "text": quote,
        },
        quote,
    )
    result = llm.validate_grounded_result(
        _model_json(text=quote, quote=quote, chunk_id="mentorship-row"),
        [page],
    )

    assert result.valid
    assert result.answer == f"{quote}."
    assert result.claims[0].quote == quote


def test_mentorship_table_supports_two_separate_correcting_claims() -> None:
    table_text = (
        "What Full price As a member 10-Hour LLM Fundamentals video course "
        "Five in-depth 2-hour video sessions $199 Included from day one "
        "Full Stack AI Engineering · Agent Engineering · Master AI for Work "
        "$349–499 each 25% off, always"
    )
    included_quote = (
        "10-Hour LLM Fundamentals video course Five in-depth 2-hour video "
        "sessions $199 Included from day one"
    )
    discount_quote = (
        "Full Stack AI Engineering · Agent Engineering · Master AI for Work "
        "$349–499 each 25% off, always"
    )
    table_page = _with_spans(
        {
            "chunk_id": "mentorship-curriculum-table",
            "title": "Towards AI Mentorship",
            "kind": "mentorship",
            "url": "https://towardsai.com/academy/mentorship/",
            "headings": ["The curriculum comes with the team"],
            "text": table_text,
        },
        included_quote,
        discount_quote,
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


def test_invalid_claim_text_fails_closed_even_with_valid_table_row_quotes() -> None:
    included_quote = "10-Hour LLM Fundamentals video course $199 Included from day one"
    discount_quote = (
        "Full Stack AI Engineering · Agent Engineering · Master AI for Work "
        "$349–499 each 25% off, always"
    )
    table_page = _with_spans(
        {
            "chunk_id": "mentorship-table",
            "title": "Towards AI Mentorship",
            "kind": "mentorship",
            "url": "https://towardsai.com/academy/mentorship/",
            "headings": ["The curriculum comes with the team"],
            "text": f"{included_quote} {discount_quote}",
        },
        included_quote,
        discount_quote,
    )
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

    assert not result.valid
    assert result.status == "validation_failure"
    assert result.answer == ""
    assert "unsupported number words" in result.validation_error


def test_claim_cannot_add_framing_to_an_exact_span() -> None:
    quote = "10-Hour LLM Fundamentals video course $199 Included from day one"
    table_page = _with_spans(
        {
            "chunk_id": "mentorship-table",
            "title": "Towards AI Mentorship",
            "kind": "mentorship",
            "url": "https://towardsai.com/academy/mentorship/",
            "headings": ["The curriculum comes with the team"],
            "text": quote,
        },
        quote,
    )
    raw = _model_json(
        text=(
            "The mentorship includes the 10-Hour LLM Fundamentals video course "
            "from day one."
        ),
        quote=quote,
        chunk_id="mentorship-table",
    )

    result = llm.validate_grounded_result(raw, [table_page])

    assert not result.valid
    assert result.status == "validation_failure"
    assert result.answer == ""
    assert "verbatim" in result.validation_error


def test_claim_cannot_borrow_framing_from_an_unrelated_chunk() -> None:
    quote = "10-Hour LLM Fundamentals video course $199 Included from day one"
    table_page = _with_spans(
        {
            "chunk_id": "mentorship-table",
            "title": "Towards AI Mentorship",
            "kind": "mentorship",
            "url": "https://towardsai.com/academy/mentorship/",
            "headings": ["The curriculum comes with the team"],
            "text": quote,
        },
        quote,
    )
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

    assert not result.valid
    assert result.status == "validation_failure"
    assert result.answer == ""
    assert "verbatim" in result.validation_error


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
    assert "evidence span" in result.validation_error


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
    ("claim", "quote", "error_fragment"),
    [
        (
            "The Mentorship program includes 2 courses.",
            "The Mentorship program includes 1 course",
            "numbers",
        ),
        (
            "The Mentorship program includes two courses.",
            "The Mentorship program includes one course",
            "number words",
        ),
        (
            "Members receive 3 live sessions every week.",
            "Members also receive two live sessions every week.",
            "numbers",
        ),
        (
            "The yearly plan saves 25%.",
            "The yearly plan saves 24%",
            "percentages",
        ),
        (
            "The plan costs $199.",
            "The plan costs $99",
            "currency amounts",
        ),
        (
            "Details are at https://towardsai.com/invented.",
            "Details are at https://towardsai.com/academy/mentorship/",
            "URLs",
        ),
    ],
)
def test_unsupported_critical_facts_fail_closed(
    claim: str, quote: str, error_fragment: str
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

    assert not result.valid
    assert result.status == "validation_failure"
    assert result.answer == ""
    assert error_fragment in result.validation_error


def test_loose_paraphrase_fails_closed() -> None:
    quote = "Members also receive two live sessions every week."
    claim = "Experts provide unlimited private coaching and personal hiring referrals."
    result = llm.validate_grounded_result(
        _model_json(text=claim, quote=quote), [MENTORSHIP_PAGE]
    )

    assert not result.valid
    assert result.status == "validation_failure"
    assert result.answer == ""
    assert "verbatim" in result.validation_error


def test_changed_negation_fails_closed() -> None:
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

    assert not result.valid
    assert result.status == "validation_failure"
    assert result.answer == ""
    assert "negation" in result.validation_error


def test_oversized_exact_quote_fails_closed() -> None:
    quote = "x" * (llm.MAX_EVIDENCE_QUOTE_CHARS + 1)
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
    assert "exceeds" in result.validation_error


@pytest.mark.parametrize(
    "claim",
    [
        "Two courses are included.",
        "Full Stack AI Engineering is included from day one.",
        "Agent Engineering is included from day one.",
    ],
)
def test_claim_cannot_recombine_words_from_a_table_chunk(claim: str) -> None:
    full_table = (
        "Two live Q&A calls every week Course Full price As a member "
        "10-Hour LLM Fundamentals video course $199 Included from day one "
        "Full Stack AI Engineering · Agent Engineering · Master AI for Work "
        "$349–499 each 25% off, always"
    )
    included_row = "10-Hour LLM Fundamentals video course $199 Included from day one"
    discount_row = (
        "Full Stack AI Engineering · Agent Engineering · Master AI for Work "
        "$349–499 each 25% off, always"
    )
    page = _with_spans(
        {**MENTORSHIP_PAGE, "chunk_id": "mentorship-table", "text": full_table},
        included_row,
        discount_row,
    )
    quote = claim.removesuffix(".")
    result = llm.validate_grounded_result(
        _model_json(text=claim, quote=quote, chunk_id="mentorship-table"),
        [page],
    )

    assert result.status == "validation_failure"
    assert result.answer == ""
    assert "evidence span" in result.validation_error


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
    assert "complete server-defined evidence span" in result.validation_error


@pytest.mark.parametrize(
    ("source_span", "unsafe_substring"),
    [
        ("No code required: learn by doing, not watching.", "code required"),
        ("Never guaranteed, always earned.", "guaranteed"),
        ("Earned, never promised.", "promised"),
        (
            "If you cancel the monthly plan, you can upgrade before renewal.",
            "you can upgrade before renewal",
        ),
        ("Pay once $399 $349 one-time Save 12%", "$399"),
    ],
)
def test_arbitrary_substrings_cannot_omit_negation_or_conditions(
    source_span: str, unsafe_substring: str
) -> None:
    page = _with_spans(
        {
            **MENTORSHIP_PAGE,
            "chunk_id": "atomic-source",
            "text": source_span,
        },
        source_span,
    )
    result = llm.validate_grounded_result(
        _model_json(
            text=f"{unsafe_substring}.",
            quote=unsafe_substring,
            chunk_id="atomic-source",
        ),
        [page],
    )

    assert result.status == "validation_failure"
    assert result.answer == ""
    assert "complete server-defined evidence span" in result.validation_error


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


def test_generate_grounded_answer_retries_one_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentence = (
        "The Mentorship program includes one course: the 10-Hour LLM "
        "Fundamentals course."
    )
    responses = iter(
        [
            llm.LLMResult("An unsupported provider sentence."),
            llm.LLMResult(_model_json(text=sentence, quote=sentence)),
        ]
    )
    prompts: list[str] = []

    def fake_generate(prompt: str) -> llm.LLMResult:
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(llm, "generate_answer", fake_generate)

    result = llm.generate_grounded_answer("prompt", [MENTORSHIP_PAGE])

    assert result.is_answered
    assert result.answer == sentence
    assert len(prompts) == 2
    assert "single valid claim is better" in prompts[1]


def test_generate_grounded_answer_does_not_retry_valid_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_generate(_prompt: str) -> llm.LLMResult:
        nonlocal calls
        calls += 1
        return llm.LLMResult('{"status":"not_found","claims":[]}')

    monkeypatch.setattr(llm, "generate_answer", fake_generate)

    result = llm.generate_grounded_answer("prompt", [MENTORSHIP_PAGE])

    assert result.status == "not_found"
    assert calls == 1


def _query_bound_result(page: dict, query: str, target_offer_id: str):
    span = page["evidence_spans"][0]["text"]
    raw = _model_json(
        text=span if span.endswith((".", "!", "?")) else f"{span}.",
        quote=span,
        chunk_id=page["chunk_id"],
    )
    return llm.validate_grounded_result(
        raw,
        [page],
        query=query,
        target_offer_ids=frozenset({target_offer_id}),
    )


def test_broad_course_decision_starter_accepts_retrieved_offer_evidence() -> None:
    span = "Build and evaluate production-ready agentic AI systems."
    page = _with_spans(
        {
            "chunk_id": "agent-engineering-overview",
            "title": "Agent Engineering",
            "kind": "course",
            "offer_id": "agent-engineering",
            "entity_id": "offer:agent-engineering",
            "url": "https://towardsai.com/academy/agent-engineering/",
            "headings": ["Agent Engineering"],
            "text": span,
        },
        span,
    )
    raw = _model_json(
        text=span,
        quote=span,
        chunk_id=page["chunk_id"],
    )

    result = llm.validate_grounded_result(
        raw,
        [page],
        query="I want help deciding which course to take.",
        target_offer_ids=frozenset(),
    )

    assert result.is_answered
    assert result.answer == span


@pytest.mark.parametrize("starter", forced_prompts())
def test_exact_starter_prompts_are_routing_intent_not_factual_qualifiers(
    starter: str,
) -> None:
    span = "Two live Q&A calls with senior engineers."
    page = _with_spans(
        {
            "chunk_id": "starter-route-evidence",
            "title": "Towards AI Offer",
            "kind": "course",
            "offer_id": "",
            "entity_id": "",
            "url": "https://towardsai.com/academy/",
            "headings": ["Offer"],
            "text": span,
        },
        span,
    )
    raw = _model_json(
        text=span,
        quote=span,
        chunk_id=page["chunk_id"],
    )

    result = llm.validate_grounded_result(
        raw,
        [page],
        query=starter,
        target_offer_ids=frozenset(),
    )

    assert result.is_answered
    assert result.answer == span


def test_typed_duration_uses_field_validation_not_literal_structure_word() -> None:
    span = "It is self-paced; the average completion time is 10 hours across five 2-hour sessions."
    page = _with_spans(
        {
            "chunk_id": "llm-primer-duration",
            "title": "10-Hour LLM Fundamentals",
            "kind": "course",
            "offer_id": "llm-primer",
            "entity_id": "offer:llm-primer",
            "url": "https://towardsai.com/academy/llm-primer/",
            "headings": ["Course duration"],
            "text": span,
        },
        span,
    )
    raw = _model_json(text=span, quote=span, chunk_id=page["chunk_id"])

    result = llm.validate_grounded_result(
        raw,
        [page],
        query="How long is LLM Fundamentals, and how is it structured?",
        target_offer_ids=frozenset({"llm-primer"}),
    )

    assert result.is_answered


def test_zero_coding_experience_is_a_typed_prerequisite_question() -> None:
    span = "The course teaches Python from scratch and assumes no software background."
    page = _with_spans(
        {
            "chunk_id": "python-prerequisite",
            "title": "Beginner Python for AI Engineering",
            "kind": "course",
            "offer_id": "python-for-ai-engineering",
            "entity_id": "offer:python-for-ai-engineering",
            "url": "https://towardsai.com/academy/python-for-ai-engineering/",
            "headings": ["Prerequisites"],
            "text": span,
        },
        span,
    )
    raw = _model_json(text=span, quote=span, chunk_id=page["chunk_id"])

    result = llm.validate_grounded_result(
        raw,
        [page],
        query=(
            "Is Beginner Python for AI Engineering suitable for someone with "
            "zero coding experience?"
        ),
        target_offer_ids=frozenset({"python-for-ai-engineering"}),
    )

    assert result.is_answered


def test_requires_coding_is_a_typed_prerequisite_question() -> None:
    span = "No code required: learn by doing, not watching."
    page = _with_spans(
        {
            "chunk_id": "ai-for-work-prerequisite",
            "title": "Master AI for Work",
            "kind": "course",
            "offer_id": "ai-for-work",
            "entity_id": "offer:ai-for-work",
            "url": "https://towardsai.com/academy/ai-for-work/",
            "headings": ["No code required"],
            "text": span,
        },
        span,
    )
    raw = _model_json(text=span, quote=span, chunk_id=page["chunk_id"])

    result = llm.validate_grounded_result(
        raw,
        [page],
        query="Does Master AI for Work require coding?",
        target_offer_ids=frozenset({"ai-for-work"}),
    )

    assert result.is_answered


def test_query_binding_rejects_an_exact_span_from_the_wrong_offer() -> None:
    page = _with_spans(
        {
            "chunk_id": "book-community",
            "title": "Building LLMs for Production",
            "kind": "book",
            "offer_id": "building-llms-for-production",
            "entity_id": "offer:building-llms-for-production",
            "url": "https://towardsai.com/academy/building-llms-for-production/",
            "headings": ["Community"],
            "text": "Community access and our own AI Tutor",
        },
        "Community access and our own AI Tutor",
    )

    result = _query_bound_result(
        page,
        "Does LLM Fundamentals include community support and an AI tutor?",
        "llm-primer",
    )

    assert result.status == "validation_failure"
    assert "outside the requested offer boundary" in result.validation_error


@pytest.mark.parametrize(
    ("offer_id", "query", "span"),
    [
        (
            "full-stack-ai-engineering-free-preview",
            "Does the Full Stack free preview give me a certificate?",
            "03 A certification that unlocks six-figure roles",
        ),
        (
            "mentorship",
            "Does the monthly mentorship plan have a 30-day money-back guarantee?",
            "Join the Mentorship 30-day money-back guarantee",
        ),
        (
            "get-it-all",
            "What is the Get It All bundle price?",
            "$1,625 combined price bought separately",
        ),
        (
            "agent-engineering",
            "Does Agent Engineering include lifetime access?",
            "Get instant access today",
        ),
        (
            "mentorship",
            "What is the monthly mentorship price?",
            "From $75/month",
        ),
        (
            "mentorship",
            "What is the month-to-month mentorship price?",
            "From $75/month",
        ),
        (
            "mentorship",
            "What does mentorship cost each month?",
            "How is this different from a $150/month mentor?",
        ),
        (
            "mentorship",
            "What is the monthly mentorship price?",
            "1× Guest workshop monthly, recorded",
        ),
        (
            "mentorship",
            "What is the yearly mentorship price?",
            "Yearly Save 24% · $289 off",
        ),
        (
            "mentorship",
            "Is the yearly mentorship plan 24% off?",
            (
                "Full Stack AI Engineering · Agent Engineering · Master AI for "
                "Work $349–499 each 25% off, always"
            ),
        ),
        (
            "mentorship",
            "Does monthly mentorship have a discount?",
            (
                "Full Stack AI Engineering · Agent Engineering · Master AI for "
                "Work $349–499 each 25% off, always"
            ),
        ),
    ],
)
def test_query_binding_rejects_wrong_qualifier_within_the_right_offer(
    offer_id: str, query: str, span: str
) -> None:
    page = _with_spans(
        {
            "chunk_id": f"{offer_id}-unsafe-field",
            "title": offer_id,
            "kind": "course",
            "offer_id": offer_id,
            "entity_id": f"offer:{offer_id}",
            "url": f"https://towardsai.com/academy/{offer_id}/",
            "headings": ["Offer"],
            "text": span,
        },
        span,
    )

    result = _query_bound_result(page, query, offer_id)

    assert result.status == "validation_failure"
    assert "target-qualified" in result.validation_error


@pytest.mark.parametrize(
    ("offer_id", "query", "span", "targets"),
    [
        (
            "full-stack-ai-engineering",
            "How many Full Stack AI Engineering lessons can I preview for free?",
            "Explore the first 6 lessons free.",
            frozenset(
                {
                    "full-stack-ai-engineering",
                    "full-stack-ai-engineering-free-preview",
                }
            ),
        ),
        (
            "llm-primer",
            "Is LLM Fundamentals 10 or 12 hours long?",
            (
                "It is self-paced; the average completion time is 10 hours "
                "across five 2-hour sessions."
            ),
            frozenset({"llm-primer"}),
        ),
        (
            "mentorship",
            "What is the month-to-month mentorship price?",
            "$99 /month",
            frozenset({"mentorship"}),
        ),
    ],
)
def test_query_binding_accepts_exact_target_qualified_facts(
    offer_id: str,
    query: str,
    span: str,
    targets: frozenset[str],
) -> None:
    page = _with_spans(
        {
            "chunk_id": f"{offer_id}-valid-field",
            "title": offer_id,
            "kind": "course",
            "offer_id": offer_id,
            "entity_id": f"offer:{offer_id}",
            "url": f"https://towardsai.com/academy/{offer_id}/",
            "headings": ["Offer"],
            "text": span,
        },
        span,
    )
    raw = _model_json(
        text=span,
        quote=span,
        chunk_id=page["chunk_id"],
    )

    result = llm.validate_grounded_result(
        raw,
        [page],
        query=query,
        target_offer_ids=targets,
    )

    assert result.is_answered
    assert result.answer == (
        span if span.endswith((".", "!", "?")) else f"{span}."
    )


def test_preview_count_exception_rejects_paid_course_access_claim() -> None:
    preview_count = "Free preview · 7 full lessons"
    paid_access = "Unlock Lifetime Access"
    preview_page = _with_spans(
        {
            "chunk_id": "agent-preview-count",
            "title": "Agent Engineering free preview",
            "kind": "course_preview",
            "offer_id": "agent-engineering-free-preview",
            "entity_id": "offer:agent-engineering-free-preview",
            "url": (
                "https://towardsai.com/academy/"
                "agent-engineering-free-preview/"
            ),
            "headings": ["Free preview"],
            "text": preview_count,
        },
        preview_count,
    )
    paid_page = _with_spans(
        {
            "chunk_id": "agent-paid-access",
            "title": "Agent Engineering",
            "kind": "course",
            "offer_id": "agent-engineering",
            "entity_id": "offer:agent-engineering",
            "url": "https://towardsai.com/academy/agent-engineering/",
            "headings": ["Purchase"],
            "text": paid_access,
        },
        paid_access,
    )
    raw = json.dumps(
        {
            "status": "answered",
            "claims": [
                {
                    "text": preview_count,
                    "chunk_id": preview_page["chunk_id"],
                    "quote": preview_count,
                },
                {
                    "text": paid_access,
                    "chunk_id": paid_page["chunk_id"],
                    "quote": paid_access,
                },
            ],
        }
    )
    query = (
        "Do the 7 lessons in the Agent Engineering preview include lifetime access?"
    )

    result = llm.validate_grounded_result(
        raw,
        [preview_page, paid_page],
        query=query,
        target_offer_ids=frozenset(
            {"agent-engineering-free-preview", "agent-engineering"}
        ),
    )

    assert result.status == "validation_failure"
    assert "target-qualified" in result.validation_error


@pytest.mark.parametrize(
    ("query", "span"),
    [
        (
            "Does mentorship include lifetime course access?",
            (
                "A senior AI consultant runs $200–500 an hour, with retainers "
                "from $3,000 a month."
            ),
        ),
        (
            "Does mentorship include resume and project reviews?",
            (
                "A single mentor runs $120–450 a month, with resume reviews "
                "billed $150–300 each."
            ),
        ),
    ],
)
def test_competitor_comparison_spans_are_never_offer_evidence(
    query: str, span: str
) -> None:
    page = _with_spans(
        {
            "chunk_id": "mentorship-comparison",
            "title": "Towards AI Mentorship",
            "kind": "mentorship",
            "offer_id": "mentorship",
            "entity_id": "offer:mentorship",
            "url": "https://towardsai.com/academy/mentorship/",
            "headings": ["Comparison"],
            "text": span,
        },
        span,
    )

    result = _query_bound_result(page, query, "mentorship")

    assert result.status == "validation_failure"
    assert "competitor comparison" in result.validation_error
