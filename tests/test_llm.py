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
