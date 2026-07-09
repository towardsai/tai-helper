from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any

import requests
from google import genai

from .catalog import assistant_notes
from .settings import settings

OPENROUTER_PROVIDER = "openrouter"
GEMINI_PROVIDER = "google_genai"
DEFAULT_TEMPERATURE = 0.2
logger = logging.getLogger(__name__)


SYSTEM_INSTRUCTION = """You are Towards AI Helper, a concise public assistant for anonymous prospective students.

Your only job is to help users choose Towards AI courses, bundles, mentorship,
free resources, the book, community, or B2B training/consulting.

Rules:
- Stay on this scope. If asked general AI, coding, homework, news, or unrelated questions, briefly say you can only help with choosing Towards AI learning/training options.
- Do not teach course lesson content, reveal course material, or provide detailed technical lessons. Give high-level fit guidance and link to relevant public pages.
- Keep answers short: usually 2-5 sentences plus links when useful.
- For course-choice prompts, ask one practical follow-up if you need background, coding level, goals, or company context.
- For B2B/company training/consulting, ask for use case, team background, timeline, and suggest emailing louis@towardsai.net.
- For mentors, recommend the mentorship program and ask what kind of guidance they need.
- For eager learners wanting the best value, recommend the Get it all bundle.
- For coupon code requests, do not provide a code.
"""


@dataclass(frozen=True)
class LLMResult:
    answer: str
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0


def _context_block(selected_pages: list[dict[str, Any]], max_chars: int = 18000) -> str:
    chunks = []
    notes = assistant_notes()
    chunks.append("ROUTING NOTES:\n" + str(notes))
    for index, page in enumerate(selected_pages, start=1):
        if str(page.get("url", "")).startswith("internal://"):
            continue
        text = str(page.get("text", ""))
        chunks.append(
            "\n".join(
                [
                    f"SOURCE {index}",
                    f"Title: {page.get('title', '')}",
                    f"Kind: {page.get('kind', '')}",
                    f"URL: {page.get('url', '')}",
                    f"Headings: {', '.join(str(h) for h in page.get('headings', [])[:12])}",
                    f"Text: {text[:4500]}",
                ]
            )
        )
    block = "\n\n".join(chunks)
    return block[:max_chars]


def build_prompt(
    *,
    query: str,
    selected_prompt: str,
    current_url: str,
    page_title: str,
    history: list[tuple[str, str]],
    selected_pages: list[dict[str, Any]],
) -> str:
    turns = "\n".join(
        f"{role}: {content[:800]}" for role, content in history[-8:] if content.strip()
    )
    return f"""The visitor is on a public Towards AI page.

Current URL: {current_url or "unknown"}
Current page title: {page_title or "unknown"}
Initial forced prompt: {selected_prompt or "unknown"}

Conversation so far:
{turns or "(none)"}

Visitor message:
{query}

Use only these public sales/resource sources and the routing notes:
{_context_block(selected_pages)}

Answer now. Include links only when directly useful. Do not mention internal routing notes.
"""


def _clean_usage(usage: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in usage.items() if value is not None}


def _text_from_openrouter_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content or "")


def _openrouter_headers() -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if settings.openrouter_site_url:
        headers["HTTP-Referer"] = settings.openrouter_site_url
    if settings.openrouter_app_title:
        headers["X-OpenRouter-Title"] = settings.openrouter_app_title
    return headers


def _generate_openrouter_answer(prompt: str) -> LLMResult:
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    response = requests.post(
        f"{settings.openrouter_base_url}/chat/completions",
        headers=_openrouter_headers(),
        json={
            "model": settings.primary_model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
            "temperature": DEFAULT_TEMPERATURE,
            "max_tokens": settings.max_output_tokens,
        },
        timeout=settings.llm_request_timeout_seconds,
    )
    if response.status_code >= 400:
        details = response.text.strip()[:500]
        raise RuntimeError(
            f"OpenRouter request failed with HTTP {response.status_code}: {details}"
        )

    payload = response.json()
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("OpenRouter response did not include any choices")

    message = choices[0].get("message") or {}
    answer = _text_from_openrouter_content(message.get("content")).strip()
    raw_usage = payload.get("usage") or {}
    usage = _clean_usage(
        {
            "input_tokens": raw_usage.get("prompt_tokens")
            or raw_usage.get("input_tokens"),
            "output_tokens": raw_usage.get("completion_tokens")
            or raw_usage.get("output_tokens"),
            "total_tokens": raw_usage.get("total_tokens"),
            "provider": OPENROUTER_PROVIDER,
            "model": settings.primary_model_name,
        }
    )
    return LLMResult(answer=answer, usage=usage)


def _generate_gemini_answer(prompt: str, *, fallback_from: str = "") -> LLMResult:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.fallback_model_name,
        contents=prompt,
        config={
            "system_instruction": SYSTEM_INSTRUCTION,
            "temperature": DEFAULT_TEMPERATURE,
            "max_output_tokens": settings.max_output_tokens,
        },
    )
    usage_metadata = getattr(response, "usage_metadata", None)
    usage = {}
    if usage_metadata is not None:
        usage = {
            "input_tokens": getattr(usage_metadata, "prompt_token_count", None),
            "output_tokens": getattr(usage_metadata, "candidates_token_count", None),
            "total_tokens": getattr(usage_metadata, "total_token_count", None),
        }
    usage.update(
        {
            "provider": GEMINI_PROVIDER,
            "model": settings.fallback_model_name,
        }
    )
    if fallback_from:
        usage["fallback_from"] = fallback_from
    return LLMResult(
        answer=(getattr(response, "text", "") or "").strip(),
        usage=_clean_usage(usage),
    )


def _with_latency(result: LLMResult, started: float) -> LLMResult:
    return replace(result, latency_ms=int((time.monotonic() - started) * 1000))


def generate_answer(prompt: str) -> LLMResult:
    started = time.monotonic()
    primary_error: Exception | None = None

    if settings.openrouter_api_key:
        try:
            result = _generate_openrouter_answer(prompt)
            return _with_latency(result, started)
        except Exception as exc:
            primary_error = exc
            logger.warning(
                "OpenRouter generation failed; falling back to Gemini.",
                exc_info=True,
            )

    try:
        result = _generate_gemini_answer(
            prompt,
            fallback_from=OPENROUTER_PROVIDER if primary_error else "",
        )
        return _with_latency(result, started)
    except Exception as fallback_error:
        if primary_error is not None:
            raise RuntimeError(
                "OpenRouter primary and Gemini fallback generation both failed"
            ) from fallback_error
        raise
