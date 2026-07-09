from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from .settings import Settings, settings

logger = logging.getLogger(__name__)

_OPIK_CONFIGURED_FOR: tuple[str, str, str] | None = None
_OPIK_IMPORT_WARNING_EMITTED = False


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if limit <= 0 or len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def _import_opik() -> Any | None:
    global _OPIK_IMPORT_WARNING_EMITTED
    try:
        import opik  # type: ignore[import-not-found]
    except Exception:
        if not _OPIK_IMPORT_WARNING_EMITTED:
            logger.warning("Opik monitoring is enabled but the opik package is unavailable.")
            _OPIK_IMPORT_WARNING_EMITTED = True
        return None
    return opik


def _configure_opik(opik: Any, configured: Settings) -> None:
    global _OPIK_CONFIGURED_FOR
    signature = (
        configured.opik_api_key,
        configured.opik_workspace,
        configured.opik_project_name,
    )
    if _OPIK_CONFIGURED_FOR == signature:
        return

    os.environ["OPIK_API_KEY"] = configured.opik_api_key
    os.environ["OPIK_PROJECT_NAME"] = configured.opik_project_name
    if configured.opik_workspace:
        os.environ["OPIK_WORKSPACE"] = configured.opik_workspace

    configure = getattr(opik, "configure", None)
    if callable(configure):
        kwargs = {
            "api_key": configured.opik_api_key,
            "use_local": False,
            "force": True,
            "automatic_approvals": True,
        }
        if configured.opik_workspace:
            kwargs["workspace"] = configured.opik_workspace
        configure(**kwargs)

    _OPIK_CONFIGURED_FOR = signature


@dataclass(slots=True)
class HelperMonitor:
    query: str
    answer: str
    current_url: str
    selected_prompt: str
    visitor_key: str
    thread_id: str
    sources: list[dict[str, str]]
    usage: dict[str, Any]
    latency_ms: int
    error_message: str = ""
    configured: Settings = settings
    opik_module: Any | None = None
    started_at: float = field(default_factory=time.monotonic)

    @property
    def enabled(self) -> bool:
        return bool(self.configured.opik_enabled and self.configured.opik_api_key)

    def flush(self) -> None:
        if not self.enabled:
            return
        opik = self.opik_module or _import_opik()
        if opik is None:
            return
        try:
            _configure_opik(opik, self.configured)
            self._write_span(opik)
        except Exception:
            logger.warning("Failed to write Opik helper trace.", exc_info=True)

    def _write_span(self, opik: Any) -> None:
        tags = ["towards-ai-helper", "public-sales-helper"]
        if self.selected_prompt:
            tags.append("forced-prompt")
        span_kwargs = {
            "name": "towards_ai_helper_chat",
            "type": "llm",
            "input": {
                "query": _truncate(self.query, self.configured.opik_max_text_chars),
                "selected_prompt": self.selected_prompt,
                "current_url": self.current_url,
            },
            "output": {
                "answer": _truncate(self.answer, self.configured.opik_max_text_chars)
            },
            "metadata": {
                "thread_id": self.thread_id,
                "visitor_key": self.visitor_key,
                "current_url": self.current_url,
                "sources": self.sources,
                "latency_ms": self.latency_ms,
                "status": "error" if self.error_message else "completed",
            },
            "tags": tags,
            "project_name": self.configured.opik_project_name,
            "model": self.usage.get("model") or self.configured.model_name,
            "provider": self.usage.get("provider") or "unknown",
            "flush": True,
        }
        with opik.start_as_current_span(**span_kwargs) as span:
            if self.usage:
                span.usage = {
                    "prompt_tokens": self.usage.get("input_tokens"),
                    "completion_tokens": self.usage.get("output_tokens"),
                    "total_tokens": self.usage.get("total_tokens"),
                }
            if self.error_message:
                span.error_info = {
                    "type": "RuntimeError",
                    "message": _truncate(self.error_message, 1000),
                }
