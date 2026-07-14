from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "towardsai_com_pages.json"

REVIEWED_PAGES = [
    {
        "review_title": "Homepage",
        "url": "https://towardsai.com/",
        "kind": "page",
        "summary": (
            "Towards AI is an AI deployment and education firm offering individual "
            "learning, enterprise enablement, and custom AI development."
        ),
    },
    {
        "review_title": "Enterprise Enablement",
        "url": "https://towardsai.com/enterpriseenablement/",
        "kind": "b2b",
        "summary": (
            "Enterprise AI enablement covers team training, an enterprise academy, "
            "developer conversion programs, and support for deploying AI capability."
        ),
    },
    {
        "review_title": "Value Creation",
        "url": "https://towardsai.com/valuecreation/",
        "kind": "b2b",
        "summary": (
            "Towards AI provides custom AI development and value-creation consulting "
            "for companies and private-equity portfolios."
        ),
    },
    {
        "review_title": "Agent Engineering webinar",
        "url": "https://towardsai.com/webinars/agentengineering/",
        "kind": "free_resource",
        "summary": (
            "Free agent engineering webinar for people exploring how to become an AI "
            "engineer and build production agent systems."
        ),
    },
    {
        "review_title": "Academy hub",
        "url": "https://towardsai.com/academy/",
        "kind": "collection",
        "summary": (
            "The Academy hub compares the five main learning paths: Full Stack AI "
            "Engineering, Agent Engineering, LLM Primer, Python, and AI for Work."
        ),
    },
    {
        "review_title": "Full Stack AI Engineering",
        "url": "https://towardsai.com/academy/full-stack-ai-engineering/",
        "kind": "course",
        "summary": (
            "Flagship program for Python developers building production LLM products "
            "with prompting, RAG, fine-tuning, agents, evaluation, and deployment."
        ),
    },
    {
        "review_title": "Agent Engineering",
        "url": "https://towardsai.com/academy/agentic-ai-engineering/",
        "kind": "course",
        "summary": (
            "Production-focused agent engineering program covering agent design, tool "
            "orchestration, evaluation, monitoring, and deployment."
        ),
    },
    {
        "review_title": "LLM Primer",
        "url": "https://towardsai.com/academy/llm-primer/",
        "kind": "course",
        "summary": (
            "A focused video crash course on LLM fundamentals and choosing between "
            "prompting, RAG, fine-tuning, and agents."
        ),
    },
    {
        "review_title": "Python for AI Engineering",
        "url": "https://towardsai.com/academy/python-for-ai-engineering/",
        "kind": "course",
        "summary": (
            "Beginner Python foundations for non-coders who want to build and integrate "
            "AI applications before taking advanced engineering courses."
        ),
    },
    {
        "review_title": "AI for Work",
        "url": "https://towardsai.com/academy/ai-for-work/",
        "kind": "course",
        "summary": (
            "No-code AI training for professionals who want practical, safe workflows "
            "for research, communication, analysis, and automation."
        ),
    },
    {
        "review_title": "Membership",
        "url": "https://towardsai.com/academy/membership/",
        "kind": "mentorship",
        "summary": (
            "Towards AI membership provides mentorship, project feedback, career "
            "guidance, accountability, and access to the AI engineering team."
        ),
    },
    {
        "review_title": "About",
        "url": "https://towardsai.com/academy/about/",
        "kind": "page",
        "summary": "Background on the Towards AI Academy and the team behind it.",
    },
    {
        "review_title": "Contact",
        "url": "https://towardsai.com/academy/contact/",
        "kind": "page",
        "summary": "Contact options for Towards AI Academy questions and support.",
    },
    {
        "review_title": "Affiliate",
        "url": "https://towardsai.com/academy/affiliate/",
        "kind": "page",
        "summary": "Towards AI referral and affiliate program details.",
    },
    {
        "review_title": "Software Developer to AI Engineer",
        "url": "https://towardsai.com/enterprise/software-developer-to-ai-engineer/",
        "kind": "b2b",
        "summary": (
            "Enterprise conversion program for teams that want to turn existing "
            "software developers into AI engineers through courses, bootcamps, or coaching."
        ),
    },
    {
        "review_title": "Agentic Developer Conversion",
        "url": "https://towardsai.com/enterprise/agentic-developer-conversion/",
        "kind": "b2b",
        "summary": (
            "Live Claude Code and Codex training that helps engineering teams adopt "
            "shared, safe, and effective coding-agent practices."
        ),
    },
    {
        "review_title": "Free lessons: Full Stack",
        "url": "https://towardsai.com/academy/free-lesson-offer/",
        "kind": "free_resource",
        "summary": (
            "Free Full Stack AI Engineering lessons with signup leading to the "
            "Thinkific enrollment flow."
        ),
    },
    {
        "review_title": "Free lessons: Agent Engineering",
        "url": "https://towardsai.com/academy/free-lesson-offer-2/",
        "kind": "free_resource",
        "summary": (
            "Seven free Agent Engineering lessons with signup leading to the Thinkific "
            "enrollment flow."
        ),
    },
    {
        "review_title": "From Developer to Advanced AI Engineer",
        "url": (
            "https://towardsai.com/academy/bundles/"
            "10-hour-crash-course-into-llm-developer-expert/"
        ),
        "kind": "bundle",
        "summary": (
            "Course bundle for developers progressing from LLM fundamentals to "
            "advanced AI engineering."
        ),
    },
    {
        "review_title": "From Non-Coder to AI Engineer",
        "url": (
            "https://towardsai.com/academy/bundles/"
            "from-coding-novice-to-advanced-llm-developer/"
        ),
        "kind": "bundle",
        "summary": (
            "Course bundle that starts with Python foundations and progresses from "
            "non-coder to advanced AI engineering."
        ),
    },
    {
        "review_title": "Get It All",
        "url": "https://towardsai.com/academy/bundles/get-it-all/",
        "kind": "bundle",
        "summary": (
            "Best-value bundle for broad access to every Towards AI Academy course, "
            "from foundations through advanced AI engineering."
        ),
    },
]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class PageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.suppressed_depth = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.headings: list[str] = []
        self.links: list[dict[str, str]] = []
        self.meta_description = ""
        self._in_title = False
        self._heading_parts: list[str] | None = None
        self._link_href = ""
        self._link_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self.suppressed_depth += 1
            return
        if self.suppressed_depth:
            return
        if tag == "title":
            self._in_title = True
        elif tag in {"h1", "h2", "h3"}:
            self._heading_parts = []
        elif tag == "a":
            self._link_href = values.get("href") or ""
            self._link_parts = []
        elif tag == "meta" and (values.get("name") or "").lower() == "description":
            self.meta_description = _clean(values.get("content") or "")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"}:
            if self.suppressed_depth:
                self.suppressed_depth -= 1
            return
        if self.suppressed_depth:
            return
        if tag == "title":
            self._in_title = False
        elif tag in {"h1", "h2", "h3"} and self._heading_parts is not None:
            heading = _clean(" ".join(self._heading_parts))
            if heading and heading not in self.headings:
                self.headings.append(heading)
            self._heading_parts = None
        elif tag == "a" and self._link_parts is not None:
            href = self._link_href.strip()
            if href and not href.startswith(("#", "mailto:", "tel:", "javascript:")):
                self.links.append(
                    {
                        "text": _clean(" ".join(self._link_parts)),
                        "url": urljoin(self.base_url, href),
                    }
                )
            self._link_href = ""
            self._link_parts = None

    def handle_data(self, data: str) -> None:
        if self.suppressed_depth:
            return
        value = _clean(data)
        if not value:
            return
        self.text_parts.append(value)
        if self._in_title:
            self.title_parts.append(value)
        if self._heading_parts is not None:
            self._heading_parts.append(value)
        if self._link_parts is not None:
            self._link_parts.append(value)


def _unique_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    result = []
    seen = set()
    for link in links:
        key = (link["text"], link["url"])
        if key not in seen:
            seen.add(key)
            result.append(link)
    return result


def fetch_page(session: requests.Session, spec: dict[str, str]) -> dict[str, Any]:
    response = session.get(spec["url"], timeout=30)
    response.raise_for_status()
    parser = PageParser(response.url)
    parser.feed(response.text)

    parsed = urlparse(spec["url"])
    summary = spec["summary"]
    visible_text = _clean(" ".join(parser.text_parts))
    text = f"{summary} {visible_text}"[:30_000]
    title = _clean(" ".join(parser.title_parts)) or spec["review_title"]
    return {
        "title": title,
        "review_title": spec["review_title"],
        "url": spec["url"],
        "host": parsed.hostname,
        "path": parsed.path.rstrip("/") or "/",
        "kind": spec["kind"],
        "meta_description": parser.meta_description,
        "headings": parser.headings[:60],
        "text": text,
        "links": _unique_links(parser.links)[:250],
    }


def build_catalog() -> dict[str, Any]:
    session = requests.Session()
    session.headers["User-Agent"] = "TowardsAIHelperCatalog/1.0"
    pages = [fetch_page(session, spec) for spec in REVIEWED_PAGES]
    return {
        "source": "Website review.md supplied 2026-07-13",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages": pages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh the towardsai.com helper catalog"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    payload = build_catalog()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {len(payload['pages'])} pages to {args.output}")


if __name__ == "__main__":
    main()
