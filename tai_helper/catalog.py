from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qs, urlparse

from .settings import repo_root, settings

WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.-]*")


@lru_cache(maxsize=1)
def pages_payload() -> dict[str, Any]:
    payload = json.loads((repo_root() / "data" / "pages.json").read_text())
    additions_path = repo_root() / "data" / "towardsai_com_pages.json"
    if additions_path.is_file():
        additions = json.loads(additions_path.read_text())
        payload["pages"] = [*payload["pages"], *additions.get("pages", [])]
    return payload


@lru_cache(maxsize=1)
def assistant_notes() -> dict[str, Any]:
    return json.loads((repo_root() / "data" / "assistant_notes.json").read_text())


def forced_prompts() -> list[str]:
    return list(assistant_notes()["forced_prompts"])


def pages() -> list[dict[str, Any]]:
    return list(pages_payload()["pages"])


def tokenize(text: str) -> set[str]:
    return {token.lower() for token in WORD_RE.findall(text.lower()) if len(token) > 2}


def normalized_path(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/") or "/"
    return host, path


def allowed_paths_by_host() -> dict[str, list[str]]:
    result: dict[str, set[str]] = {}
    for page in pages():
        host = str(page.get("host", "")).lower()
        path = str(page.get("path", "/")).rstrip("/") or "/"
        if host:
            result.setdefault(host, set()).add(path)
            if host in {"towardsai.com", "towardsai.net"}:
                result.setdefault(f"www.{host}", set()).add(path)
    return {host: sorted(paths) for host, paths in result.items()}


def page_is_allowed(url: str) -> bool:
    host, path = normalized_path(url)
    parsed = urlparse(url)
    if not host:
        return False
    if path.startswith(("/courses/take", "/enroll", "/order", "/checkout", "/cart")):
        return False
    if path.startswith(
        (
            "/users",
            "/account",
            "/admin",
            "/wp-admin",
            "/wp-login",
            "/wp-json",
            "/wp-content",
            "/wp-includes",
            "/xmlrpc.php",
        )
    ):
        return False
    if "preview" in parse_qs(parsed.query):
        return False
    if host in {item.lower() for item in settings.site_wide_hosts}:
        return True
    allowed = allowed_paths_by_host()
    return path in allowed.get(host, [])


def source_for_url(url: str) -> dict[str, Any] | None:
    host, path = normalized_path(url)
    for page in pages():
        if (
            str(page.get("host", "")).lower() == host
            and (str(page.get("path", "/")).rstrip("/") or "/") == path
        ):
            return page
    return None


def retrieve(
    query: str, *, current_url: str = "", limit: int = 7
) -> list[dict[str, Any]]:
    query_tokens = tokenize(query)
    scored: list[tuple[float, dict[str, Any]]] = []
    current = source_for_url(current_url)
    notes_text = json.dumps(assistant_notes(), ensure_ascii=False)

    synthetic_notes = {
        "title": "Towards AI Helper Routing Notes",
        "url": "internal://assistant-notes",
        "kind": "routing_notes",
        "text": notes_text,
        "headings": [],
        "links": [],
    }
    all_pages = [synthetic_notes, *pages()]

    for page in all_pages:
        text = " ".join(
            [
                str(page.get("title", "")),
                str(page.get("kind", "")),
                " ".join(str(item) for item in page.get("headings", [])[:30]),
                str(page.get("meta_description", "")),
                str(page.get("text", ""))[:8000],
            ]
        )
        tokens = tokenize(text)
        overlap = len(query_tokens & tokens)
        score = float(overlap)
        kind = page.get("kind", "")
        lowered = query.lower()
        page_url = str(page.get("url", "")).lower()
        if page is current:
            score += 7.0
        if kind == "routing_notes":
            score += 5.0
        if str(page.get("host", "")).lower() == "towardsai.com":
            score += 1.5
        if "company" in lowered or "b2b" in lowered or "training" in lowered:
            if kind == "b2b":
                score += 8.0
        if "mentor" in lowered or "mentorship" in lowered:
            if kind == "mentorship" or "mentorship" in page_url:
                score += 10.0
        if "free" in lowered or "youtube" in lowered or "resource" in lowered:
            if kind in {"free_resource", "free_content_external", "community"}:
                score += 7.0
        if "book" in lowered or "amazon" in lowered:
            if kind in {"book", "book_external"}:
                score += 8.0
        if "bundle" in lowered or "all" in lowered or "value" in lowered:
            if "get-it-all" in page_url:
                score += 8.0
        if any(term in lowered for term in ("codex", "claude", "coding agent")):
            if "agentic-developer-conversion" in page_url:
                score += 12.0
        if "software developer" in lowered or (
            "ai engineer" in lowered
            and any(term in lowered for term in ("company", "team", "training"))
        ):
            if "software-developer-to-ai-engineer" in page_url:
                score += 10.0
        if any(
            term in lowered
            for term in ("consulting", "deployment", "value creation", "private equity")
        ):
            if "valuecreation" in page_url:
                score += 10.0
        if "enablement" in lowered or "enterprise academy" in lowered:
            if "enterpriseenablement" in page_url:
                score += 10.0
        if score > 0:
            scored.append((score, page))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [page for _score, page in scored[:limit]]


def sources_from_pages(
    selected: list[dict[str, Any]], limit: int = 4
) -> list[dict[str, str]]:
    result = []
    for page in selected:
        url = str(page.get("url", ""))
        if url.startswith("internal://"):
            continue
        result.append(
            {
                "title": str(page.get("title", "")) or url,
                "url": url,
                "kind": str(page.get("kind", "page")),
            }
        )
    seen = set()
    unique = []
    for source in result:
        if source["url"] not in seen:
            seen.add(source["url"])
            unique.append(source)
    return unique[:limit]


def in_scope(text: str, history: list[str] | None = None) -> bool:
    haystack = " ".join([text, *(history or [])]).lower()
    allowed_terms = {
        "course",
        "courses",
        "bundle",
        "academy",
        "towards ai",
        "mentor",
        "mentorship",
        "training",
        "company",
        "business",
        "team",
        "consulting",
        "resource",
        "resources",
        "youtube",
        "book",
        "amazon",
        "learn",
        "learning",
        "python",
        "llm",
        "agent",
        "agents",
        "genai",
        "certificate",
        "refund",
        "price",
        "coupon",
        "discount",
        "promo",
        "career",
    }
    return any(term in haystack for term in allowed_terms)


def coupon_intent(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in ("coupon", "promo code", "discount code"))


def coupon_followup(text: str, history: list[str]) -> bool:
    lowered = " ".join([*history, text]).lower()
    prior_coupon_mentions = sum(
        lowered.count(term) for term in ("coupon", "promo code", "discount code")
    )
    return prior_coupon_mentions >= 2 or any(
        term in text.lower()
        for term in ("please", "really", "need", "student", "can't")
    )
