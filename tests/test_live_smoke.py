from __future__ import annotations

import os
import time

import pytest
import requests

LIVE_BASE_URL = os.getenv("LIVE_SPACE_BASE_URL", "").rstrip("/")
LIVE_HELPER_WIDGET_PATH = "/" + os.getenv(
    "LIVE_HELPER_WIDGET_PATH", "/helper-widget.js"
).strip("/")
RUN_LIVE_CHAT = os.getenv("RUN_LIVE_CHAT_SMOKE", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
HEADERS = {"Origin": "https://academy.towardsai.net"}
FIRST_PROMPT = "I want help deciding which course to take."


def require_live_base_url() -> str:
    if not LIVE_BASE_URL:
        pytest.skip("LIVE_SPACE_BASE_URL is not set")
    return LIVE_BASE_URL


def max_seconds(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def timed_request(method: str, url: str, **kwargs) -> tuple[requests.Response, float]:
    start = time.perf_counter()
    response = requests.request(method, url, **kwargs)
    elapsed = time.perf_counter() - start
    return response, elapsed


@pytest.mark.live
def test_live_health_widget_and_config() -> None:
    base_url = require_live_base_url()

    health, health_seconds = timed_request("GET", f"{base_url}/healthz", timeout=120)
    widget, widget_seconds = timed_request(
        "GET", f"{base_url}{LIVE_HELPER_WIDGET_PATH}", timeout=120
    )
    config, config_seconds = timed_request(
        "GET", f"{base_url}/api/helper/config", timeout=120
    )

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert health_seconds <= max_seconds("LIVE_SMOKE_MAX_HEALTH_SECONDS", 120)
    assert widget.status_code == 200
    assert "Towards AI Helper" in widget.text
    assert "Choose a starter prompt" in widget.text
    assert "isSignedIn" in widget.text
    assert widget_seconds <= max_seconds("LIVE_SMOKE_MAX_WIDGET_SECONDS", 30)
    assert config.status_code == 200
    payload = config.json()
    assert FIRST_PROMPT in payload["forcedPrompts"]
    assert "/courses/agent-engineering" in payload["allowedPathsByHost"]["academy.towardsai.net"]
    assert config_seconds <= max_seconds("LIVE_SMOKE_MAX_CONFIG_SECONDS", 30)


@pytest.mark.live
@pytest.mark.skipif(
    not RUN_LIVE_CHAT,
    reason="RUN_LIVE_CHAT_SMOKE is not enabled",
)
def test_live_chat_returns_concise_answer() -> None:
    base_url = require_live_base_url()
    response, elapsed = timed_request(
        "POST",
        f"{base_url}/api/helper/chat",
        json={
            "query": FIRST_PROMPT,
            "selectedPrompt": FIRST_PROMPT,
            "visitorId": "github-action-smoke",
            "context": {
                "url": "https://academy.towardsai.net/courses/agent-engineering",
                "pageTitle": "Agent course",
                "signedIn": False,
            },
        },
        headers=HEADERS,
        timeout=120,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].strip()
    assert len(payload["answer"]) < 1400
    assert payload["sources"]
    assert elapsed <= max_seconds("LIVE_SMOKE_MAX_CHAT_SECONDS", 90)
