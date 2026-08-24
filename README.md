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
- It uses DeepSeek V4 Flash through OpenRouter first, then falls back to
  Gemini 3.7 Flash if the primary provider fails.
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
HELPER_PRIMARY_API_KEY=...   # OpenRouter key
GEMINI_API_KEY=...
```

## Model Providers

The primary model is DeepSeek V4 Flash reached **through OpenRouter only**. The
direct DeepSeek API path was removed deliberately: that standalone account ran
out of balance and took the helper down, while OpenRouter draws on a shared
balance that is kept topped up. `HELPER_PRIMARY_MODEL` can name any OpenRouter
model without code changes.

Gemini 3.7 Flash is the fallback, deliberately kept on Google's own API rather
than routed through OpenRouter, so the backup does not share a gateway with the
primary. It only runs when the primary fails and it passes the grounding
validator slightly less often, so a broken primary shows up as visitors being
told "I couldn't verify that" on questions the helper used to answer.
`usage.provider` and `usage.fallback_from` say which model actually replied.

**Reasoning must stay off on both.** Reasoning tokens are billed against
`HELPER_MAX_OUTPUT_TOKENS`, so with it on the model spends the budget reasoning
and returns a truncated fragment that cannot pass validation — which reads as a
legitimate abstention rather than a failure. Each provider has its own switch
and **accepts the other's with HTTP 200 while ignoring it**, so a wrong switch
fails silently. This has caused two separate outages:

| Provider | Switch sent | Controlled by |
| --- | --- | --- |
| OpenRouter | `reasoning: {enabled: false}` | `HELPER_PRIMARY_REASONING=false` |
| Gemini | `thinking_config.thinking_budget: 0` | `HELPER_GEMINI_THINKING_BUDGET=0` |

When changing model or provider, check `usage.output_tokens` on a real grounded
query. A value near zero means reasoning is still on.

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

The panel header carries two controls: a reset button that clears the thread and
returns to the starter prompts, and the minimize button. Resetting also discards
any reply still in flight, so a late answer from the previous thread cannot
appear under a new question.

The `.net` website redirects to `.com` before page JavaScript runs, so installing
the snippet only on `.net` will not make the helper appear on `.com`.

## Deployment

The helper runs on the Hugging Face Space `towardsai-tutors/tai_helper`, served
at `https://towardsai-tutors-tai-helper.hf.space`. **The Space is a separate git
repository from GitHub, so merging to `main` is not a deploy.** Its history is a
linear series of `Deploy tai-helper <sha>` snapshots.

Deploy with the **Deploy to HF Space** workflow, or locally:

```bash
HF_TOKEN=hf_... scripts/deploy_to_space.sh
```

Both run the test suite first, push a snapshot, then poll `/healthz` until the
Space reports a fresh catalog. The weekly catalog refresh calls the same workflow
so a refreshed catalog actually reaches visitors. Set `HF_TOKEN` as a repository
secret (write-scoped for the Space) for either to work from CI.

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
fetch time, content hash, source authority, heading-aware chunks, and atomic
evidence spans (complete source sentences, DOM blocks, or table rows). A second
hash binds the canonical URL, page text, chunks, and span definitions together.
Known staging pages, legacy duplicates, conflicting catalog summaries, failed
fetches, and manually described links remain in the inventory but are explicitly
ineligible as evidence.

Refresh both catalogs after public pages change:

```bash
python scripts/build_towardsai_com_catalog.py
```

The API accepts evidence only while each page's successful fetch is within
`HELPER_CATALOG_MAX_AGE_DAYS` (14 days by default). Canonical `.com` offer pages
supersede lower-authority Academy mirrors for the same offer. Routing notes are
never treated as factual evidence.

### The catalog must not be allowed to expire

Past that 14-day window every page is rejected at once, so retrieval returns
nothing and *every* answer becomes "I couldn't verify that". The API stays up and
returns 200 throughout, which is why this can run unnoticed. Three things guard
against it:

- **Refresh Catalog** (`.github/workflows/refresh-catalog.yml`) rebuilds both
  catalogs every Monday and commits them, keeping two refreshes of headroom
  before the 14-day boundary. It runs the full test suite first so a partial or
  misparsed scrape is never committed.
- **`/healthz`** reports the countdown (see Monitoring below).
- **HF Space Keepalive** fails when the catalog has expired, when fewer than
  `CATALOG_WARN_DAYS` remain, or when the deployed Space is too old to report
  catalog state at all.

Refreshing the catalog on `main` does not by itself change what visitors see:
the Space is deployed separately (see Deployment below).

For factual answers, the model must return structured sentence-level claims.
Every claim needs a valid retrieved chunk ID and must copy one complete
server-defined evidence span. Arbitrary substrings are forbidden, so a model
cannot turn “No code required” into “code required” or cross table-row
boundaries. The server independently verifies catalog freshness, both hashes,
canonical URLs, chunk/span identity, numbers, prices, percentages, URLs,
negation, the named offer, the requested fact type, and output schema before
anything is shown to a visitor. If exact target-qualified evidence is missing or
generation fails validation, the API returns no sources and directs the visitor
to the canonical [Towards AI contact form](https://towardsai.com/academy/contact/#contact)
instead of guessing.

## Monitoring

`GET /healthz` reports liveness and evidence-catalog freshness together:

```json
{
  "status": "ok",
  "catalog": {
    "evidencePages": 32,
    "maxAgeDays": 14,
    "oldestFetchAgeDays": 0.4,
    "expiresInDays": 13.6,
    "fresh": true
  }
}
```

`status` becomes `degraded` and `evidencePages` drops to `0` once the catalog
expires. The endpoint deliberately still returns 200 so the Space is not
restarted for a container that is running correctly; the scheduled keepalive is
what turns a degraded catalog into a failed workflow run.

Enable Opik:

```bash
OPIK_ENABLED=true
OPIK_API_KEY=...
OPIK_PROJECT_NAME=towards-ai-helper
```

Traces include URL, selected prompt, model, token usage, latency, and sources.
They intentionally avoid logging the full page dataset.
