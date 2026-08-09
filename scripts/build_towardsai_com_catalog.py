from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse
from xml.etree import ElementTree

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COM_OUTPUT = ROOT / "data" / "towardsai_com_pages.json"
DEFAULT_ACADEMY_OUTPUT = ROOT / "data" / "pages.json"
# Kept for callers of the original, .com-only builder.
DEFAULT_OUTPUT = DEFAULT_COM_OUTPUT

COM_SITEMAP_URL = "https://towardsai.com/pages-sitemap.xml"
ACADEMY_SITEMAP_URL = "https://academy.towardsai.net/sitemap.xml"

COM_HOSTS = frozenset({"towardsai.com", "www.towardsai.com"})
ACADEMY_HOSTS = frozenset({"academy.towardsai.net"})

MIN_CHUNK_CHARS = 1_200
TARGET_CHUNK_CHARS = 1_550
MAX_CHUNK_CHARS = 1_800
MAX_EVIDENCE_SPAN_CHARS = 320
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]*[A-Z0-9])")
SPAN_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

# Collection pages are still scanned and hashed, but are not factual evidence:
# their compact cards have contradicted the corresponding canonical detail pages.
COM_EXCLUSIONS = {
    "/": "homepage offer summaries can conflict with canonical detail pages",
    "/academy": "catalog summary can conflict with canonical offer detail pages",
    "/academy/bundles": (
        "catalog summary can conflict with canonical bundle detail pages"
    ),
}

# These Thinkific pages are published in the sitemap, but are unfinished template,
# collection, or legacy copies of authoritative product pages. They are fetched so
# that a refresh records their existence and hash, then withheld from retrieval.
ACADEMY_EXCLUSIONS = {
    "/collections": ("catalog summary can lag behind canonical offer detail pages"),
    "/collections/products": (
        "catalog summary can lag behind canonical offer detail pages"
    ),
    "/collections/developers": (
        "catalog summary can lag behind canonical offer detail pages"
    ),
    "/collections/professionals": (
        "catalog summary can lag behind canonical offer detail pages"
    ),
    "/pages/free-resources": (
        "legacy resource summary conflicts with the current LLM Fundamentals offer"
    ),
    "/pages/agent-course-landing-page": (
        "legacy duplicate of the Agent Engineering course page"
    ),
    "/pages/agent-course-new-page-cro": (
        "alternate sales copy duplicates the Agent Engineering course page"
    ),
    "/pages/towards-ai-insider": "unfinished template content",
    "/pages/webinar": "unfinished template content",
    "/pages/new-home-page": "legacy duplicate of the Academy home page",
    "/pages/landing-page-free-email-course": "unfinished template content",
    "/pages/choose-your-course": "legacy duplicate of the courses collection",
}

# Cross-site identifiers let retrieval prefer the canonical .com description of
# an offer while retaining the Thinkific purchase/enrolment page as provenance.
OFFER_PATHS = {
    "/academy/full-stack-ai-engineering": "full-stack-ai-engineering",
    "/courses/beginner-to-advanced-llm-dev": "full-stack-ai-engineering",
    "/academy/agent-engineering": "agent-engineering",
    "/academy/agentic-ai-engineering": "agent-engineering",
    "/courses/agent-engineering": "agent-engineering",
    "/pages/agent-course-landing-page": "agent-engineering",
    "/pages/agent-course-new-page-cro": "agent-engineering",
    "/academy/llm-primer": "llm-primer",
    "/courses/llm-primer": "llm-primer",
    "/academy/python-for-ai-engineering": "python-for-ai-engineering",
    "/courses/python-for-genai": "python-for-ai-engineering",
    "/academy/ai-for-work": "ai-for-work",
    "/courses/ai-business-professionals": "ai-for-work",
    "/academy/building-llms-for-production": "building-llms-for-production",
    "/courses/buildingllmsforproduction": "building-llms-for-production",
    "/academy/mentorship": "mentorship",
    "/bundles/tai-mentorship": "mentorship",
    "/academy/bundles/get-it-all": "get-it-all",
    "/bundles/get-it-all": "get-it-all",
    "/academy/bundles/from-coding-novice-to-advanced-llm-developer": (
        "from-coding-novice-to-advanced-llm-developer"
    ),
    "/bundles/from-coding-novice-to-advanced-llm-developer": (
        "from-coding-novice-to-advanced-llm-developer"
    ),
    "/academy/bundles/10-hour-crash-course-into-llm-developer-expert": (
        "10-hour-crash-course-into-llm-developer-expert"
    ),
    "/bundles/10-hour-crash-course-into-llm-developer-expert": (
        "10-hour-crash-course-into-llm-developer-expert"
    ),
    "/academy/agent-engineering-free-preview": ("agent-engineering-free-preview"),
    "/academy/full-stack-ai-engineering-free-preview": (
        "full-stack-ai-engineering-free-preview"
    ),
    "/products/digital_downloads/agents-cheatsheet": "agents-cheatsheet",
    "/products/digital_downloads/anti-slop-framework": "anti-slop-framework",
}

# These two resources do not belong to either first-party sitemap. Keeping the
# small, explicit allowlist avoids turning arbitrary outbound links into evidence.
MANUAL_SAFE_RESOURCES: tuple[dict[str, Any], ...] = (
    {
        "url": ("https://www.amazon.com/s?k=Towards+AI+Building+LLMs+for+Production"),
        "kind": "book_external",
        "title": "Towards AI book on Amazon",
        "text": (
            "Building LLMs for Production by Towards AI — Amazon search resource."
        ),
        "links": [
            {
                "text": "Amazon book search",
                "url": (
                    "https://www.amazon.com/s?k=Towards+AI+Building+LLMs+for+Production"
                ),
            }
        ],
    },
    {
        "url": "https://www.youtube.com/channel/UCQNjFuhOJM1YqFTPY1Q_kYQ",
        "kind": "free_content_external",
        "title": "What's AI YouTube channel",
        "text": ("What's AI by Louis-François Bouchard — YouTube channel."),
        "links": [
            {
                "text": "What's AI on YouTube",
                "url": ("https://www.youtube.com/channel/UCQNjFuhOJM1YqFTPY1Q_kYQ"),
            }
        ],
    },
)

# Human-reviewed routing metadata is preserved across sitemap refreshes, but the
# summary is metadata only: factual answers must cite scraped page chunks.
CURATED_COM_METADATA: tuple[dict[str, str], ...] = (
    {
        "url": "https://towardsai.com/",
        "review_title": "Homepage",
        "kind": "page",
        "reviewed_summary": "Towards AI deployment, education, and company overview.",
    },
    {
        "url": "https://towardsai.com/academy/",
        "review_title": "Academy hub",
        "kind": "collection",
        "reviewed_summary": "Central comparison page for Towards AI learning paths.",
    },
    {
        "url": "https://towardsai.com/academy/full-stack-ai-engineering/",
        "review_title": "Full Stack AI Engineering",
        "kind": "course",
        "reviewed_summary": "Production LLM product engineering course.",
    },
    {
        "url": "https://towardsai.com/academy/agent-engineering/",
        "review_title": "Agent Engineering",
        "kind": "course",
        "reviewed_summary": "Production-focused agent engineering course.",
    },
    {
        "url": "https://towardsai.com/academy/llm-primer/",
        "review_title": "10-Hour LLM Fundamentals",
        "kind": "course",
        "reviewed_summary": "Focused LLM fundamentals video course.",
    },
    {
        "url": "https://towardsai.com/academy/python-for-ai-engineering/",
        "review_title": "Python for AI Engineering",
        "kind": "course",
        "reviewed_summary": "Beginner Python foundations for AI engineering.",
    },
    {
        "url": "https://towardsai.com/academy/ai-for-work/",
        "review_title": "AI for Work",
        "kind": "course",
        "reviewed_summary": "Practical no-code AI training for professionals.",
    },
    {
        "url": "https://towardsai.com/academy/building-llms-for-production/",
        "review_title": "Building LLMs for Production",
        "kind": "book",
        "reviewed_summary": "Towards AI book and companion learning page.",
    },
    {
        "url": "https://towardsai.com/academy/book/",
        "review_title": "The Book",
        "kind": "book",
        "reviewed_summary": "Towards AI book page.",
    },
    {
        "url": "https://towardsai.com/academy/bundles/",
        "review_title": "Academy bundles",
        "kind": "collection",
        "reviewed_summary": "Central collection of current Academy bundles.",
    },
    {
        "url": "https://towardsai.com/academy/mentorship/",
        "review_title": "Mentorship",
        "kind": "mentorship",
        "reviewed_summary": (
            "Mentorship includes one course, the 10-Hour LLM Fundamentals video "
            "course from day one; the other currently listed courses are 25% off."
        ),
    },
    {
        "url": "https://towardsai.com/academy/about/",
        "review_title": "About",
        "kind": "page",
        "reviewed_summary": "Towards AI Academy and team background.",
    },
    {
        "url": "https://towardsai.com/academy/contact/",
        "review_title": "Contact",
        "kind": "page",
        "reviewed_summary": "Towards AI Academy contact options.",
    },
    {
        "url": "https://towardsai.com/academy/affiliate/",
        "review_title": "Affiliate",
        "kind": "page",
        "reviewed_summary": "Towards AI referral and affiliate program.",
    },
    {
        "url": "https://towardsai.com/academy/full-stack-ai-engineering-free-preview/",
        "review_title": "Full Stack AI Engineering free preview",
        "kind": "free_resource",
        "reviewed_summary": "Free preview of Full Stack AI Engineering.",
    },
    {
        "url": "https://towardsai.com/academy/agent-engineering-free-preview/",
        "review_title": "Agent Engineering free preview",
        "kind": "free_resource",
        "reviewed_summary": "Free preview of Agent Engineering.",
    },
    {
        "url": "https://towardsai.com/academy/bundles/get-it-all/",
        "review_title": "Get It All",
        "kind": "bundle",
        "reviewed_summary": "Broadest Academy course bundle.",
    },
    {
        "url": "https://towardsai.com/academy/bundles/from-coding-novice-to-advanced-llm-developer/",
        "review_title": "From Non-Coder to AI Engineer",
        "kind": "bundle",
        "reviewed_summary": "Bundle path from Python foundations to AI engineering.",
    },
    {
        "url": "https://towardsai.com/academy/bundles/10-hour-crash-course-into-llm-developer-expert/",
        "review_title": "From Developer to Advanced AI Engineer",
        "kind": "bundle",
        "reviewed_summary": "Bundle path from LLM fundamentals to advanced engineering.",
    },
    {
        "url": "https://towardsai.com/enterprise/software-developer-to-ai-engineer/",
        "review_title": "Software Developer to AI Engineer",
        "kind": "b2b",
        "reviewed_summary": "Enterprise AI-engineer conversion program.",
    },
    {
        "url": "https://towardsai.com/enterprise/agentic-developer-conversion/",
        "review_title": "Agentic Developer Conversion",
        "kind": "b2b",
        "reviewed_summary": "Enterprise coding-agent adoption program.",
    },
    {
        "url": "https://towardsai.com/enterpriseenablement/",
        "review_title": "Enterprise Enablement",
        "kind": "b2b",
        "reviewed_summary": "Enterprise AI training and enablement.",
    },
    {
        "url": "https://towardsai.com/valuecreation/",
        "review_title": "Value Creation",
        "kind": "b2b",
        "reviewed_summary": "Custom AI development and value-creation consulting.",
    },
    {
        "url": "https://towardsai.com/webinars/agentengineering/",
        "review_title": "Agent Engineering webinar",
        "kind": "free_resource",
        "reviewed_summary": "Free agent engineering webinar.",
    },
)

SUPPRESSED_TAGS = frozenset(
    {"script", "style", "noscript", "svg", "template", "nav", "footer"}
)
VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "blockquote",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "li",
        "main",
        "p",
        "section",
        "td",
        "th",
    }
)
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
SUPPRESSED_ROLES = frozenset({"navigation", "contentinfo"})
SUPPRESSED_CLASS_TOKENS = frozenset(
    {
        "cookie-banner",
        "cookie-consent",
        "footer",
        "global-footer",
        "global-nav",
        "header",
        "navbar",
        "navigation",
        "site-footer",
        "site-nav",
        "ta-announce",
        # Testimonials, endorsements, simulated conversations, and competitor
        # comparison tables are useful marketing context but are not first-party
        # offer terms. Keeping them citable lets review copy or competitor facts
        # conflict with the actual product specification.
        "ta-ment-thread",
        "ta-ment-vsnote",
        "ta-ment-vswrap",
        "ta-mobile-menu",
        "ta-quote",
        "ta-review",
    }
)

PREVIEW_SUPPRESSED_SECTION_IDS: dict[str, frozenset[str]] = {
    # These sections explicitly describe the paid course, not the free preview.
    "/academy/agent-engineering-free-preview": frozenset({"fullcourse"}),
    "/academy/full-stack-ai-engineering-free-preview": frozenset(
        {"outcomes", "cta"}
    ),
}
PAGE_SUPPRESSED_CLASS_TOKENS: dict[str, frozenset[str]] = {
    # Keep the first-party feature list in the comparison section, but discard
    # competitor scorecards and bought-separately summaries.
    "/academy/mentorship": frozenset({"board", "sum"}),
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _normalise_url(url: str) -> str:
    """Return a fragment-free URL with a normalised scheme and hostname."""

    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if not scheme or not hostname:
        return url.strip()
    port = parsed.port
    if port and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def _path(url: str) -> str:
    return urlparse(url).path.rstrip("/") or "/"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _evidence_hash(page: dict[str, Any]) -> str:
    canonical = json.dumps(
        {key: value for key, value in page.items() if key != "evidence_hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256(canonical)


def _is_suppressed_container(tag: str, attributes: dict[str, str | None]) -> bool:
    class_tokens = {
        token
        for token in re.split(r"[^a-z0-9_-]+", (attributes.get("class") or "").lower())
        if token
    }
    # Offer pages use a semantic <header class="ta-hero"> for product stats,
    # pricing, and eligibility facts. Preserve that content header while still
    # suppressing the site's navigation header.
    content_header = tag == "header" and any(
        token == "hero" or token.endswith("-hero") for token in class_tokens
    )
    if tag in SUPPRESSED_TAGS and not content_header:
        return True
    if (attributes.get("role") or "").lower() in SUPPRESSED_ROLES:
        return True
    tokens = re.split(
        r"[^a-z0-9_-]+",
        " ".join([attributes.get("id") or "", attributes.get("class") or ""]).lower(),
    )
    return any(token in SUPPRESSED_CLASS_TOKENS for token in tokens if token)


def _is_page_specific_suppressed_container(
    base_url: str, tag: str, attributes: dict[str, str | None]
) -> bool:
    page_path = _path(base_url)
    if tag == "section":
        suppressed_ids = PREVIEW_SUPPRESSED_SECTION_IDS.get(page_path, frozenset())
        if (attributes.get("id") or "").casefold() in suppressed_ids:
            return True
    class_tokens = {
        token
        for token in re.split(
            r"[^a-z0-9_-]+", (attributes.get("class") or "").casefold()
        )
        if token
    }
    return bool(
        class_tokens & PAGE_SUPPRESSED_CLASS_TOKENS.get(page_path, frozenset())
    )


def _meta_refresh_target(content: str) -> str:
    for part in content.split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key.strip().lower() == "url":
            return value.strip().strip("\"'")
    return ""


class PageParser(HTMLParser):
    """Extract visible, sectioned page content and canonicalisation hints."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.suppressed_depth = 0
        self.head_depth = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.headings: list[str] = []
        self.links: list[dict[str, str]] = []
        self.sections: list[dict[str, Any]] = []
        self.meta_description = ""
        self.canonical_url = ""
        self.meta_refresh_url = ""
        self._in_title = False
        self._heading_parts: list[str] | None = None
        self._current_heading = ""
        self._section_parts: list[str] = []
        self._section_spans: list[str] = []
        self._block_parts: list[str] = []
        self._table_row_parts: list[str] | None = None
        self._table_head_depth = 0
        self._link_href = ""
        self._link_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {key.lower(): value for key, value in attrs}

        if self.suppressed_depth:
            if tag not in VOID_TAGS:
                self.suppressed_depth += 1
            return
        if _is_suppressed_container(tag, values) or _is_page_specific_suppressed_container(
            self.base_url, tag, values
        ):
            self._flush_block()
            self.suppressed_depth = 1
            return

        if tag == "head":
            self.head_depth += 1
        if tag == "title":
            self._in_title = True
        elif tag == "link":
            rel = {item.lower() for item in (values.get("rel") or "").split()}
            if "canonical" in rel and not self.canonical_url:
                self.canonical_url = (values.get("href") or "").strip()
        elif tag == "meta":
            name = (values.get("name") or "").lower()
            http_equiv = (values.get("http-equiv") or "").lower()
            content = values.get("content") or ""
            if name == "description":
                self.meta_description = _clean(content)
            elif http_equiv == "refresh" and not self.meta_refresh_url:
                self.meta_refresh_url = _meta_refresh_target(content)

        if self.head_depth:
            return
        if tag == "thead":
            self._table_head_depth += 1
        elif tag == "tr":
            self._flush_block()
            self._table_row_parts = []
        elif tag in HEADING_TAGS:
            self._flush_block()
            self._flush_section()
            self._heading_parts = []
        elif tag == "a":
            self._link_href = values.get("href") or ""
            self._link_parts = []
        elif tag == "br":
            self._flush_block()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Avoid changing suppression depth for an explicitly self-closing tag.
        if self.suppressed_depth:
            return
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.suppressed_depth:
            self.suppressed_depth -= 1
            return
        if tag == "head":
            self.head_depth = max(0, self.head_depth - 1)
            return
        if tag == "title":
            self._in_title = False
            return
        if self.head_depth:
            return
        if tag in HEADING_TAGS and self._heading_parts is not None:
            heading = _clean(" ".join(self._heading_parts))
            if heading:
                self.headings.append(heading)
                self._current_heading = heading
            self._heading_parts = None
        elif tag == "a" and self._link_parts is not None:
            href = self._link_href.strip()
            if href and not href.lower().startswith(
                ("#", "mailto:", "tel:", "javascript:")
            ):
                self.links.append(
                    {
                        "text": _clean(" ".join(self._link_parts)),
                        "url": _normalise_url(urljoin(self.base_url, href)),
                    }
                )
            self._link_href = ""
            self._link_parts = None
        if tag in BLOCK_TAGS:
            self._flush_block()
        if tag == "tr" and self._table_row_parts is not None:
            self._flush_block()
            row = _clean(" ".join(self._table_row_parts))
            if row and self._table_head_depth == 0:
                self._section_spans.append(row)
            self._table_row_parts = None
        if tag == "thead":
            self._table_head_depth = max(0, self._table_head_depth - 1)

    def handle_data(self, data: str) -> None:
        value = _clean(data)
        if not value or self.suppressed_depth:
            return
        if self._in_title:
            self.title_parts.append(value)
            return
        if self.head_depth:
            return
        if self._heading_parts is not None:
            self._heading_parts.append(value)
            return
        self.text_parts.append(value)
        self._block_parts.append(value)
        if self._table_row_parts is not None:
            self._table_row_parts.append(value)
        if self._link_parts is not None:
            self._link_parts.append(value)

    def close(self) -> None:
        super().close()
        self._flush_block()
        self._flush_section()

    def _flush_block(self) -> None:
        block = _clean(" ".join(self._block_parts))
        if block:
            self._section_parts.append(block)
            if self._table_row_parts is None:
                self._section_spans.append(block)
        self._block_parts = []

    def _flush_section(self) -> None:
        self._flush_block()
        body = _clean(" ".join(self._section_parts))
        if body or self._current_heading:
            self.sections.append(
                {
                    "heading": self._current_heading,
                    "text": body,
                    "spans": list(dict.fromkeys(self._section_spans)),
                }
            )
        self._section_parts = []
        self._section_spans = []


def _unique_links(links: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for link in links:
        key = (link["text"], link["url"])
        if key not in seen:
            seen.add(key)
            result.append(link)
    return result


def _split_to_limit(text: str, limit: int) -> list[str]:
    """Split text without breaking words, preferring paragraph/sentence edges."""

    text = text.strip()
    pieces: list[str] = []
    while len(text) > limit:
        lower_bound = max(1, int(limit * 0.62))
        candidates = [
            text.rfind("\n\n", lower_bound, limit + 1),
            text.rfind(". ", lower_bound, limit + 1),
            text.rfind("? ", lower_bound, limit + 1),
            text.rfind("! ", lower_bound, limit + 1),
            text.rfind(" ", lower_bound, limit + 1),
        ]
        cut = max(candidates)
        if cut < 1:
            cut = text.rfind(" ", 0, limit + 1)
        if cut < 1:
            cut = limit
        elif text[cut : cut + 2] in {". ", "? ", "! "}:
            cut += 1
        pieces.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        pieces.append(text)
    return pieces


def _atomic_span_texts(raw_spans: Iterable[str]) -> list[str]:
    """Return complete, bounded source spans; never emit arbitrary substrings."""

    result: list[str] = []
    seen: set[str] = set()
    for raw_span in raw_spans:
        block = _clean(str(raw_span))
        if not block:
            continue
        # Accordion rows are flattened by the parser as ``Question? + Answer``.
        # Only the complete answer is evidence: the question may contain a false
        # premise, comparison price, or visitor-style wording that must never be
        # treated as a first-party offer fact.
        faq_parts = re.split(r"(?<=\?)\s*\+\s*", block, maxsplit=1)
        if len(faq_parts) > 1:
            candidates = faq_parts[1:]
        else:
            sentences = SENTENCE_SPLIT_RE.split(block)
            candidates = sentences if len(sentences) > 1 else [block]
        for candidate in candidates:
            span = _clean(candidate)
            key = span.casefold()
            if (
                len(SPAN_TOKEN_RE.findall(span)) < 2
                or len(span) > MAX_EVIDENCE_SPAN_CHARS
                or any(symbol in span for symbol in ("✓", "✗"))
                or key in seen
            ):
                continue
            seen.add(key)
            result.append(span)
    return result


def _span_records(
    canonical_url: str, chunk_id: str, raw_spans: Iterable[str]
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for text in _atomic_span_texts(raw_spans):
        identity = f"{canonical_url}\n{chunk_id}\n{text}"
        records.append(
            {
                "span_id": f"span-{_sha256(identity)[:24]}",
                "text": text,
            }
        )
    return records


def build_chunks(
    sections: Iterable[dict[str, Any]],
    canonical_url: str,
    *,
    min_chars: int = MIN_CHUNK_CHARS,
    target_chars: int = TARGET_CHUNK_CHARS,
    max_chars: int = MAX_CHUNK_CHARS,
) -> list[dict[str, Any]]:
    """Build bounded deterministic chunks while retaining section headings."""

    if not 0 < min_chars <= target_chars <= max_chars:
        raise ValueError("chunk sizes must satisfy 0 < min <= target <= max")

    pieces: list[dict[str, Any]] = []
    for section_index, section in enumerate(sections):
        heading = _clean(str(section.get("heading", "")))
        body = _clean(str(section.get("text", "")))
        raw_section_spans = [str(item) for item in section.get("spans", [])]
        section_spans = _atomic_span_texts(raw_section_spans)
        heading_spans = _atomic_span_texts([heading]) if heading else []
        if not heading and not body:
            continue
        prefix = f"{heading}\n" if heading else ""
        body_limit = max(1, max_chars - len(prefix))
        body_pieces = _split_to_limit(body, body_limit) if body else [""]
        for part_index, body_piece in enumerate(body_pieces):
            text = f"{prefix}{body_piece}".strip()
            normalized_piece = _clean(body_piece)
            piece_spans = [span for span in section_spans if span in normalized_piece]
            if part_index == 0:
                piece_spans = [
                    *[span for span in heading_spans if re.search(r"\d|[$€£¥%]", span)],
                    *piece_spans,
                ]
            if not piece_spans:
                piece_spans.extend(heading_spans)
            pieces.append(
                {
                    "text": text,
                    "heading": heading or "Overview",
                    "key": f"section-{section_index}-part-{part_index}",
                    "spans": piece_spans,
                }
            )

    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_length = 0
    for piece in pieces:
        separator_length = 2 if current else 0
        candidate_length = current_length + separator_length + len(piece["text"])
        if current and candidate_length > max_chars:
            groups.append(current)
            current = []
            current_length = 0
            separator_length = 0
        current.append(piece)
        current_length += separator_length + len(piece["text"])
        if current_length >= target_chars:
            groups.append(current)
            current = []
            current_length = 0
    if current:
        groups.append(current)

    # Fold a small final group into its predecessor when the hard maximum allows.
    if len(groups) >= 2:
        tail_length = sum(len(item["text"]) for item in groups[-1])
        tail_length += 2 * (len(groups[-1]) - 1)
        previous_length = sum(len(item["text"]) for item in groups[-2])
        previous_length += 2 * (len(groups[-2]) - 1)
        if tail_length < min_chars and previous_length + 2 + tail_length <= max_chars:
            groups[-2].extend(groups.pop())

    result: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        # The most substantial section is the best label when a chunk spans a run
        # of short sections. Every original heading remains embedded in the text.
        anchor = max(group, key=lambda item: len(item["text"]))
        identity = f"{canonical_url}\n{anchor['key']}"
        chunk_id = f"tai-{_sha256(identity)[:24]}"
        result.append(
            {
                "chunk_id": chunk_id,
                "text": "\n\n".join(item["text"] for item in group),
                "heading": anchor["heading"],
                "index": index,
                "evidence_spans": _span_records(
                    canonical_url,
                    chunk_id,
                    (span for item in group for span in item.get("spans", [])),
                ),
            }
        )
    return result


def _document_text(sections: Iterable[dict[str, str]]) -> str:
    blocks: list[str] = []
    for section in sections:
        heading = _clean(str(section.get("heading", "")))
        body = _clean(str(section.get("text", "")))
        block = f"{heading}\n{body}".strip()
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


def _parse_sitemap(response_text: str) -> tuple[str, list[dict[str, str]]]:
    root = ElementTree.fromstring(response_text)
    root_type = _local_name(root.tag)
    entries: list[dict[str, str]] = []
    for child in root:
        if _local_name(child.tag) not in {"url", "sitemap"}:
            continue
        values = {_local_name(item.tag): _clean(item.text or "") for item in child}
        if values.get("loc"):
            entries.append(values)
    return root_type, entries


def discover_sitemap_entries(
    session: requests.Session,
    sitemap_url: str,
    *,
    allowed_hosts: frozenset[str] | None = None,
    _visited: set[str] | None = None,
) -> list[dict[str, str]]:
    """Read a urlset or sitemap index and return de-duplicated page entries."""

    visited = _visited if _visited is not None else set()
    normalised_sitemap = _normalise_url(sitemap_url)
    if normalised_sitemap in visited:
        return []
    visited.add(normalised_sitemap)

    response = session.get(sitemap_url, timeout=30)
    response.raise_for_status()
    root_type, raw_entries = _parse_sitemap(response.text)
    if root_type == "sitemapindex":
        nested: list[dict[str, str]] = []
        for item in raw_entries:
            nested.extend(
                discover_sitemap_entries(
                    session,
                    item["loc"],
                    allowed_hosts=allowed_hosts,
                    _visited=visited,
                )
            )
        return nested
    if root_type != "urlset":
        raise ValueError(f"unsupported sitemap root: {root_type}")

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_entries:
        url = _normalise_url(item["loc"])
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        if allowed_hosts and parsed.hostname.lower() not in allowed_hosts:
            continue
        if url in seen:
            continue
        seen.add(url)
        result.append(
            {
                "url": url,
                "lastmod": item.get("lastmod", ""),
                "sitemap_url": normalised_sitemap,
            }
        )
    return result


def discover_sitemap_urls(
    session: requests.Session,
    sitemap_url: str,
    *,
    allowed_hosts: frozenset[str] | None = None,
) -> list[str]:
    return [
        item["url"]
        for item in discover_sitemap_entries(
            session, sitemap_url, allowed_hosts=allowed_hosts
        )
    ]


def merge_curated_com_metadata(
    entries: Iterable[dict[str, str]],
    curated_pages: Iterable[dict[str, str]] = CURATED_COM_METADATA,
) -> list[dict[str, str]]:
    """Attach non-factual labels only to URLs discovered in the live sitemap."""

    curated_by_url = {_normalise_url(spec["url"]): dict(spec) for spec in curated_pages}
    result: list[dict[str, str]] = []
    for raw_entry in entries:
        entry = dict(raw_entry)
        url = _normalise_url(entry["url"])
        entry["url"] = url
        metadata = curated_by_url.get(url)
        if metadata:
            entry.update(
                {key: value for key, value in metadata.items() if key != "url"}
            )
        result.append(entry)
    return result


def _fetch_and_resolve(
    session: requests.Session, url: str, *, max_meta_refreshes: int = 3
) -> tuple[Any, PageParser, str, list[str]]:
    """Follow HTTP redirects, HTML meta refreshes, then honour rel=canonical."""

    current_url = url
    visited: list[str] = []
    for _hop in range(max_meta_refreshes + 1):
        response = session.get(current_url, timeout=30)
        response.raise_for_status()
        response_url = _normalise_url(response.url)
        visited.append(response_url)
        parser = PageParser(response_url)
        parser.feed(response.text)
        parser.close()

        refresh = parser.meta_refresh_url
        if refresh:
            refresh_url = _normalise_url(urljoin(response_url, refresh))
            if refresh_url not in visited:
                current_url = refresh_url
                continue

        canonical_url = response_url
        if parser.canonical_url:
            candidate = _normalise_url(urljoin(response_url, parser.canonical_url))
            if urlparse(candidate).scheme in {"http", "https"}:
                canonical_url = candidate
        return response, parser, canonical_url, visited
    raise ValueError(f"too many meta refreshes while fetching {url}")


def classify_kind(url: str) -> str:
    path = _path(url).lower()
    if path in {"/academy", "/academy/bundles"} or path.startswith("/collections"):
        return "collection"
    if "/enterprise/" in path or path in {
        "/enterpriseenablement",
        "/valuecreation",
    }:
        return "b2b"
    if path.startswith("/valuecreation/"):
        return "career"
    if "/mentorship" in path or path.endswith("/tai-mentorship"):
        return "mentorship"
    if "free" in path or "/webinars/" in path:
        return "free_resource"
    if "/bundles/" in path:
        return "bundle"
    if "/courses/" in path or (
        path.startswith("/academy/")
        and any(
            term in path
            for term in (
                "full-stack",
                "agent-engineering",
                "llm-primer",
                "python-for-ai",
                "ai-for-work",
                "building-llms",
            )
        )
    ):
        return "course"
    if "/digital_downloads/" in path:
        return "digital_download"
    if path.endswith("/book"):
        return "book"
    if path == "/contribute":
        return "community"
    return "page"


def offer_id_for_url(url: str) -> str | None:
    return OFFER_PATHS.get(_path(url).lower())


def entity_id_for_url(url: str) -> str:
    offer_id = offer_id_for_url(url)
    if offer_id:
        return f"offer:{offer_id}"
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return f"page:{host}{_path(url).lower()}"


def fetch_page(
    session: requests.Session,
    spec: dict[str, Any],
    *,
    authority: str | None = None,
    fetched_at: str | None = None,
    allowed_hosts: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Fetch one sitemap entry without adding any non-page summary to its text."""

    discovered_url = _normalise_url(str(spec["url"]))
    fetched_at = fetched_at or _utc_now()
    authority = authority or (
        "official_academy"
        if urlparse(discovered_url).hostname == "academy.towardsai.net"
        else "official_site"
    )
    response, parser, canonical_url, redirect_chain = _fetch_and_resolve(
        session, discovered_url
    )
    parsed = urlparse(canonical_url)
    text = _document_text(parser.sections)
    content_sha256 = _sha256(text)
    status = "included"
    excluded_reason = ""
    if allowed_hosts and (parsed.hostname or "").lower() not in allowed_hosts:
        status = "excluded"
        excluded_reason = "canonical URL is outside the sitemap authority"

    discovered_path = _path(discovered_url)
    if authority == "official_site" and discovered_path in COM_EXCLUSIONS:
        status = "excluded"
        excluded_reason = COM_EXCLUSIONS[discovered_path]
    if authority == "official_academy" and discovered_path in ACADEMY_EXCLUSIONS:
        status = "excluded"
        excluded_reason = ACADEMY_EXCLUSIONS[discovered_path]
    if not text:
        status = "excluded"
        excluded_reason = "no usable visible page content"

    title = _clean(" ".join(parser.title_parts))
    if not title:
        title = _clean(str(spec.get("review_title", ""))) or canonical_url
    offer_id = offer_id_for_url(canonical_url) or offer_id_for_url(discovered_url)
    chunks = build_chunks(parser.sections, canonical_url)
    page = {
        "discovered_url": discovered_url,
        "url": canonical_url,
        "canonical_url": canonical_url,
        "host": (parsed.hostname or "").lower(),
        "path": parsed.path.rstrip("/") or "/",
        "kind": str(spec.get("kind") or classify_kind(canonical_url)),
        "offer_id": offer_id,
        "entity_id": (
            f"offer:{offer_id}" if offer_id else entity_id_for_url(canonical_url)
        ),
        "title": title,
        "review_title": str(spec.get("review_title", "")),
        "reviewed_summary": str(spec.get("reviewed_summary", "")),
        "meta_description": parser.meta_description,
        "headings": list(dict.fromkeys(parser.headings))[:100],
        "text": text,
        "links": _unique_links(parser.links)[:300],
        "chunks": chunks,
        "fetched_at": fetched_at,
        "content_sha256": content_sha256,
        # content_hash is the generic name consumed by the retrieval layer.
        "content_hash": content_sha256,
        "authority": authority,
        "status": status,
        "retrieval_eligible": status == "included",
        "http_status": int(getattr(response, "status_code", 200)),
        "lastmod": str(spec.get("lastmod", "")),
        "sitemap_url": str(spec.get("sitemap_url", "")),
        "redirect_chain": redirect_chain,
    }
    if excluded_reason:
        page["excluded_reason"] = excluded_reason
    page["evidence_hash"] = _evidence_hash(page)
    return page


def _failed_page(
    spec: dict[str, Any], authority: str, fetched_at: str, error: Exception
) -> dict[str, Any]:
    url = _normalise_url(str(spec["url"]))
    parsed = urlparse(url)
    content_sha256 = _sha256("")
    chunks: list[dict[str, Any]] = []
    page = {
        "discovered_url": url,
        "url": url,
        "canonical_url": url,
        "host": (parsed.hostname or "").lower(),
        "path": parsed.path.rstrip("/") or "/",
        "kind": classify_kind(url),
        "offer_id": offer_id_for_url(url),
        "entity_id": entity_id_for_url(url),
        "title": url,
        "review_title": str(spec.get("review_title", "")),
        "reviewed_summary": str(spec.get("reviewed_summary", "")),
        "meta_description": "",
        "headings": [],
        "text": "",
        "links": [],
        "chunks": chunks,
        "fetched_at": fetched_at,
        "content_sha256": content_sha256,
        "content_hash": content_sha256,
        "authority": authority,
        "status": "fetch_error",
        "retrieval_eligible": False,
        "http_status": None,
        "lastmod": str(spec.get("lastmod", "")),
        "sitemap_url": str(spec.get("sitemap_url", "")),
        "redirect_chain": [],
        "error": f"{type(error).__name__}: {error}",
    }
    page["evidence_hash"] = _evidence_hash(page)
    return page


def _exclude_canonical_duplicates(pages: list[dict[str, Any]]) -> None:
    seen: dict[str, str] = {}
    for page in pages:
        if page["status"] != "included":
            continue
        canonical_url = str(page["canonical_url"])
        if canonical_url in seen:
            page["status"] = "excluded"
            page["retrieval_eligible"] = False
            page["excluded_reason"] = (
                f"duplicate canonical URL; authoritative scan is {seen[canonical_url]}"
            )
        else:
            seen[canonical_url] = str(page["discovered_url"])


def _manual_resource_page(spec: dict[str, Any], fetched_at: str) -> dict[str, Any]:
    url = _normalise_url(str(spec["url"]))
    parsed = urlparse(url)
    text = _clean(str(spec["text"]))
    content_sha256 = _sha256(text)
    chunks: list[dict[str, Any]] = []
    page = {
        "discovered_url": url,
        "url": url,
        "canonical_url": url,
        "host": (parsed.hostname or "").lower(),
        "path": parsed.path.rstrip("/") or "/",
        "kind": str(spec["kind"]),
        "offer_id": None,
        "entity_id": entity_id_for_url(url),
        "title": str(spec["title"]),
        "meta_description": "",
        "headings": [str(spec["title"])],
        "text": text,
        "links": list(spec.get("links", [])),
        "chunks": chunks,
        "fetched_at": fetched_at,
        "content_sha256": content_sha256,
        "content_hash": content_sha256,
        "authority": "curated_external",
        "status": "excluded",
        "retrieval_eligible": False,
        "excluded_reason": (
            "manual routing-only resource; descriptive text was not fetched"
        ),
        "http_status": None,
        "lastmod": "",
        "sitemap_url": "manual_allowlist",
        "redirect_chain": [],
    }
    page["evidence_hash"] = _evidence_hash(page)
    return page


def build_catalog(
    *,
    session: requests.Session | None = None,
    sitemap_url: str = COM_SITEMAP_URL,
    authority: str = "official_site",
    allowed_hosts: frozenset[str] = COM_HOSTS,
    fetched_at: str | None = None,
    include_manual_resources: bool = False,
) -> dict[str, Any]:
    """Build one catalog from its sitemap while retaining failed scan records."""

    fetched_at = fetched_at or _utc_now()
    own_session = session or requests.Session()
    own_session.headers.setdefault("User-Agent", "TowardsAIHelperCatalog/2.0")
    entries = discover_sitemap_entries(
        own_session, sitemap_url, allowed_hosts=allowed_hosts
    )
    if authority == "official_site":
        entries = merge_curated_com_metadata(entries)
    pages: list[dict[str, Any]] = []
    for spec in entries:
        try:
            pages.append(
                fetch_page(
                    own_session,
                    spec,
                    authority=authority,
                    fetched_at=fetched_at,
                    allowed_hosts=allowed_hosts,
                )
            )
        except (requests.RequestException, ValueError) as error:
            pages.append(_failed_page(spec, authority, fetched_at, error))
    _exclude_canonical_duplicates(pages)
    if include_manual_resources:
        pages.extend(
            _manual_resource_page(spec, fetched_at) for spec in MANUAL_SAFE_RESOURCES
        )
    for page in pages:
        page["evidence_hash"] = _evidence_hash(page)

    statuses: dict[str, int] = {}
    for page in pages:
        status = str(page["status"])
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "schema_version": 2,
        "source": _normalise_url(sitemap_url),
        "generated_at": fetched_at,
        "authority": authority,
        "status_counts": statuses,
        "pages": pages,
    }


def build_catalogs(
    *,
    session: requests.Session | None = None,
    com_sitemap_url: str = COM_SITEMAP_URL,
    academy_sitemap_url: str = ACADEMY_SITEMAP_URL,
    fetched_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the public-site and Academy catalogs in one reproducible scan."""

    fetched_at = fetched_at or _utc_now()
    own_session = session or requests.Session()
    own_session.headers.setdefault("User-Agent", "TowardsAIHelperCatalog/2.0")
    com_catalog = build_catalog(
        session=own_session,
        sitemap_url=com_sitemap_url,
        authority="official_site",
        allowed_hosts=COM_HOSTS,
        fetched_at=fetched_at,
    )
    academy_catalog = build_catalog(
        session=own_session,
        sitemap_url=academy_sitemap_url,
        authority="official_academy",
        allowed_hosts=ACADEMY_HOSTS,
        fetched_at=fetched_at,
        include_manual_resources=True,
    )
    return com_catalog, academy_catalog


def _write_catalog(output: Path, payload: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh the towardsai.com and Academy helper catalogs"
    )
    parser.add_argument(
        "--com-output",
        "--output",
        dest="com_output",
        type=Path,
        default=DEFAULT_COM_OUTPUT,
        help="output for towardsai.com pages (legacy alias: --output)",
    )
    parser.add_argument("--academy-output", type=Path, default=DEFAULT_ACADEMY_OUTPUT)
    parser.add_argument("--com-sitemap", default=COM_SITEMAP_URL)
    parser.add_argument("--academy-sitemap", default=ACADEMY_SITEMAP_URL)
    args = parser.parse_args()

    com_catalog, academy_catalog = build_catalogs(
        com_sitemap_url=args.com_sitemap,
        academy_sitemap_url=args.academy_sitemap,
    )
    _write_catalog(args.com_output, com_catalog)
    _write_catalog(args.academy_output, academy_catalog)
    print(f"Wrote {len(com_catalog['pages'])} .com pages to {args.com_output}")
    print(
        f"Wrote {len(academy_catalog['pages'])} Academy/manual pages "
        f"to {args.academy_output}"
    )


if __name__ == "__main__":
    main()
