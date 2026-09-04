from __future__ import annotations

import hashlib
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
MAX_EVIDENCE_SPAN_CHARS = 320
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

# Explicit offer names are a hard retrieval boundary, not merely a ranking hint.
# A truthful sentence from another course is still an unsafe answer for the
# course the visitor named. Preview aliases intentionally resolve to a distinct
# offer so paid-course entitlements cannot leak into preview answers.
OFFER_QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "full-stack-ai-engineering": (
        "full stack ai engineering",
        "full stack engineering",
        "full stack",
    ),
    "agent-engineering": (
        "agentic ai engineering",
        "agent engineering",
    ),
    "llm-primer": (
        "10-hour llm fundamentals",
        "10 hour llm fundamentals",
        "llm fundamentals",
        "llm primer",
    ),
    "python-for-ai-engineering": (
        "beginner python for ai engineering",
        "python for ai engineering",
        "beginner python",
        "python course",
    ),
    "ai-for-work": (
        "master ai for work",
        "ai for work",
    ),
    "building-llms-for-production": (
        "building llms for production",
        "building llm for production",
        "the ebook",
        "e-book",
        "ebook",
    ),
    "get-it-all": (
        "get it all bundle",
        "get-it-all bundle",
        "get it all",
    ),
    "from-coding-novice-to-advanced-llm-developer": (
        "from non-coder to ai engineer",
        "from non coder to ai engineer",
        "non-coder to ai engineer bundle",
    ),
    "10-hour-crash-course-into-llm-developer-expert": (
        "from developer to advanced ai engineer",
        "developer to advanced ai engineer bundle",
    ),
    "mentorship": (
        "towards ai mentorship",
        "mentorship",
        "membership",
    ),
}

PREVIEW_OFFER_IDS = {
    "full-stack-ai-engineering": "full-stack-ai-engineering-free-preview",
    "agent-engineering": "agent-engineering-free-preview",
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
    text = str(page.get("text", ""))
    normalized_page_text = SPACE_RE.sub(" ", text).strip()
    page_url_text = str(page.get("url", ""))
    canonical_url = str(page.get("canonical_url") or page.get("url") or "")
    page_url = urlparse(page_url_text)
    canonical = urlparse(canonical_url)
    valid_chunks = (
        isinstance(raw_chunks, list)
        and bool(raw_chunks)
        and all(
            isinstance(chunk, dict)
            and bool(str(chunk.get("chunk_id", "")).strip())
            and bool(str(chunk.get("text", "")).strip())
            and isinstance(chunk.get("evidence_spans"), list)
            and bool(chunk["evidence_spans"])
            and all(
                isinstance(span, dict)
                and bool(str(span.get("span_id", "")).strip())
                and bool(str(span.get("text", "")).strip())
                and len(SPACE_RE.sub(" ", str(span["text"])).strip())
                <= MAX_EVIDENCE_SPAN_CHARS
                and SPACE_RE.sub(" ", str(span["text"])).strip()
                in SPACE_RE.sub(" ", str(chunk["text"])).strip()
                and SPACE_RE.sub(" ", str(span["text"])).strip() in normalized_page_text
                for span in chunk["evidence_spans"]
            )
            and len({str(span["span_id"]).strip() for span in chunk["evidence_spans"]})
            == len(chunk["evidence_spans"])
            for chunk in raw_chunks
        )
        and len({str(chunk["chunk_id"]).strip() for chunk in raw_chunks})
        == len(raw_chunks)
    )
    content_hash = str(page.get("content_hash", ""))
    evidence_hash = str(page.get("evidence_hash", ""))
    canonical_evidence = json.dumps(
        {
            key: value
            for key, value in page.items()
            if key not in {"catalog_generated_at", "evidence_hash"}
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        str(page.get("status", "")).lower() == EVIDENCE_STATUS
        and page.get("retrieval_eligible") is True
        and str(page.get("authority", "")).lower() in EVIDENCE_AUTHORITIES
        and page.get("http_status") == 200
        and page_url.scheme == "https"
        and page_url.hostname in {"towardsai.com", "academy.towardsai.net"}
        and canonical.scheme == "https"
        and canonical.hostname in {"towardsai.com", "academy.towardsai.net"}
        and _canonical_key(page_url_text) == _canonical_key(canonical_url)
        and str(page.get("host", "")).lower() == (page_url.hostname or "").lower()
        and (str(page.get("path", "")).rstrip("/") or "/")
        == (page_url.path.rstrip("/") or "/")
        and CONTENT_HASH_RE.fullmatch(content_hash) is not None
        and hashlib.sha256(text.encode("utf-8")).hexdigest() == content_hash
        and CONTENT_HASH_RE.fullmatch(evidence_hash) is not None
        and hashlib.sha256(canonical_evidence.encode("utf-8")).hexdigest()
        == evidence_hash
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
    candidates = (*pages_without_offer, *best_by_offer.values())
    chunk_id_counts = Counter(
        str(chunk["chunk_id"]).strip()
        for page in candidates
        for chunk in page["chunks"]
    )
    return tuple(
        page
        for page in candidates
        if all(
            chunk_id_counts[str(chunk["chunk_id"]).strip()] == 1
            for chunk in page["chunks"]
        )
    )


def pages() -> list[dict[str, Any]]:
    """Return only fresh, reviewed pages that may be used as factual evidence."""
    return list(_fresh_pages())


def freshness() -> dict[str, Any]:
    """Report how close the evidence catalog is to expiring.

    When every page ages past ``HELPER_CATALOG_MAX_AGE_DAYS`` the helper keeps
    answering requests but has no evidence left, so every reply becomes
    "I couldn't verify that". That failure is invisible to a liveness probe,
    which is how it once ran for a day unnoticed. Surfacing the countdown lets
    the scheduled keepalive fail before visitors see it.
    """

    now = datetime.now(UTC)
    max_age_days = max(settings.catalog_max_age_days, 0)
    ages = [
        (now - fetched_at).total_seconds() / 86_400
        for fetched_at in (
            _parse_timestamp(page.get("fetched_at")) for page in all_pages()
        )
        if fetched_at is not None
    ]
    oldest_age_days = max(ages) if ages else None
    evidence_pages = len(_fresh_pages())
    return {
        "evidencePages": evidence_pages,
        "maxAgeDays": max_age_days,
        "oldestFetchAgeDays": (
            round(oldest_age_days, 2) if oldest_age_days is not None else None
        ),
        "expiresInDays": (
            round(max_age_days - oldest_age_days, 2)
            if oldest_age_days is not None
            else None
        ),
        "fresh": evidence_pages > 0,
    }


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


def offer_ids_for_query(query: str) -> frozenset[str]:
    """Resolve explicitly named offers into a fail-closed retrieval boundary."""

    lowered = SPACE_RE.sub(" ", query.casefold().replace("–", "-")).strip()
    if "webinar" in lowered:
        return frozenset()
    matches = {
        offer_id
        for offer_id, aliases in OFFER_QUERY_ALIASES.items()
        if any(alias in lowered for alias in aliases)
    }
    preview_intent = bool(
        re.search(r"\bpreview\b|\bfree\s+lessons?\b", lowered)
    )
    if preview_intent:
        for paid_offer_id, preview_offer_id in PREVIEW_OFFER_IDS.items():
            if paid_offer_id in matches:
                matches.remove(paid_offer_id)
                matches.add(preview_offer_id)

    if "mentorship" in matches and len(matches) > 1:
        compares_offers = bool(
            re.search(r"\b(?:compare|versus|vs\.?|between)\b", lowered)
        )
        course_subject_includes_mentorship = bool(
            re.search(
                r"(?:full stack|agent(?:ic)? engineering|llm fundamentals|llm primer|"
                r"python for ai|ai for work|building llms|get it all).{0,80}"
                r"\b(?:include|come with|provide|offer|have)\b.{0,50}\bmentor",
                lowered,
            )
        )
        if course_subject_includes_mentorship:
            matches.remove("mentorship")
        elif not compares_offers:
            # When a course is mentioned inside a mentorship access/discount/
            # cancellation question, the mentorship page is the authority.
            matches = {"mentorship"}
    return frozenset(matches)


def evidence_offer_ids_for_query(query: str) -> frozenset[str]:
    """Return offer IDs allowed to supply evidence for this exact question."""

    targets = set(offer_ids_for_query(query))
    fields = requested_fact_fields(query)
    if not fields:
        return frozenset(targets)
    evidence_targets: set[str] = set()
    for field in fields:
        evidence_targets.update(evidence_offer_ids_for_field(query, field))
    return frozenset(evidence_targets)


def evidence_offer_ids_for_field(query: str, field: str) -> frozenset[str]:
    """Return the offers allowed to prove one requested fact field.

    Evidence exceptions are deliberately field-specific. A paid course page can
    state the size of its free preview, but that exception must never expose the
    paid course's access entitlement to a preview access question in the same
    visitor message.
    """

    targets = set(offer_ids_for_query(query))
    # A paid offer page may explicitly state how many lessons its free preview
    # contains. This is the sole preview↔parent exception; paid entitlements,
    # certificates, prices, and refund terms remain outside the preview boundary.
    if field == "lesson_count":
        reverse_preview_ids = {
            preview_id: paid_id for paid_id, preview_id in PREVIEW_OFFER_IDS.items()
        }
        targets.update(
            reverse_preview_ids[offer_id]
            for offer_id in tuple(targets)
            if offer_id in reverse_preview_ids
        )
    return frozenset(targets)


def offer_alias_tokens(offer_ids: frozenset[str] | set[str]) -> frozenset[str]:
    """Return tokens that name the selected offers, for query relevance checks."""

    result: set[str] = set()
    reverse_preview_ids = {
        preview_id: paid_id for paid_id, preview_id in PREVIEW_OFFER_IDS.items()
    }
    for offer_id in offer_ids:
        paid_offer_id = reverse_preview_ids.get(offer_id, offer_id)
        for alias in OFFER_QUERY_ALIASES.get(paid_offer_id, ()):
            result.update(_token_list(alias))
            # Query validation tokenizes without stemming, so retain the exact
            # alias words as well as their retrieval-normalized forms.
            result.update(WORD_RE.findall(alias.casefold()))
        if offer_id in reverse_preview_ids:
            result.update({"free", "preview", "lesson", "lessons"})
    return frozenset(result)


BUNDLE_OFFER_IDS = frozenset(
    {
        "get-it-all",
        "from-coding-novice-to-advanced-llm-developer",
        "10-hour-crash-course-into-llm-developer-expert",
    }
)

TOTAL_LESSON_PATTERNS: dict[str, re.Pattern[str]] = {
    "full-stack-ai-engineering": re.compile(r"\b92\s+lessons\b", re.IGNORECASE),
    "agent-engineering": re.compile(r"\b37\s+lessons\b", re.IGNORECASE),
    "python-for-ai-engineering": re.compile(r"\b38\s+lessons\b", re.IGNORECASE),
    "ai-for-work": re.compile(r"\b98\s+lessons\b", re.IGNORECASE),
    "building-llms-for-production": re.compile(
        r"\b84\s+lessons\b", re.IGNORECASE
    ),
    "agent-engineering-free-preview": re.compile(
        r"\b7\s+(?:free\s+|full\s+)?lessons\b", re.IGNORECASE
    ),
    "full-stack-ai-engineering-free-preview": re.compile(
        r"\b(?:first\s+)?6\s+(?:free\s+|preview\s+)?lessons\b", re.IGNORECASE
    ),
}

DURATION_PATTERNS: dict[str, re.Pattern[str]] = {
    "full-stack-ai-engineering": re.compile(
        r"\b60\+\s*hours\b", re.IGNORECASE
    ),
    "llm-primer": re.compile(
        r"\b10\s*hours?\b|\bfive\s+(?:in-depth\s+)?2-hour\s+(?:video\s+)?sessions\b",
        re.IGNORECASE,
    ),
    "ai-for-work": re.compile(r"\baround\s+20\s+hours\b", re.IGNORECASE),
}

MONTHLY_PLAN_PRICE_RE = re.compile(
    r"\$\s*99(?:\.00)?\s*(?:/\s*month|monthly)\b",
    re.IGNORECASE,
)
YEARLY_PLAN_PRICE_RE = re.compile(
    r"\$\s*899(?:\.00)?.{0,20}(?:/\s*year|per year|once a year)\b",
    re.IGNORECASE,
)
PERMANENT_ACCESS_RE = re.compile(
    r"\b(?:lifetime|forever|keep|retain|retained)\b",
    re.IGNORECASE,
)


def monthly_plan_intent(query: str) -> bool:
    return bool(
        re.search(
            r"\bmonthly\b|\bmonth[- ](?:to|by)[- ]month\b|"
            r"\b(?:per|each)\s+month\b|"
            r"\bmonth\s+(?:price|cost|plan|rate|subscription|membership|mentorship)\b",
            query,
        )
    )


def yearly_plan_intent(query: str) -> bool:
    return bool(
        re.search(
            r"\b(?:yearly|annual|annually)\b|\bper\s+year\b|"
            r"\byear\s+(?:price|cost|plan|rate|subscription|membership|mentorship)\b",
            query,
        )
    )


def _supports_monthly_plan_price(text: str) -> bool:
    for match in MONTHLY_PLAN_PRICE_RE.finditer(text):
        prefix = text[max(0, match.start() - 16) : match.start()]
        suffix = text[match.end() : match.end() + 32]
        if re.search(r"\b(?:from|about)\s*$", prefix):
            continue
        if re.search(r"\bbilled\s+(?:yearly|annually)\b", suffix):
            continue
        return True
    return False


def _supports_yearly_plan_price(text: str) -> bool:
    for match in YEARLY_PLAN_PRICE_RE.finditer(text):
        prefix = text[max(0, match.start() - 16) : match.start()]
        if re.search(r"\b(?:from|about)\s*$", prefix):
            continue
        if "a month" in match.group().casefold():
            continue
        return True
    return False


def requested_fact_fields(query: str) -> frozenset[str]:
    """Classify high-risk facts that require typed, target-bound evidence."""

    lowered = SPACE_RE.sub(" ", query.casefold().replace("–", "-")).strip()
    fields: set[str] = set()
    if re.search(r"\b(?:price|cost|how much)\b|[$€£¥]\s*\d", lowered):
        fields.add("price")
    if "lesson" in lowered and re.search(
        r"\b(?:how many|number of|total|overall)\b|\b\d+\s+lessons?\b|\blessons?\s*[:=]?\s*\d+\b",
        lowered,
    ):
        fields.add("lesson_count")
    if "product" in lowered and re.search(
        r"\b(?:how many|number of|total)\b", lowered
    ):
        fields.add("product_count")
    if "page" in lowered and re.search(
        r"\b(?:how many|number of|total|pages?)\b", lowered
    ):
        fields.add("page_count")
    if re.search(
        r"\bhow long\b|\bhow many hours?\b|\bduration\b|\btime to (?:finish|complete)\b|\b\d+\+?\s*hours?\b|\bhours?\s+(?:long|total)\b|\bhours?.{0,24}\b(?:take|finish|complete)\b",
        lowered,
    ):
        fields.add("duration")
    if re.search(
        r"\bprerequisites?\b|\brequirements?\b|\bprior experience\b|"
        r"\bneed to know\b|\bneed (?:python|coding|code)\b|"
        r"\brequire(?:s|d)? (?:python|coding|code)\b|"
        r"\b(?:no|zero)\s+(?:prior\s+)?(?:coding|software|programming)\s+"
        r"(?:experience|background)\b|\bcomplete beginners?\b|\bfrom scratch\b",
        lowered,
    ):
        fields.add("prerequisite")
    if re.search(r"\bcertificat(?:e|ion|ed)\b", lowered):
        fields.add("certificate")
    if re.search(r"\brefund\b|\bmoney[- ]back\b", lowered):
        fields.add("refund")
    if re.search(r"\bguarantee(?:d)?\b", lowered):
        fields.add("guarantee")
    if re.search(
        r"\bdiscount\b|\bcoupon\b|\bpromo\b|\bsavings?\b|"
        r"\b\d+(?:\.\d+)?%\s+(?:off|less)\b|"
        r"\bsaves?\s+\d+(?:\.\d+)?%",
        lowered,
    ):
        fields.add("discount")
    if re.search(r"\baccess\b|\blifetime\b|\bkeep\b|\bforever\b|\bretain\b", lowered):
        fields.add("access")
    if (
        "mentor" in lowered
        and not re.search(r"\bcancel|\bcancell|\bafter\b|\blifetime\b|\bkeep\b", lowered)
        and re.search(
            r"\b(?:course|courses|llm fundamentals|full stack|agent engineering|master ai for work|choice|choose)\b",
            lowered,
        )
        and re.search(r"\b(?:included|include|access|choice|choose)\b", lowered)
    ):
        fields.add("inclusion")
    return frozenset(fields)


def mixed_preview_fact_request(query: str) -> bool:
    """Return true when one message mixes multiple preview/paid fact scopes.

    A single offer ID cannot safely assign separate clauses to the free preview
    and paid course. These compound questions therefore fail closed and ask the
    visitor to use the contact form (or ask the facts separately).
    """

    lowered = SPACE_RE.sub(" ", query.casefold()).strip()
    preview_intent = bool(re.search(r"\bpreview\b|\bfree\s+lessons?\b", lowered))
    return preview_intent and len(requested_fact_fields(query)) > 1


def _span_supports_fact(
    span_text: str,
    *,
    field: str,
    offer_id: str,
    query: str,
) -> bool:
    text = SPACE_RE.sub(" ", span_text.casefold().replace("–", "-")).strip()
    lowered_query = query.casefold().replace("–", "-")
    is_preview = offer_id.endswith("-free-preview")

    if field == "price":
        if offer_id == "get-it-all":
            asks_where_price_is_displayed = bool(
                "checkout" in lowered_query
                and re.search(
                    r"\b(?:where|shown|displayed|find|see)\b", lowered_query
                )
            )
            return (
                asks_where_price_is_displayed
                and "bundle price shown at checkout" in text
            )
        if offer_id in BUNDLE_OFFER_IDS:
            return "bundle price" in text or (
                "one-time" in text and bool(_CURRENCY_TOKEN_RE.search(text))
            )
        if offer_id == "mentorship":
            if yearly_plan_intent(lowered_query):
                return _supports_yearly_plan_price(text)
            if monthly_plan_intent(lowered_query):
                return _supports_monthly_plan_price(text)
            return _supports_monthly_plan_price(
                text
            ) or _supports_yearly_plan_price(text)
        if is_preview:
            return "free" in text
        return bool(_CURRENCY_TOKEN_RE.search(text)) and any(
            term in text
            for term in ("one-time", "/month", "in total", "lifetime access")
        )

    if field == "lesson_count":
        if re.search(r"\bpreview\b|\bfree\s+lessons?\b", lowered_query):
            preview_count_patterns = {
                "full-stack-ai-engineering": re.compile(
                    r"\b(?:first|try|explore)\s+6\s+lessons\b|\bfirst\s+six\s+lessons\b",
                    re.IGNORECASE,
                ),
                "agent-engineering": re.compile(
                    r"\b(?:first|try|explore)\s+7\s+lessons\b|\bfirst\s+seven\s+lessons\b",
                    re.IGNORECASE,
                ),
            }
            parent_pattern = preview_count_patterns.get(offer_id)
            if parent_pattern is not None:
                # The parent-page exception is count-only. Some CTA DOM blocks
                # combine "Try 7 Lessons Free" with paid lifetime access and a
                # guarantee; never admit that mixed block as preview evidence.
                mixed_paid_entitlement = bool(
                    re.search(
                        r"\b(?:lifetime|guarantee|refund|certificat(?:e|ion)|"
                        r"money[- ]back)\b|[$€£¥]\s*\d",
                        text,
                    )
                )
                return bool(parent_pattern.search(span_text)) and not (
                    mixed_paid_entitlement
                )
        pattern = TOTAL_LESSON_PATTERNS.get(offer_id)
        return bool(pattern and pattern.search(span_text))

    if field == "product_count":
        return bool(re.search(r"\b\d+\s+products\b", text))

    if field == "page_count":
        return bool(re.search(r"\b\d[\d,]*[- ]page\b", text))

    if field == "duration":
        pattern = DURATION_PATTERNS.get(offer_id)
        return bool(pattern and pattern.search(span_text))

    if field == "prerequisite":
        return any(
            term in text
            for term in (
                "prerequisite",
                "prior experience",
                "no prior",
                "no code",
                "no coding",
                "no software background",
                "from scratch",
                "basic python",
                "intermediate python",
                "complete beginner",
                "zero prior",
                "experience with",
            )
        )

    if field == "certificate":
        if not re.search(r"\bcertificat(?:e|ion|ed)\b", text):
            return False
        return not is_preview or any(term in text for term in ("free", "preview"))

    if field == "refund":
        if offer_id == "building-llms-for-production":
            return False
        if offer_id == "mentorship":
            if monthly_plan_intent(lowered_query):
                return (
                    "monthly mentorship can be cancelled" in text
                    or "yearly plan carries a 30-day money-back guarantee" in text
                    or "money-back on yearly" in text
                )
            if yearly_plan_intent(lowered_query):
                return "yearly" in text and "money-back" in text
            return "yearly" in text and "money-back" in text
        return "refund" in text

    if field == "guarantee":
        if re.search(r"\b(?:job|role|internship|placement|career)\b", lowered_query):
            return bool(
                re.search(r"\b(?:job|role|internship|placement|career|pathway)\b", text)
                and re.search(r"\b(?:guarantee|promised|earned)\b", text)
            )
        return _span_supports_fact(
            span_text, field="refund", offer_id=offer_id, query=query
        )

    if field == "discount":
        if offer_id == "mentorship":
            alpha_intent = bool(re.search(r"\b(?:new courses?|alpha)\b", lowered_query))
            plan_intent = bool(
                monthly_plan_intent(lowered_query)
                or yearly_plan_intent(lowered_query)
                or re.search(r"\b(?:billing|plan|save|savings?)\b|\b24%", lowered_query)
            )
            course_intent = bool(
                re.search(
                    r"\b(?:courses?|full stack|agent(?:ic)? engineering|"
                    r"master ai for work|ai for work|existing)\b",
                    lowered_query,
                )
            )
            if sum((alpha_intent, plan_intent, course_intent)) > 1:
                return False
            if alpha_intent:
                return "alpha access" in text and "% off" in text
            if plan_intent:
                if monthly_plan_intent(lowered_query) and not yearly_plan_intent(
                    lowered_query
                ):
                    return False
                return "save 24%" in text or (
                    "24% less" in text and "month to month" in text
                )
            if course_intent:
                return "25% off" in text
            return False
        if offer_id in BUNDLE_OFFER_IDS:
            if re.search(r"\bstudent\b|\bprevious\b|\bbuyer\b", lowered_query):
                return False
            if re.search(r"\bgroup\b|\bteam\b|\btwo or more\b", lowered_query):
                return "group" in text and "bundle pricing" in text
            return "bundle price" in text and "was" in text
        return "discount" in text or (
            "students get 50% off" in text
            and any(term in text for term in ("previous", "groups of two"))
        )

    if field == "access":
        permanent_access_requested = bool(PERMANENT_ACCESS_RE.search(lowered_query))
        if offer_id == "mentorship":
            if re.search(r"\bcancel|\bcancell|\bafter\b", lowered_query):
                return (
                    "course access is active while" in text
                    or "if you cancel" in text
                )
            if permanent_access_requested:
                return bool(PERMANENT_ACCESS_RE.search(text))
            return any(
                term in text
                for term in ("included from day one", "course access", "alpha access")
            )
        if is_preview:
            relation = any(
                term in text for term in ("access", "lifetime", "keep", "forever")
            )
            preview_qualified = any(
                term in text for term in ("free", "preview", "lessons", "no card")
            )
            permanent_qualified = not permanent_access_requested or bool(
                PERMANENT_ACCESS_RE.search(text)
            )
            return relation and preview_qualified and permanent_qualified
        if permanent_access_requested:
            return bool(PERMANENT_ACCESS_RE.search(text))
        return any(term in text for term in ("access", "lifetime", "included"))

    if field == "inclusion":
        if offer_id == "mentorship":
            return any(
                term in text
                for term in ("included from day one", "25% off", "alpha access")
            )
        return "included" in text or "comes with" in text

    return False


def evidence_span_supports_field(
    span_text: str, *, field: str, offer_id: str, query: str
) -> bool:
    """Public validator counterpart to the typed retrieval evidence gate."""

    return _span_supports_fact(
        span_text,
        field=field,
        offer_id=offer_id,
        query=query,
    )


_CURRENCY_TOKEN_RE = re.compile(r"[$€£¥]\s*\d")


def _restrict_chunk_evidence(
    chunk: dict[str, Any], query: str, fields: frozenset[str]
) -> dict[str, Any] | None:
    offer_id = str(chunk.get("offer_id", ""))
    allowed_fields = {
        field
        for field in fields
        if offer_id in evidence_offer_ids_for_field(query, field)
    }
    if not allowed_fields:
        return None
    spans = [
        span
        for span in chunk.get("evidence_spans", [])
        if isinstance(span, dict)
        and any(
            _span_supports_fact(
                str(span.get("text", "")),
                field=field,
                offer_id=offer_id,
                query=query,
            )
            for field in allowed_fields
        )
    ]
    if not spans:
        return None
    restricted = dict(chunk)
    restricted["evidence_spans"] = spans
    return restricted


def normalized_path(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/") or "/"
    return host, path


def allowed_paths_by_host() -> dict[str, list[str]]:
    result: dict[str, set[str]] = {}
    allowed_hosts = {host.lower() for host in settings.allowed_hosts}
    for page in pages_payload()["pages"]:
        # Routing is broader than evidence retrieval. A sitemap URL can safely
        # host the widget even when its canonical page lives on another Towards
        # AI host, but excluded or redirected content must never become evidence.
        if (
            str(page.get("status", "")).lower() not in {"included", "excluded"}
            or page.get("http_status") != 200
        ):
            continue
        discovered_url = str(page.get("discovered_url") or page.get("url") or "")
        parsed = urlparse(discovered_url)
        host = (parsed.hostname or "").lower()
        path = parsed.path.rstrip("/") or "/"
        if host not in allowed_hosts:
            continue
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
                    "entity_id": str(page.get("entity_id", "")),
                    "heading": heading,
                    "headings": [heading] if heading else [],
                    "text": text,
                    "chunk_index": raw_chunk.get("index"),
                    "evidence_spans": list(raw_chunk.get("evidence_spans", [])),
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
    chunk_index = chunk.get("chunk_index")
    kind = str(chunk.get("kind", ""))
    evidence_text = str(chunk.get("text", ""))
    evidence_lower = evidence_text.lower()
    score = 0.0

    course_starter = "help deciding which course to take" in lowered
    canonical_learning_paths = {
        "/academy/full-stack-ai-engineering",
        "/academy/agent-engineering",
        "/academy/llm-primer",
        "/academy/python-for-ai-engineering",
        "/academy/ai-for-work",
        "/academy/building-llms-for-production",
    }
    if course_starter and chunk_path in canonical_learning_paths:
        score += 36.0 if chunk_index == 0 else 6.0

    free_starter = "free resources to learn before committing" in lowered
    if free_starter:
        if kind in {"free_resource", "digital_download"}:
            score += 42.0 + (8.0 if chunk_index == 0 else 0.0)
        elif chunk_path == "/academy/book":
            score += 26.0

    if "integrate ai into my company" in lowered:
        if chunk_path == "/valuecreation":
            score += 52.0 + (12.0 if chunk_index == 0 else 0.0)
        elif chunk_path == "/enterpriseenablement":
            score += 44.0 + (12.0 if chunk_index == 0 else 0.0)
        elif chunk_path.startswith("/enterprise/"):
            score += 28.0 + (8.0 if chunk_index == 0 else 0.0)

    if "training inside my company" in lowered:
        if chunk_path == "/enterpriseenablement":
            score += 44.0
        elif chunk_path.startswith("/enterprise/"):
            score += 28.0

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
        and any(term in lowered for term in ("course", "access", "llm fundamentals"))
        and "llm fundamentals" in evidence_lower
        and "included from day one" in evidence_lower
    ):
        score += 30.0
    if (
        chunk_path == "/academy/mentorship"
        and all(term in lowered for term in ("resume", "project", "review"))
        and any(
            all(
                term in str(span.get("text", "")).casefold()
                for term in ("resume", "project", "review")
            )
            for span in chunk.get("evidence_spans", [])
            if isinstance(span, dict)
        )
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
    if (
        any(term in lowered for term in ("price", "cost", "how much"))
        and "$" in evidence_text
    ):
        score += 10.0
    if (
        "lesson" in lowered
        and any(phrase in lowered for phrase in ("how many", "number of"))
        and re.search(r"\b\d[\d,+]*\s+lessons\b", evidence_lower)
    ):
        score += 16.0
    if (
        "page" in lowered
        and any(phrase in lowered for phrase in ("how many", "number of"))
        and re.search(r"\b\d[\d,]*[- ]page\b", evidence_lower)
    ):
        score += 16.0
    if (
        "product" in lowered
        and any(phrase in lowered for phrase in ("how many", "number of"))
        and re.search(r"\b\d+\s+products\b", evidence_lower)
    ):
        score += 16.0

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

    normalized_query = SPACE_RE.sub(" ", query.strip().lower()).rstrip(".")
    course_paths = {
        "/academy/full-stack-ai-engineering",
        "/academy/agent-engineering",
        "/academy/llm-primer",
        "/academy/python-for-ai-engineering",
        "/academy/ai-for-work",
        "/academy/building-llms-for-production",
    }
    if normalized_query == "i want help deciding which course to take":
        corpus = [chunk for chunk in corpus if chunk.get("path") in course_paths]
    elif normalized_query == "i want help to integrate ai into my company":
        corpus = [
            chunk
            for chunk in corpus
            if chunk.get("path") in {"/valuecreation", "/enterpriseenablement"}
            or str(chunk.get("path", "")).startswith("/enterprise/")
        ]
    elif normalized_query == "i want a training inside my company":
        corpus = [
            chunk
            for chunk in corpus
            if chunk.get("path") == "/enterpriseenablement"
            or str(chunk.get("path", "")).startswith("/enterprise/")
        ]
    elif normalized_query == (
        "i'm looking for more free resources to learn before committing to buying "
        "a course"
    ):
        corpus = [
            chunk
            for chunk in corpus
            if chunk.get("kind") in {"free_resource", "digital_download"}
            or chunk.get("path") == "/academy/book"
        ]
    elif normalized_query == "i want to find mentors":
        corpus = [
            chunk for chunk in corpus if chunk.get("path") == "/academy/mentorship"
        ]

    target_offer_ids = offer_ids_for_query(query)
    evidence_offer_ids = evidence_offer_ids_for_query(query)
    if evidence_offer_ids:
        corpus = [
            chunk
            for chunk in corpus
            if str(chunk.get("offer_id", "")) in evidence_offer_ids
        ]
    fact_fields = requested_fact_fields(query)
    if fact_fields:
        # High-risk facts without an explicit offer are ambiguous by definition.
        # Ask the visitor to contact the team instead of mixing offer policies.
        if not target_offer_ids:
            return []
        if mixed_preview_fact_request(query):
            return []
        restricted_corpus: list[dict[str, Any]] = []
        for chunk in corpus:
            restricted = _restrict_chunk_evidence(chunk, query, fact_fields)
            if restricted is not None:
                restricted_corpus.append(restricted)
        corpus = restricted_corpus
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
        route_boost = _routing_boost(query, chunk)
        if fact_fields and target_offer_ids:
            # Typed evidence has already passed the strict offer/field/qualifier
            # gate. It should not be discarded merely because the visitor used
            # a synonym such as "cancelling" while the page says "cancel".
            route_boost += 20.0
        if not all_matches and route_boost < 10.0:
            continue
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
    diversify = normalized_query in {
        "i want help deciding which course to take",
        "i want help to integrate ai into my company",
        "i'm looking for more free resources to learn before committing to buying a course",
    }
    per_url_limit = 1 if diversify else 2
    for _score, _index, chunk in scored:
        url = str(chunk.get("url", ""))
        if per_url[url] >= per_url_limit:
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
        "preview",
        "lesson",
        "lessons",
        "free",
        "full stack",
        "ebook",
        "e-book",
        "lifetime",
        "access",
        "feature",
        "features",
        "duration",
        "hour",
        "hours",
        "guarantee",
        "support",
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
