from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import llm
from .catalog import (
    allowed_paths_by_host,
    coupon_followup,
    coupon_intent,
    forced_prompts,
    in_scope,
    page_is_allowed,
    retrieve,
    sources_from_pages,
)
from .monitoring import HelperMonitor
from .rate_limiter import FixedWindowRateLimiter, RateLimit
from .schemas import HelperChatRequest, HelperChatResponse, SourceOut
from .settings import repo_root, settings

logger = logging.getLogger(__name__)

app = FastAPI(title="Towards AI Helper API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def reject_oversized_bodies(request: Request, call_next):
    content_length = request.headers.get("content-length")
    try:
        too_large = (
            content_length is not None and int(content_length) > settings.max_body_bytes
        )
    except ValueError:
        too_large = False
    if too_large:
        return JSONResponse({"detail": "Request body too large"}, status_code=413)
    return await call_next(request)


STATIC_DIR = repo_root() / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


visitor_limiter = FixedWindowRateLimiter(
    (
        RateLimit("per_minute", settings.rate_limit_per_minute, 60),
        RateLimit("per_day", settings.rate_limit_per_day, 24 * 60 * 60),
    )
)
ip_limiter = FixedWindowRateLimiter(
    (
        RateLimit("ip_per_minute", settings.rate_limit_per_minute, 60),
        RateLimit("ip_per_day", settings.rate_limit_per_day, 24 * 60 * 60),
    )
)
global_limiter = FixedWindowRateLimiter(
    (RateLimit("global_per_minute", settings.rate_limit_global_per_minute, 60),)
)


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _header_host_allowed(value: str) -> bool:
    if not value:
        return False
    hostname = (urlparse(value).hostname or "").lower()
    return any(
        hostname == allowed.lower() or hostname.endswith("." + allowed.lower())
        for allowed in settings.allowed_hosts
    )


def _require_allowed_browser_origin(request: Request) -> None:
    origin = request.headers.get("origin", "")
    referer = request.headers.get("referer", "")
    if _header_host_allowed(origin) or _header_host_allowed(referer):
        return
    raise HTTPException(
        status_code=403,
        detail="Requests must come from a configured Towards AI public site.",
    )


def _rate_key(request: Request, payload: HelperChatRequest) -> str:
    visitor_id = payload.visitorId.strip()[:80]
    if visitor_id:
        return f"visitor:{visitor_id}"
    return f"ip:{_client_ip(request)}"


def _check_rate_limits(request: Request, payload: HelperChatRequest) -> None:
    global_result = global_limiter.check("global")
    if not global_result.allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Global rate limit exceeded: {global_result.limit_name}",
            headers={"Retry-After": str(global_result.retry_after_seconds)},
        )

    ip_result = ip_limiter.check(_client_ip(request))
    if not ip_result.allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {ip_result.limit_name}",
            headers={"Retry-After": str(ip_result.retry_after_seconds)},
        )

    visitor_result = visitor_limiter.check(_rate_key(request, payload))
    if not visitor_result.allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {visitor_result.limit_name}",
            headers={"Retry-After": str(visitor_result.retry_after_seconds)},
        )


def _history_text(payload: HelperChatRequest) -> list[str]:
    return [turn.content for turn in payload.history[-settings.max_history_turns :]]


def _validate_payload(payload: HelperChatRequest) -> None:
    if payload.context.signedIn:
        raise HTTPException(
            status_code=403, detail="Helper is only for signed-out visitors."
        )
    if not page_is_allowed(payload.context.url):
        raise HTTPException(
            status_code=403, detail="Helper is only available on public pages."
        )
    if len(payload.query.strip()) > settings.max_query_chars:
        raise HTTPException(status_code=400, detail="Question is too long.")
    if not payload.history and payload.query.strip() not in forced_prompts():
        raise HTTPException(
            status_code=400,
            detail="Please choose one of the starter prompts first.",
        )


def _fixed_coupon_answer(payload: HelperChatRequest) -> str:
    history = _history_text(payload)
    if coupon_followup(payload.query, history):
        return (
            "I can't provide a coupon code here. If you have specific context, "
            "email louis@towardsai.net with what you need and we will do the best possible."
        )
    return (
        "I can't provide a coupon code here. The best value option is usually the "
        "Get It All bundle: https://towardsai.com/academy/bundles/get-it-all/"
    )


def _out_of_scope_answer() -> str:
    return (
        "I can only help with choosing Towards AI courses, bundles, mentorship, "
        "free resources, the book, or B2B training. Tell me your background and goal, "
        "and I can point you to the right option."
    )


def _fallback_answer() -> str:
    return (
        "I can help, but I need one detail: are you learning for your own career, "
        "building AI products, or looking for company training?"
    )


async def _flush_monitor(monitor: HelperMonitor) -> None:
    await asyncio.to_thread(monitor.flush)


def _schedule_monitor(monitor: HelperMonitor) -> None:
    if not monitor.enabled:
        return
    task = asyncio.create_task(_flush_monitor(monitor))

    def log_failure(done: asyncio.Task) -> None:
        try:
            done.result()
        except Exception:
            logger.warning("Background Opik monitor flush failed.", exc_info=True)

    task.add_done_callback(log_failure)


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/helper-widget.js")
@app.get("/widget.js")
def widget() -> FileResponse:
    path = STATIC_DIR / "widget.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Widget not found")
    return FileResponse(path, media_type="application/javascript")


@app.get("/api/helper/config")
def public_config() -> dict[str, Any]:
    opik_ready = bool(settings.opik_enabled and settings.opik_api_key)
    return {
        "name": "Towards AI Helper",
        "allowedHosts": list(settings.allowed_hosts),
        "siteWideHosts": list(settings.site_wide_hosts),
        "allowedPathsByHost": allowed_paths_by_host(),
        "forcedPrompts": forced_prompts(),
        "rateLimits": {
            "perMinute": settings.rate_limit_per_minute,
            "perDay": settings.rate_limit_per_day,
        },
        "monitoring": {
            "opikEnabled": opik_ready,
            "opikProject": settings.opik_project_name if opik_ready else "",
        },
    }


@app.post("/api/helper/chat")
async def chat(request: Request, payload: HelperChatRequest) -> HelperChatResponse:
    _require_allowed_browser_origin(request)
    _validate_payload(payload)
    _check_rate_limits(request, payload)

    query = payload.query.strip()
    thread_id = payload.threadId.strip() or uuid4().hex
    selected_pages = retrieve(query, current_url=payload.context.url)
    sources = sources_from_pages(selected_pages)
    usage: dict[str, Any] = {}
    latency_ms = 0
    error_message = ""

    try:
        if coupon_intent(query):
            answer = _fixed_coupon_answer(payload)
        elif not in_scope(query, _history_text(payload)):
            answer = _out_of_scope_answer()
        else:
            prompt = llm.build_prompt(
                query=query,
                selected_prompt=payload.selectedPrompt or query,
                current_url=payload.context.url,
                page_title=payload.context.pageTitle,
                history=[
                    (turn.role, turn.content)
                    for turn in payload.history[-settings.max_history_turns :]
                ],
                selected_pages=selected_pages,
            )
            result = await asyncio.to_thread(llm.generate_answer, prompt)
            answer = result.answer or _fallback_answer()
            usage = result.usage
            latency_ms = result.latency_ms
    except Exception:
        error_message = "helper generation failed"
        logger.exception("helper generation failed")
        answer = _fallback_answer()

    monitor = HelperMonitor(
        query=query,
        answer=answer,
        current_url=payload.context.url,
        selected_prompt=payload.selectedPrompt or query,
        visitor_key=_rate_key(request, payload),
        thread_id=thread_id,
        sources=sources,
        usage=usage,
        latency_ms=latency_ms,
        error_message=error_message,
    )
    _schedule_monitor(monitor)

    return HelperChatResponse(
        answer=answer,
        threadId=thread_id,
        sources=[SourceOut(**source) for source in sources],
        usage=usage,
    )
