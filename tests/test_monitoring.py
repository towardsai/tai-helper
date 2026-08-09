from __future__ import annotations

from typing import Any

from tai_helper.monitoring import HelperMonitor


class _FakeSpan:
    usage: dict[str, Any] | None = None
    error_info: dict[str, str] | None = None


class _FakeSpanContext:
    def __init__(self, span: _FakeSpan) -> None:
        self.span = span

    def __enter__(self) -> _FakeSpan:
        return self.span

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeOpik:
    def __init__(self) -> None:
        self.span = _FakeSpan()
        self.kwargs: dict[str, Any] = {}

    def start_as_current_span(self, **kwargs: Any) -> _FakeSpanContext:
        self.kwargs = kwargs
        return _FakeSpanContext(self.span)


def test_error_span_uses_current_opik_error_info_schema() -> None:
    opik = _FakeOpik()
    monitor = HelperMonitor(
        query="Unsupported claim",
        answer="Contact the team.",
        current_url="https://towardsai.com/academy/mentorship/",
        selected_prompt="I want to find mentors",
        visitor_key="visitor",
        thread_id="thread",
        sources=[],
        usage={},
        latency_ms=1,
        error_message="grounding validation failed",
    )

    monitor._write_span(opik)

    assert opik.span.error_info == {
        "exception_type": "RuntimeError",
        "message": "grounding validation failed",
        "traceback": "",
    }
