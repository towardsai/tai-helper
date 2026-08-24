from __future__ import annotations

from typing import Any

from tai_helper import llm
from tai_helper.settings import Settings


class FakeDeepSeekResponse:
    def __init__(self, status_code: int, payload: dict[str, Any], text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeUsageMetadata:
    prompt_token_count = 5
    candidates_token_count = 7
    total_token_count = 12


class FakeGeminiResponse:
    text = "Gemini fallback answer"
    usage_metadata = FakeUsageMetadata()


class FakeGeminiModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs) -> FakeGeminiResponse:
        self.calls.append(kwargs)
        return FakeGeminiResponse()


class FakeGeminiClient:
    models = FakeGeminiModels()

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key


def test_prompt_requires_direct_support_for_exact_offer_claims() -> None:
    prompt = llm.build_prompt(
        query="How many courses are included in mentorship?",
        selected_prompt="I want to find mentors",
        current_url="https://towardsai.com/academy/mentorship/",
        page_title="Towards AI Mentorship",
        history=[],
        selected_pages=[
            {
                "title": "Towards AI Mentorship",
                "kind": "mentorship",
                "url": "https://towardsai.com/academy/mentorship/",
                "headings": ["The curriculum comes with the team"],
                "text": (
                    "Towards AI Mentorship includes one course: the 10-Hour LLM "
                    "Fundamentals video course from day one."
                ),
            }
        ],
    )

    instruction = llm.SYSTEM_INSTRUCTION.lower()
    assert "only authority for factual claims" in instruction
    assert "number or names of included products or courses" in instruction
    assert "do not guess" in instruction
    assert "every factual claim must be directly supported" in prompt.lower()
    assert "cannot confirm it" in prompt.lower()
    assert "includes one course" in prompt


def test_prompt_corrects_unsupported_alternatives_with_supported_table_facts() -> None:
    prompt = llm.build_prompt(
        query=(
            "Does the mentorship include two courses of our choice, or only the "
            "LLM Fundamentals course?"
        ),
        selected_prompt="I want to find mentors",
        current_url="https://towardsai.com/academy/mentorship/",
        page_title="Towards AI Mentorship",
        history=[],
        selected_pages=[
            {
                "chunk_id": "mentorship-curriculum-table",
                "title": "Towards AI Mentorship",
                "kind": "mentorship",
                "url": "https://towardsai.com/academy/mentorship/",
                "headings": ["The curriculum comes with the team"],
                "text": (
                    "10-Hour LLM Fundamentals video course $199 Included from "
                    "day one Full Stack AI Engineering · Agent Engineering · "
                    "Master AI for Work $349–499 each 25% off, always"
                ),
            }
        ],
    )

    instruction = llm.SYSTEM_INSTRUCTION.lower()
    assert "unsupported premise or alternative" in instruction
    assert "do not return" in instruction
    assert "merely because the visitor's proposed premise is unsupported" in instruction
    assert 'never infer a total, use "only"' in instruction
    prompt_lower = prompt.lower()
    assert "correction rule" in prompt_lower
    assert (
        "return answered with those facts as separate extractive claims" in prompt_lower
    )
    assert "one table row says an item is included" in prompt_lower
    assert 'do not infer a total or say "only"' in prompt_lower
    assert "do not repeat or deny the visitor's unsupported premise" in prompt_lower
    assert 'never write "not included"' in prompt_lower
    assert (
        "unless those literal words occur in that claim's exact quote" in prompt_lower
    )


def test_generate_answer_uses_deepseek_primary(monkeypatch) -> None:
    request_calls = []
    monkeypatch.setattr(
        llm,
        "settings",
        Settings(deepseek_api_key="deepseek-key", gemini_api_key="gemini-key"),
    )

    def fake_post(*args, **kwargs):
        request_calls.append({"args": args, **kwargs})
        return FakeDeepSeekResponse(
            200,
            {
                "choices": [{"message": {"content": "DeepSeek answer"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 8,
                    "total_tokens": 18,
                },
            },
        )

    monkeypatch.setattr(llm.requests, "post", fake_post)

    result = llm.generate_answer("Visitor prompt")

    assert result.answer == "DeepSeek answer"
    assert result.usage["provider"] == "deepseek"
    assert result.usage["model"] == "deepseek-v4-flash"
    assert result.usage["total_tokens"] == 18
    assert request_calls[0]["args"] == ("https://api.deepseek.com/chat/completions",)
    assert request_calls[0]["headers"] == {
        "Authorization": "Bearer deepseek-key",
        "Content-Type": "application/json",
    }
    assert request_calls[0]["json"]["model"] == "deepseek-v4-flash"
    assert request_calls[0]["json"]["thinking"] == {"type": "disabled"}
    assert request_calls[0]["json"]["messages"][0]["role"] == "system"
    assert request_calls[0]["json"]["messages"][1] == {
        "role": "user",
        "content": "Visitor prompt",
    }


def test_generate_answer_falls_back_to_gemini_when_deepseek_fails(
    monkeypatch,
) -> None:
    FakeGeminiClient.models = FakeGeminiModels()
    monkeypatch.setattr(
        llm,
        "settings",
        Settings(deepseek_api_key="deepseek-key", gemini_api_key="gemini-key"),
    )
    monkeypatch.setattr(
        llm.requests,
        "post",
        lambda *_args, **_kwargs: FakeDeepSeekResponse(
            503, {}, "temporarily unavailable"
        ),
    )
    monkeypatch.setattr(llm.genai, "Client", FakeGeminiClient)

    result = llm.generate_answer("Visitor prompt")

    assert result.answer == "Gemini fallback answer"
    assert result.usage["provider"] == "google_genai"
    assert result.usage["model"] == "gemini-2.5-flash"
    assert result.usage["fallback_from"] == "deepseek"
    assert FakeGeminiClient.models.calls[0]["model"] == "gemini-2.5-flash"


def test_gemini_fallback_disables_thinking_so_it_can_actually_answer(
    monkeypatch,
) -> None:
    """Gemini 2.5 counts thinking tokens against max_output_tokens.

    With thinking left on, an 8k-token grounding prompt spent almost the whole
    420-token budget reasoning and emitted a truncated fragment, so every
    fallback answer failed validation. The fallback looked healthy while
    answering nothing, and only surfaced once the primary ran out of credit.
    """

    FakeGeminiClient.models = FakeGeminiModels()
    monkeypatch.setattr(
        llm,
        "settings",
        Settings(deepseek_api_key="deepseek-key", gemini_api_key="gemini-key"),
    )
    monkeypatch.setattr(
        llm.requests,
        "post",
        lambda *_args, **_kwargs: FakeDeepSeekResponse(402, {}, "Insufficient Balance"),
    )
    monkeypatch.setattr(llm.genai, "Client", FakeGeminiClient)

    llm.generate_answer("Visitor prompt")

    config = FakeGeminiClient.models.calls[0]["config"]
    assert config["thinking_config"] == {"thinking_budget": 0}
    assert config["max_output_tokens"] == 420


def test_openrouter_style_disables_reasoning_with_openrouter_parameter(
    monkeypatch,
) -> None:
    """Each gateway ignores the other's reasoning switch without erroring.

    OpenRouter accepts DeepSeek's ``thinking`` field with HTTP 200 and simply
    does not apply it, so reasoning stays on and its tokens are billed against
    max_tokens. The JSON answer then comes back truncated and fails grounding
    validation, exactly as it did on the Gemini fallback.
    """

    captured: dict[str, object] = {}

    def fake_post(_url, **kwargs):
        captured.update(kwargs["json"])
        captured["headers"] = kwargs["headers"]
        return FakeDeepSeekResponse(
            200, {"choices": [{"message": {"content": "{}"}}]}, ""
        )

    monkeypatch.setattr(
        llm,
        "settings",
        Settings(
            deepseek_api_key="openrouter-key",
            deepseek_base_url="https://openrouter.ai/api/v1",
            primary_api_style="openrouter",
            primary_model_name="deepseek/deepseek-v4-flash",
        ),
    )
    monkeypatch.setattr(llm.requests, "post", fake_post)

    llm.generate_answer("Visitor prompt")

    assert captured["reasoning"] == {"enabled": False}
    assert "thinking" not in captured
    assert captured["model"] == "deepseek/deepseek-v4-flash"


def test_deepseek_style_keeps_the_native_thinking_parameter(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(_url, **kwargs):
        captured.update(kwargs["json"])
        return FakeDeepSeekResponse(
            200, {"choices": [{"message": {"content": "{}"}}]}, ""
        )

    monkeypatch.setattr(
        llm,
        "settings",
        Settings(deepseek_api_key="deepseek-key", primary_api_style="deepseek"),
    )
    monkeypatch.setattr(llm.requests, "post", fake_post)

    llm.generate_answer("Visitor prompt")

    assert captured["thinking"] == {"type": "disabled"}
    assert "reasoning" not in captured
