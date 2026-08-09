---
title: Towards AI Helper
sdk: docker
app_port: 7860
pinned: false
---

# Towards AI Helper

Public sales helper for anonymous visitors on `towardsai.com`, the legacy
`towardsai.net` domain, and Towards AI Academy. It helps prospective students
choose courses, bundles, mentorship, free resources, the book, or B2B
training/consulting.

It is deliberately separate from the Thinkific lesson tutor:

- This helper appears on public `towardsai.com` pages and selected public
  Academy/legacy `.net` pages.
- It hides when a visitor appears signed in.
- The first message must be one of the fixed prompt buttons.
- It uses DeepSeek V4 Flash through the DeepSeek API first, then falls back to
  Gemini 2.5 Flash if the primary provider fails.
- It does not answer general AI questions or give away course lesson content.
- It returns offer facts only after every sentence has passed exact-quote and
  retrieved-chunk validation. Missing, stale, conflicting, or invalid evidence
  produces an explicit “I couldn't verify that” response instead of a guess.

## Local Setup

```bash
cd /path/to/tai-helper
uv sync
cp .env.example .env
uv run uvicorn tai_helper.api:app --host 0.0.0.0 --port 8001
```

Required model secrets:

```bash
DEEPSEEK_API_KEY=...
GEMINI_API_KEY=...
```

## Public Widget Snippet

Add this to the global footer code on `towardsai.com`. Add it separately to
`academy.towardsai.net` if the helper should also appear on its signed-out
public pages:

```html
<script
  src="https://YOUR-HF-SPACE/helper-widget.js"
  data-api-base="https://YOUR-HF-SPACE"
  defer
></script>
```

The widget fetches `/api/helper/config`, checks the current public URL, hides on
signed-in sessions, and starts as a bottom-right `Ask the helper` bubble.

The `.net` website redirects to `.com` before page JavaScript runs, so installing
the snippet only on `.net` will not make the helper appear on `.com`.

## Deployment Domain Settings

The defaults include both `.com` and `.net`. If the deployed Space already has
these environment variables set, update them because deployed values override
the defaults:

```bash
HELPER_ALLOWED_ORIGINS=https://towardsai.com,https://www.towardsai.com,https://academy.towardsai.net,https://towardsai.net,https://www.towardsai.net
HELPER_ALLOWED_HOSTS=towardsai.com,www.towardsai.com,academy.towardsai.net,towardsai.net,www.towardsai.net
HELPER_SITE_WIDE_HOSTS=towardsai.com,www.towardsai.com
```

`HELPER_SITE_WIDE_HOSTS` makes the widget available on current and future public
`.com` paths. Signed-in sessions, checkout/account paths, WordPress admin paths,
API paths, and previews remain blocked.

## Knowledge Catalog

`data/towardsai_com_pages.json` is generated from every URL in the current
`towardsai.com` page sitemap. `data/pages.json` is generated from every public
Academy sitemap URL. Each eligible page records its canonical URL, successful
fetch time, content hash, source authority, and heading-aware chunks. Known
staging pages, legacy duplicates, failed fetches, and manually described links
remain in the inventory but are explicitly ineligible as evidence.

Refresh both catalogs after public pages change:

```bash
python scripts/build_towardsai_com_catalog.py
```

The API accepts evidence only while each page's successful fetch is within
`HELPER_CATALOG_MAX_AGE_DAYS` (14 days by default). Canonical `.com` offer pages
supersede lower-authority Academy mirrors for the same offer. Routing notes are
never treated as factual evidence.

For factual answers, the model must return structured sentence-level claims.
Every claim needs a valid retrieved chunk ID and an exact contiguous quote from
that chunk. The server independently rejects altered numbers, number words,
prices, percentages, URLs, negation, invented quotes, malformed output, and
uncited text before anything is shown to a visitor.

## Monitoring

Enable Opik:

```bash
OPIK_ENABLED=true
OPIK_API_KEY=...
OPIK_PROJECT_NAME=towards-ai-helper
```

Traces include URL, selected prompt, model, token usage, latency, and sources.
They intentionally avoid logging the full page dataset.
