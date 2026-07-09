---
title: Towards AI Helper
sdk: docker
app_port: 7860
pinned: false
---

# Towards AI Helper

Public sales helper for anonymous visitors on Towards AI Academy and
TowardsAI.net. It helps prospective students choose courses, bundles,
mentorship, free resources, the book, or B2B training/consulting.

It is deliberately separate from the Thinkific lesson tutor:

- This helper appears only on public, sitemap-discoverable pages.
- It hides when a visitor appears signed in.
- The first message must be one of the fixed prompt buttons.
- It uses DeepSeek V4 Flash through the DeepSeek API first, then falls back to
  Gemini 2.5 Flash if the primary provider fails.
- It does not answer general AI questions or give away course lesson content.

## Local Setup

```bash
cd /Users/louis/Documents/GitHub/tai-helper
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

Add this to public site footer code on `academy.towardsai.net` and
`towardsai.net`:

```html
<script
  src="https://YOUR-HF-SPACE/widget.js"
  data-api-base="https://YOUR-HF-SPACE"
  defer
></script>
```

The widget fetches `/api/helper/config`, checks the current public URL, hides on
signed-in sessions, and starts as a bottom-right `Ask the helper` bubble.

## Monitoring

Enable Opik:

```bash
OPIK_ENABLED=true
OPIK_API_KEY=...
OPIK_PROJECT_NAME=towards-ai-helper
```

Traces include URL, selected prompt, model, token usage, latency, and sources.
They intentionally avoid logging the full page dataset.
