from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qs, urlparse

from .settings import repo_root, settings

WORD_RE = re.compile(r"[a-z0-9]+(?:\+\+|#)?")
SPACE_RE = re.compile(r"\s+")
CONTENT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
STOP_WORDS = {
    "a",
    "about",
    "am",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "buying",
    "by",
    "can",
    "committing",
    "complete",
    "decide",
    "deciding",
    "do",
    "does",
    "find",
    "for",
    "from",
    "get",
    "help",
    "how",
    "i",
    "if",
    "in",
    "inside",
    "into",
    "is",
    "it",
    "looking",
    "me",
    "more",
    "my",
    "need",
    "not",
    "of",
    "on",
    "or",
    "our",
    "please",
    "right",
    "that",
    "take",
    "the",
    "their",
    "this",
    "to",
    "us",
    "want",
    "we",
    "what",
    "which",
    "with",
    "you",
    "your",
}
EVIDENCE_STATUS = "included"
EVIDENCE_AUTHORITIES = {
    "academy",
    "academy_detail",
    "canonical",
    "canonical_offer",
    "official_academy",
    "official_site",
    "primary",
    "product_detail",
}
MAX_FUTURE_SKEW_SECONDS = 5 * 60
GENERIC_RETRIEVAL_TERMS = {
    "access",
    "academy",
    "ai",
    "available",
    "best",
    "bot",
    "bundle",
    "chat",
    "choose",
    "choice",
    "course",
    "detail",
    "fact",
    "having",
    "include",
    "included",
    "learn",
    "learning",
    "many",
    "mentioned",
    "offer",
    "option",
    "part",
    "price",
    "pricing",
    "provide",
    "program",
    "resource",
    "towards",
    "training",
    "true",
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
}

# The helper was historically embedded on these exact towardsai.net pages. Keep
# them available for widget routing, but never add them to the evidence corpus.
LEGACY_PUBLIC_PATHS_BY_HOST: dict[str, frozenset[str]] = {
    "towardsai.net": frozenset(
        {
            "/",
            "/academy",
            "/b2b",
            "/book",
            "/community",
            "/let-us-transform-your-team-into-ai-first-employees-to-stay-ahead-of-competitors",
            "/towards-ai-resource-library",
        }
    ),
}


def _catalog_signature(path: str) -> tuple[str, int, int]:
    catalog_path = repo_root() / "data" / path
    try:
        stat = catalog_path.stat()
    except OSError:
        return path, 0, 0
    return path, stat.st_mtime_ns, stat.st_size


def _load_catalog(
    path: str, _signature: tuple[str, int, int]
) -> tuple[list[dict[str, Any]], str]:
    catalog_path = repo_root() / "data" / path
    if not catalog_path.is_file():
        return [], ""
    try:
        payload = json.loads(catalog_path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [], ""
    if not isinstance(payload, dict) or not isinstance(payload.get("pages"), list):
        return [], ""
    generated_at = str(payload.get("generated_at", ""))
    result = []
    for raw_page in payload.get("pages", []):
        page = dict(raw_page)
        page.setdefault("catalog_generated_at", generated_at)
        result.append(page)
    return result, generated_at


@lru_cache(maxsize=8)
def _pages_payload_cached(
    academy_signature: tuple[str, int, int],
    website_signature: tuple[str, int, int],
) -> dict[str, Any]:
    academy_pages, academy_generated_at = _load_catalog("pages.json", academy_signature)
    website_pages, website_generated_at = _load_catalog(
        "towardsai_com_pages.json", website_signature
    )
    return {
        "pages": [*academy_pages, *website_pages],
        "generated_at": {
            "academy": academy_generated_at,
            "website": website_generated_at,
        },
    }


def pages_payload() -> dict[str, Any]:
    return _pages_payload_cached(
        _catalog_signature("pages.json"),
        _catalog_signature("towardsai_com_pages.json"),
    )


@lru_cache(maxsize=1)
def assistant_notes() -> dict[str, Any]:
    return json.loads((repo_root() / "data" / "assistant_notes.json").read_text())


def forced_prompts() -> list[str]:
    return list(assistant_notes()["forced_prompts"])


def _canonical_key(url: str) -> tuple[str, str]:
    host, path = normalized_path(url)
    host = host.removeprefix("www.")
    return host, path


def _authority(page: dict[str, Any]) -> float:
    raw = page.get("authority", "")
    if isinstance(raw, (int, float)):
        return float(raw)
    labels = {
        "canonical": 5.0,
        "canonical_offer": 5.0,
        "official_site": 5.0,
        "primary": 5.0,
        "academy_detail": 4.0,
        "official_academy": 4.0,
        "product_detail": 4.0,
        "academy": 3.5,
        "catalog": 3.0,
        "external": 2.0,
        "curated_external": 2.0,
        "legacy": 1.0,
    }
    if str(raw).lower() in labels:
        return labels[str(raw).lower()]
    host = str(page.get("host") or urlparse(str(page.get("url", ""))).hostname or "")
    if host.removeprefix("www.") == "towardsai.com":
        return 5.0
    if host == "academy.towardsai.net":
        return 3.5
    return 2.0


def _parse_timestamp(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        value = str(raw).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _is_fresh(page: dict[str, Any]) -> bool:
    # A successful per-page fetch time is required. The catalog generation time
    # cannot make reused or failed content appear current.
    fetched_at = _parse_timestamp(page.get("fetched_at"))
    if fetched_at is None:
        return False
    age_seconds = (datetime.now(UTC) - fetched_at).total_seconds()
    max_age_seconds = max(settings.catalog_max_age_days, 0) * 24 * 60 * 60
    return -MAX_FUTURE_SKEW_SECONDS <= age_seconds <= max_age_seconds


def _is_included(page: dict[str, Any]) -> bool:
    return str(page.get("status", "")).lower() == EVIDENCE_STATUS and not bool(
        page.get("excluded")
    )


def _is_evidence_page(page: dict[str, Any]) -> bool:
    raw_chunks = page.get("chunks")
    canonical_url = str(page.get("canonical_url") or page.get("url") or "")
    canonical = urlparse(canonical_url)
    valid_chunks = (
        isinstance(raw_chunks, list)
        and bool(raw_chunks)
        and all(
            isinstance(chunk, dict)
            and bool(str(chunk.get("chunk_id", "")).strip())
            and bool(str(chunk.get("text", "")).strip())
            for chunk in raw_chunks
        )
    )
    return (
        str(page.get("status", "")).lower() == EVIDENCE_STATUS
        and page.get("retrieval_eligible") is True
        and str(page.get("authority", "")).lower() in EVIDENCE_AUTHORITIES
        and page.get("http_status") == 200
        and canonical.scheme == "https"
        and canonical.hostname in {"towardsai.com", "academy.towardsai.net"}
        and CONTENT_HASH_RE.fullmatch(str(page.get("content_hash", ""))) is not None
        and valid_chunks
        and _is_fresh(page)
    )


def all_pages() -> list[dict[str, Any]]:
    """Return known safe pages, including stale pages used only for widget routing."""
    return [page for page in pages_payload()["pages"] if _is_included(page)]


def _page_preference(page: dict[str, Any]) -> tuple[float, float, int]:
    fetched_at = _parse_timestamp(page.get("fetched_at"))
    fetched_value = fetched_at.timestamp() if fetched_at else 0.0
    return _authority(page), fetched_value, len(str(page.get("text", "")))


def _fresh_pages() -> tuple[dict[str, Any], ...]:
    best_by_url: dict[tuple[str, str], dict[str, Any]] = {}
    for page in all_pages():
        if not _is_evidence_page(page):
            continue
        key = _canonical_key(str(page.get("url", "")))
        if not all(key):
            continue
        previous = best_by_url.get(key)
        if previous is None or _page_preference(page) > _page_preference(previous):
            best_by_url[key] = page

    # A canonical offer page wins over lower-authority mirrors for the same
    # product. This prevents conflicting catalog/Thinkific figures from both
    # entering one evidence set.
    best_by_offer: dict[str, dict[str, Any]] = {}
    pages_without_offer: list[dict[str, Any]] = []
    for page in best_by_url.values():
        offer_id = str(page.get("offer_id") or "").strip()
        if not offer_id:
            pages_without_offer.append(page)
            continue
        previous = best_by_offer.get(offer_id)
        if previous is None or _page_preference(page) > _page_preference(previous):
            best_by_offer[offer_id] = page
    return (*pages_without_offer, *best_by_offer.values())


def pages() -> list[dict[str, Any]]:
    """Return only fresh, reviewed pages that may be used as factual evidence."""
    return list(_fresh_pages())


def _token_list(text: str) -> list[str]:
    tokens = []
    for raw_token in WORD_RE.findall(text.lower()):
        token = raw_token.lower()
        if len(token) <= 1 or token in STOP_WORDS:
            continue
        if token == "classes":
            token = "class"
        elif token.endswith("ies") and len(token) > 4:
            token = f"{token[:-3]}y"
        elif token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
            token = token[:-1]
        tokens.append(token)
    return tokens


def tokenize(text: str) -> set[str]:
    return set(_token_list(text))


def normalized_path(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/") or "/"
    return host, path


def allowed_paths_by_host() -> dict[str, list[str]]:
    result: dict[str, set[str]] = {}
    for page in all_pages():
        host = str(
            page.get("host") or urlparse(str(page.get("url", ""))).hostname or ""
        ).lower()
        path = str(page.get("path") or urlparse(str(page.get("url", ""))).path or "/")
        path = path.rstrip("/") or "/"
        if host:
            result.setdefault(host, set()).add(path)
            if host in {"towardsai.com", "towardsai.net"}:
                result.setdefault(f"www.{host}", set()).add(path)
    for host, paths in LEGACY_PUBLIC_PATHS_BY_HOST.items():
        result.setdefault(host, set()).update(paths)
        result.setdefault(f"www.{host}", set()).update(paths)
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
    key = _canonical_key(url)
    for page in pages():
        if _canonical_key(str(page.get("url", ""))) == key:
            return page
    return None


def chunks() -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    for page in pages():
        raw_chunks = page["chunks"]
        for raw_chunk in raw_chunks:
            text = SPACE_RE.sub(" ", str(raw_chunk.get("text", ""))).strip()
            url = str(page.get("url", ""))
            heading = str(raw_chunk.get("heading", "")).strip()
            chunk_id = str(raw_chunk.get("chunk_id", "")).strip()
            result.append(
                {
                    "chunk_id": chunk_id,
                    "title": str(page.get("title", "")),
                    "url": url,
                    "host": str(page.get("host", "")),
                    "path": str(page.get("path", "")),
                    "kind": str(page.get("kind", "page")),
                    "offer_id": str(page.get("offer_id", "")),
                    "heading": heading,
                    "headings": [heading] if heading else [],
                    "text": text,
                    "authority": page.get("authority", _authority(page)),
                    "fetched_at": page.get("fetched_at")
                    or page.get("catalog_generated_at", ""),
                    "status": page.get("status", "active"),
                }
            )
    return tuple(result)


def _expanded_query_tokens(query: str) -> list[str]:
    tokens = _token_list(query)
    expansions = {
        "mentor": ("mentorship",),
        "mentorship": ("mentor",),
        "cost": ("price", "pricing"),
        "price": ("cost", "pricing"),
        "classes": ("course", "courses"),
        "class": ("course",),
        "company": ("enterprise", "team"),
        "business": ("enterprise", "company"),
        "certificate": ("certification",),
    }
    for token in tuple(tokens):
        tokens.extend(expansions.get(token, ()))
    return tokens


def _routing_boost(query: str, chunk: dict[str, Any]) -> float:
    lowered = query.lower()
    url = str(chunk.get("url", "")).lower()
    chunk_path = normalized_path(url)[1]
    score = 0.0

    if chunk_path == "/academy/bundles/get-it-all" and any(
        phrase in lowered for phrase in ("best value", "get it all", "every course")
    ):
        score += 12.0
    if chunk_path == "/academy/python-for-ai-engineering" and any(
        phrase in lowered
        for phrase in (
            "beginner",
            "non-coder",
            "non coder",
            "don't code",
            "do not code",
        )
    ):
        score += 10.0
    if (
        chunk_path == "/enterpriseenablement"
        and "training" in lowered
        and any(phrase in lowered for phrase in ("company", "business", "team"))
    ):
        score += 10.0
    if "help deciding which course" in lowered and chunk_path == "/academy":
        score += 5.0
    if (
        chunk_path == "/academy/mentorship"
        and any(term in lowered for term in ("mentor", "mentorship"))
        and any(term in lowered for term in ("course", "included", "include", "access"))
    ):
        evidence_text = str(chunk.get("text", "")).lower()
        if (
            "llm fundamentals" in evidence_text
            and "included from day one" in evidence_text
        ):
            score += 30.0

    wants_free_preview = "free" in lowered and any(
        term in lowered for term in ("preview", "lesson")
    )
    named_offer_routes = (
        ("full stack", "/academy/full-stack-ai-engineering", 16.0),
        ("agent engineering", "/academy/agent-engineering", 16.0),
        ("llm fundamentals", "/academy/llm-primer", 16.0),
        ("llm primer", "/academy/llm-primer", 16.0),
        ("python", "/academy/python-for-ai-engineering", 16.0),
        ("master ai for work", "/academy/ai-for-work", 16.0),
        ("ai for work", "/academy/ai-for-work", 16.0),
        (
            "from non-coder to ai engineer",
            "/academy/bundles/from-coding-novice-to-advanced-llm-developer",
            18.0,
        ),
        (
            "from developer to advanced ai engineer",
            "/academy/bundles/10-hour-crash-course-into-llm-developer-expert",
            18.0,
        ),
    )
    for phrase, target_path, boost in named_offer_routes:
        if target_path in {
            "/academy/full-stack-ai-engineering",
            "/academy/agent-engineering",
        } and (wants_free_preview or "webinar" in lowered):
            continue
        if phrase in lowered and chunk_path == target_path:
            score += boost
    if (
        "full stack" in lowered
        and wants_free_preview
        and chunk_path == "/academy/full-stack-ai-engineering-free-preview"
    ):
        score += 24.0
    if (
        "agent engineering" in lowered
        and wants_free_preview
        and chunk_path == "/academy/agent-engineering-free-preview"
    ):
        score += 24.0
    if "building llms" in lowered:
        wants_resources = any(term in lowered for term in ("resource", "companion"))
        target_path = (
            "/academy/book"
            if wants_resources
            else "/academy/building-llms-for-production"
        )
        if chunk_path == target_path:
            score += 18.0
    if "webinar" in lowered and chunk_path == "/webinars/agentengineering":
        score += 40.0
    if any(term in lowered for term in ("price", "cost", "how much")) and "$" in str(
        chunk.get("text", "")
    ):
        score += 10.0

    rules = (
        (("mentor", "mentorship"), "/academy/mentorship/", 7.0),
        (
            ("bundle", "best value", "every course", "get it all"),
            "/academy/bundles/",
            4.0,
        ),
        (
            ("codex", "claude", "coding agent"),
            "/enterprise/agentic-developer-conversion/",
            24.0,
        ),
        (
            ("software developer", "developers into ai engineers"),
            "/enterprise/software-developer-to-ai-engineer/",
            24.0,
        ),
        (
            ("consulting", "deployment", "value creation", "private equity"),
            "/valuecreation/",
            20.0,
        ),
        (("enablement", "enterprise academy"), "/enterpriseenablement/", 20.0),
    )
    for phrases, path, boost in rules:
        target_path = path.rstrip("/") or "/"
        path_matches = (
            chunk_path.startswith(target_path + "/")
            if target_path == "/academy/bundles"
            else chunk_path == target_path
        )
        if any(phrase in lowered for phrase in phrases) and path_matches:
            score += boost
    return score


def retrieve(
    query: str, *, current_url: str = "", limit: int = 7
) -> list[dict[str, Any]]:
    """Retrieve fresh evidence chunks. An empty result means the helper must abstain."""
    query_terms = _expanded_query_tokens(query)
    if not query_terms or limit <= 0:
        return []
    corpus = list(chunks())
    if not corpus:
        return []

    document_terms = [_token_list(str(chunk.get("text", ""))) for chunk in corpus]
    document_frequency: Counter[str] = Counter()
    for terms in document_terms:
        document_frequency.update(set(terms))
    average_length = sum(map(len, document_terms)) / max(len(document_terms), 1)
    query_counts = Counter(query_terms)
    query_term_set = set(query_counts)
    informative_query_terms = {
        term
        for term in query_term_set - GENERIC_RETRIEVAL_TERMS
        if not term.replace(".", "", 1).isdigit()
    }
    current_key = _canonical_key(current_url)
    scored: list[tuple[float, int, dict[str, Any]]] = []

    for index, (chunk, terms) in enumerate(zip(corpus, document_terms, strict=True)):
        counts = Counter(terms)
        matched = set(query_counts) & set(counts)
        searchable = " ".join(
            [
                str(chunk.get("title", "")),
                str(chunk.get("heading", "")),
                str(chunk.get("path", "")),
            ]
        )
        metadata_tokens = tokenize(searchable)
        metadata_matches = set(query_counts) & metadata_tokens
        all_matches = matched | metadata_matches
        if not all_matches:
            continue
        route_boost = _routing_boost(query, chunk)
        informative_matches = all_matches & informative_query_terms
        trusted_route = route_boost >= 10.0
        if informative_query_terms and not informative_matches and not trusted_route:
            continue
        informative_coverage = len(informative_matches) / max(
            len(informative_query_terms), 1
        )
        if (
            informative_query_terms
            and informative_coverage < 0.67
            and not trusted_route
        ):
            continue

        score = 0.0
        length = max(len(terms), 1)
        for term, query_frequency in query_counts.items():
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            frequency_docs = document_frequency.get(term, 0)
            inverse_frequency = math.log(
                1 + (len(corpus) - frequency_docs + 0.5) / (frequency_docs + 0.5)
            )
            denominator = frequency + 1.2 * (
                0.25 + 0.75 * length / max(average_length, 1)
            )
            score += (
                inverse_frequency
                * (frequency * 2.2 / denominator)
                * min(query_frequency, 2)
            )
        score += 1.4 * len(metadata_matches)
        score += 2.0 * len(all_matches)
        # In a tiny corpus BM25's inverse-frequency value is small even for an
        # exact match. Reward multiple distinct, non-generic matches while a
        # lone generic word such as "course" still cannot retrieve a page.
        if len(informative_matches) >= 2:
            score += 0.75 * len(informative_matches)
        score += route_boost
        if current_key == _canonical_key(str(chunk.get("url", ""))):
            score += 1.0
        score *= 0.85 + min(_authority(chunk), 5.0) * 0.05
        if score >= 1.0:
            scored.append((score, index, chunk))

    scored.sort(key=lambda item: (-item[0], item[1]))
    result: list[dict[str, Any]] = []
    per_url: defaultdict[str, int] = defaultdict(int)
    for _score, _index, chunk in scored:
        url = str(chunk.get("url", ""))
        if per_url[url] >= 2:
            continue
        result.append(chunk)
        per_url[url] += 1
        if len(result) >= limit:
            break
    return result


def sources_from_pages(
    selected: list[dict[str, Any]], limit: int = 4
) -> list[dict[str, str]]:
    result = []
    for page in selected:
        url = str(page.get("url", ""))
        if not url or url.startswith("internal://"):
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
    lowered = text.lower()
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
        "beginner",
        "code",
        "coder",
        "coding",
        "team",
        "consulting",
        "developer",
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
        "certification",
        "refund",
        "price",
        "pricing",
        "cost",
        "coupon",
        "discount",
        "engineer",
        "experience",
        "founder",
        "promo",
        "professional",
        "career",
    }
    if any(term in lowered for term in allowed_terms):
        return True

    # Conversation history is useful only for genuinely referential follow-ups.
    # It must never make a new, unrelated question appear in scope.
    followup_terms = {
        "it",
        "that",
        "this",
        "they",
        "them",
        "those",
        "one",
        "ones",
        "included",
        "access",
        "prerequisites",
    }
    raw_words = {token.lower() for token in WORD_RE.findall(lowered)}
    is_followup = len(raw_words) <= 10 and bool(raw_words & followup_terms)
    if not is_followup:
        return False
    prior = " ".join(history or []).lower()
    return any(term in prior for term in allowed_terms)


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


def clear_catalog_caches() -> None:
    """Clear catalog caches after an on-disk refresh or in tests."""
    _pages_payload_cached.cache_clear()
    assistant_notes.cache_clear()
