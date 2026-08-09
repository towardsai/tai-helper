from __future__ import annotations

import requests

from scripts.build_towardsai_com_catalog import (
    ACADEMY_EXCLUSIONS,
    ACADEMY_HOSTS,
    ACADEMY_SITEMAP_URL,
    COM_HOSTS,
    PageParser,
    build_catalog,
    build_catalogs,
    build_chunks,
    discover_sitemap_entries,
    fetch_page,
)


class FakeResponse:
    def __init__(
        self,
        url: str,
        text: str,
        *,
        status_code: int = 200,
    ) -> None:
        self.url = url
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code} for {self.url}")


class FakeSession:
    def __init__(self, routes: dict[str, FakeResponse]) -> None:
        self.routes = routes
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: int) -> FakeResponse:
        assert timeout == 30
        self.calls.append(url)
        if url not in self.routes:
            raise AssertionError(f"unexpected network request: {url}")
        return self.routes[url]


def sitemap(*urls: str) -> str:
    rows = "".join(f"<url><loc>{url}</loc></url>" for url in urls)
    return (
        '<?xml version="1.0"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{rows}</urlset>"
    )


def page_html(title: str, body: str, *, canonical: str = "") -> str:
    canonical_tag = (
        f'<link href="{canonical}" rel="alternate canonical">' if canonical else ""
    )
    return f"""
        <html>
          <head>
            <title>{title}</title>
            <meta name="description" content="A fetched description">
            {canonical_tag}
          </head>
          <body>
            <nav>Navigation misinformation</nav>
            <main><h1>{title}</h1><p>{body}</p></main>
            <footer>Footer misinformation</footer>
            <script>Script misinformation</script>
            <style>.misinformation {{ display: block }}</style>
          </body>
        </html>
    """


def test_parser_suppresses_chrome_and_extracts_canonical_hints() -> None:
    parser = PageParser("https://towardsai.com/original/")
    parser.feed(
        """
        <html><head>
          <title>Course title</title>
          <link rel="canonical" href="/academy/course/">
          <meta http-equiv="Refresh" content="0; URL='/moved/'">
        </head><body>
          <header class="header"><a>Skip to main content</a><button>Toggle menu</button></header>
          <header class="ta-hero"><h1>Current offer</h1><p>60+ Hrs</p></header>
          <div class="ta-announce">New: Towards AI Mentorship</div>
          <div class="navbar"><p>Bad navigation claim</p></div>
          <div class="ta-mobile-menu">Duplicated mobile course links</div>
          <h1>Course facts</h1><p>Only retrieved facts survive.</p>
          <div role="contentinfo">Bad footer claim</div>
          <script>Bad script claim</script><style>Bad style claim</style>
        </body></html>
        """
    )
    parser.close()

    extracted = " ".join(section["text"] for section in parser.sections)
    assert parser.canonical_url == "/academy/course/"
    assert parser.meta_refresh_url == "/moved/"
    assert parser.headings == ["Current offer", "Course facts"]
    assert extracted == "60+ Hrs Only retrieved facts survive."
    assert "Bad" not in extracted
    assert "Mentorship" not in extracted
    assert "Toggle menu" not in extracted


def test_sitemap_discovery_uses_fake_http_and_filters_foreign_hosts() -> None:
    sitemap_url = "https://towardsai.com/pages-sitemap.xml"
    session = FakeSession(
        {
            sitemap_url: FakeResponse(
                sitemap_url,
                sitemap(
                    "https://towardsai.com/new-page/",
                    "https://towardsai.com/new-page/",
                    "https://untrusted.example/poison",
                ),
            )
        }
    )

    entries = discover_sitemap_entries(session, sitemap_url, allowed_hosts=COM_HOSTS)

    assert [entry["url"] for entry in entries] == ["https://towardsai.com/new-page/"]
    assert session.calls == [sitemap_url]


def test_fetch_resolves_http_canonical_and_meta_refresh_without_summary() -> None:
    old_url = "https://towardsai.com/old/"
    http_final = "https://towardsai.com/http-final/"
    canonical = "https://towardsai.com/canonical/"
    refresh_start = "https://academy.towardsai.net/refresh"
    refresh_target = "https://academy.towardsai.net/final"
    session = FakeSession(
        {
            old_url: FakeResponse(
                http_final,
                page_html(
                    "Canonical offer", "Retrieved offer facts.", canonical=canonical
                ),
            ),
            refresh_start: FakeResponse(
                refresh_start,
                '<meta http-equiv="refresh" content="0; url=/final">',
            ),
            refresh_target: FakeResponse(
                refresh_target,
                page_html("Final Academy page", "Academy evidence."),
            ),
        }
    )

    page = fetch_page(
        session,
        {
            "url": old_url,
            "summary": "HANDWRITTEN FALSE CLAIM",
            "kind": "course",
        },
        allowed_hosts=COM_HOSTS,
        fetched_at="2026-08-08T00:00:00+00:00",
    )
    refreshed = fetch_page(
        session,
        {"url": refresh_start},
        authority="official_academy",
        allowed_hosts=ACADEMY_HOSTS,
        fetched_at="2026-08-08T00:00:00+00:00",
    )

    assert page["discovered_url"] == old_url
    assert page["url"] == canonical
    assert page["canonical_url"] == canonical
    assert page["redirect_chain"] == [http_final]
    assert "Retrieved offer facts." in page["text"]
    assert "HANDWRITTEN FALSE CLAIM" not in page["text"]
    assert "Navigation misinformation" not in page["text"]
    assert refreshed["canonical_url"] == refresh_target
    assert refreshed["redirect_chain"] == [refresh_start, refresh_target]


def test_chunks_are_heading_aware_bounded_and_stable() -> None:
    sections = [
        {
            "heading": "Mentorship access",
            "text": "evidence " * 350,
        }
    ]
    changed_sections = [
        {
            "heading": "Mentorship access",
            "text": ("evidence " * 349) + "updated",
        }
    ]

    first = build_chunks(sections, "https://towardsai.com/academy/mentorship/")
    second = build_chunks(sections, "https://towardsai.com/academy/mentorship/")
    changed = build_chunks(
        changed_sections, "https://towardsai.com/academy/mentorship/"
    )

    assert len(first) == 2
    assert [chunk["chunk_id"] for chunk in first] == [
        chunk["chunk_id"] for chunk in second
    ]
    assert [chunk["chunk_id"] for chunk in first] == [
        chunk["chunk_id"] for chunk in changed
    ]
    assert all(chunk["heading"] == "Mentorship access" for chunk in first)
    assert all(1_200 <= len(chunk["text"]) <= 1_800 for chunk in first)


def test_table_rows_become_atomic_evidence_spans() -> None:
    parser = PageParser("https://towardsai.com/academy/mentorship/")
    parser.feed(
        """
        <main>
          <h2>The curriculum comes with the team</h2>
          <table><tbody>
            <tr><th>10-Hour LLM Fundamentals course</th><td>$199</td>
                <td>Included from day one</td></tr>
            <tr><th>Full Stack AI Engineering</th><td>$349</td>
                <td>25% off, always</td></tr>
          </tbody></table>
        </main>
        """
    )
    parser.close()

    built = build_chunks(parser.sections, parser.base_url)
    spans = {span["text"] for chunk in built for span in chunk["evidence_spans"]}

    assert "10-Hour LLM Fundamentals course $199 Included from day one" in spans
    assert "Full Stack AI Engineering $349 25% off, always" in spans
    assert "Included from day one" not in spans
    assert "25% off, always" not in spans


def test_accordion_uses_only_the_answer_as_an_atomic_evidence_span() -> None:
    built = build_chunks(
        [
            {
                "heading": "Frequently asked questions",
                "text": (
                    "How long does this course take to complete? + "
                    "It is self-paced; the average completion time is 10 hours "
                    "across five 2-hour sessions."
                ),
                "spans": [
                    (
                        "How long does this course take to complete? + "
                        "It is self-paced; the average completion time is 10 hours "
                        "across five 2-hour sessions."
                    )
                ],
            }
        ],
        "https://towardsai.com/academy/llm-primer/",
    )
    spans = {span["text"] for chunk in built for span in chunk["evidence_spans"]}

    assert "How long does this course take to complete?" not in spans
    assert (
        "It is self-paced; the average completion time is 10 hours across five "
        "2-hour sessions."
    ) in spans
    assert not any("? +" in span for span in spans)


def test_build_both_catalogs_records_exclusions_manual_entries_and_identity() -> None:
    fetched_at = "2026-08-08T12:00:00+00:00"
    com_sitemap = "https://towardsai.com/pages-sitemap.xml"
    academy_sitemap = "https://academy.towardsai.net/sitemap.xml"
    mentorship = "https://towardsai.com/academy/mentorship/"
    academy_mentorship = "https://academy.towardsai.net/bundles/tai-mentorship"
    placeholder = "https://academy.towardsai.net/pages/webinar"
    session = FakeSession(
        {
            com_sitemap: FakeResponse(com_sitemap, sitemap(mentorship)),
            academy_sitemap: FakeResponse(
                academy_sitemap, sitemap(academy_mentorship, placeholder)
            ),
            mentorship: FakeResponse(
                mentorship,
                page_html(
                    "Mentorship",
                    "The retrieved page defines the included course access.",
                ),
            ),
            academy_mentorship: FakeResponse(
                academy_mentorship,
                page_html("Mentorship checkout", "Thinkific purchase facts."),
            ),
            placeholder: FakeResponse(
                placeholder,
                page_html("Webinar", "Add a concise subheading about your product."),
            ),
        }
    )

    com, academy = build_catalogs(session=session, fetched_at=fetched_at)

    assert [page["discovered_url"] for page in com["pages"]] == [mentorship]
    assert len(academy["pages"]) == 4
    com_offer = com["pages"][0]
    academy_offer = next(
        page
        for page in academy["pages"]
        if page["discovered_url"] == academy_mentorship
    )
    excluded = next(
        page for page in academy["pages"] if page["discovered_url"] == placeholder
    )
    manual = [
        page for page in academy["pages"] if page["authority"] == "curated_external"
    ]

    assert com_offer["offer_id"] == academy_offer["offer_id"] == "mentorship"
    assert com_offer["entity_id"] == academy_offer["entity_id"]
    assert excluded["status"] == "excluded"
    assert excluded["retrieval_eligible"] is False
    assert excluded["excluded_reason"] == "unfinished template content"
    assert placeholder in session.calls  # excluded URLs are still fetched and hashed
    assert len(manual) == 2
    assert all(page["status"] == "excluded" for page in manual)
    assert all(page["retrieval_eligible"] is False for page in manual)
    assert all(page["chunks"] == [] for page in manual)

    required = {
        "canonical_url",
        "fetched_at",
        "content_sha256",
        "content_hash",
        "evidence_hash",
        "authority",
        "status",
        "retrieval_eligible",
        "chunks",
        "entity_id",
        "offer_id",
    }
    assert all(required <= page.keys() for page in [*com["pages"], *academy["pages"]])
    assert all(page["fetched_at"] == fetched_at for page in com["pages"])


def test_failed_page_is_recorded_but_never_retrieval_eligible() -> None:
    sitemap_url = "https://towardsai.com/pages-sitemap.xml"
    broken_url = "https://towardsai.com/broken/"
    session = FakeSession(
        {
            sitemap_url: FakeResponse(sitemap_url, sitemap(broken_url)),
            broken_url: FakeResponse(broken_url, "upstream failed", status_code=503),
        }
    )

    catalog = build_catalog(
        session=session,
        sitemap_url=sitemap_url,
        fetched_at="2026-08-08T00:00:00+00:00",
    )

    assert len(catalog["pages"]) == 1
    page = catalog["pages"][0]
    assert page["status"] == "fetch_error"
    assert page["retrieval_eligible"] is False
    assert page["chunks"] == []
    assert page["content_sha256"] == page["content_hash"]
    assert len(page["evidence_hash"]) == 64
    assert catalog["status_counts"] == {"fetch_error": 1}


def test_stale_academy_summaries_are_fetched_but_excluded_from_retrieval() -> None:
    stale_paths = (
        "/collections",
        "/collections/products",
        "/collections/developers",
        "/collections/professionals",
        "/pages/free-resources",
    )
    urls = tuple(f"https://academy.towardsai.net{path}" for path in stale_paths)
    routes = {
        ACADEMY_SITEMAP_URL: FakeResponse(
            ACADEMY_SITEMAP_URL,
            sitemap(*urls),
        )
    }
    routes.update(
        {
            url: FakeResponse(
                url,
                page_html("Legacy Academy summary", f"Stale content for {path}."),
            )
            for url, path in zip(urls, stale_paths, strict=True)
        }
    )
    session = FakeSession(routes)

    catalog = build_catalog(
        session=session,
        sitemap_url=ACADEMY_SITEMAP_URL,
        authority="official_academy",
        allowed_hosts=ACADEMY_HOSTS,
        fetched_at="2026-08-08T00:00:00+00:00",
    )

    pages_by_path = {page["path"]: page for page in catalog["pages"]}
    assert set(pages_by_path) == set(stale_paths)
    for path in stale_paths:
        page = pages_by_path[path]
        assert page["status"] == "excluded"
        assert page["retrieval_eligible"] is False
        assert page["excluded_reason"] == ACADEMY_EXCLUSIONS[path]
        assert page["text"]
        assert page["content_hash"] != ""
        assert f"https://academy.towardsai.net{path}" in session.calls


def test_parser_excludes_reviews_comparisons_and_simulated_conversations() -> None:
    parser = PageParser("https://towardsai.com/academy/llm-primer/")
    parser.feed(
        """
        <main>
          <h2>Official duration</h2><p>Average completion time is 10 hours.</p>
          <article class="ta-review"><p>The course actually has 12 hours.</p></article>
          <div class="ta-ment-vswrap"><p>A competitor costs $500.</p></div>
          <p class="ta-ment-vsnote">A single mentor costs $150 monthly.</p>
          <div class="ta-ment-thread"><p>An example user says guaranteed.</p></div>
        </main>
        """
    )
    parser.close()
    text = " ".join(section["text"] for section in parser.sections)

    assert "Average completion time is 10 hours" in text
    assert "12 hours" not in text
    assert "competitor costs" not in text
    assert "single mentor costs" not in text
    assert "example user" not in text


def test_parser_excludes_paid_course_outcomes_from_preview_evidence() -> None:
    parser = PageParser(
        "https://towardsai.com/academy/full-stack-ai-engineering-free-preview/"
    )
    parser.feed(
        """
        <main>
          <section id="preview"><h2>Free preview</h2><p>No card required.</p></section>
          <section id="outcomes">
            <h2>The full course outcomes</h2>
            <p>A certification that unlocks six-figure roles.</p>
          </section>
          <section id="cta"><p>Buy the paid course.</p></section>
        </main>
        """
    )
    parser.close()
    text = " ".join(section["text"] for section in parser.sections)

    assert "No card required" in text
    assert "certification" not in text
    assert "paid course" not in text


def test_mentorship_comparison_keeps_own_features_but_drops_competitors() -> None:
    parser = PageParser("https://towardsai.com/academy/mentorship/")
    parser.feed(
        """
        <main><section id="compare">
          <div class="inc"><p>Resume &amp; project reviews in 48–72h</p></div>
          <div class="board"><p>A single mentor costs $150/month.</p></div>
          <p class="sum">Bought separately: $2,000+ a month.</p>
        </section></main>
        """
    )
    parser.close()
    text = " ".join(section["text"] for section in parser.sections)

    assert "Resume & project reviews in 48–72h" in text
    assert "single mentor" not in text
    assert "Bought separately" not in text
