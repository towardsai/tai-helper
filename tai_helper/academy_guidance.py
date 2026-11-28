"""Read reviewed Academy guidance. Reader sends only a fixed public GET, never chat data."""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from urllib.request import Request, urlopen

ENDPOINT = "https://academy-helper-guidance.bouchard-lf.workers.dev/v1/guide"
_entries = json.loads(Path(__file__).with_name("academy_guidance.json").read_text())
_lock = Lock()
_refresh_at = 0.0


def _matches(row, question, context):
    return (
        re.search(row["pattern"], question, re.IGNORECASE)
        and not (
            row.get("exclude") and re.search(row["exclude"], question, re.IGNORECASE)
        )
        and (not row.get("focus") or re.search(row["focus"], context, re.IGNORECASE))
    )


def _refresh():
    global _entries, _refresh_at
    if time.monotonic() < _refresh_at or not _lock.acquire(blocking=False):
        return
    try:
        _refresh_at = time.monotonic() + 60
        req = Request(ENDPOINT, headers={"User-Agent": "TowardsAI-Academy-Guide/1"})
        with urlopen(req, timeout=2) as response:
            rows = json.load(response)
        if (
            isinstance(rows, list)
            and rows
            and all(
                isinstance(r, dict)
                and all(k in r for k in ("id", "pattern", "en", "fr", "sources"))
                for r in rows
            )
        ):
            _entries = rows
            _refresh_at = time.monotonic() + 300
    except (OSError, ValueError):
        pass
    finally:
        _lock.release()


def guidance_answer(question, history=(), *, instant=None):
    context = " ".join([*list(history)[-2:], question])
    if not any(_matches(row, question, context) for row in _entries):
        return None
    _refresh()
    matches = [r for r in _entries if _matches(r, question, context)]
    if not matches:
        return None
    rows = [matches[0]]
    if rows[0]["id"] == "gift":
        rows.extend(r for r in matches if r["id"] == "black-friday")
    now = (instant or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    language = (
        "fr"
        if re.search(
            r"\b(?:est-ce|puis-je|cadeau|cours|forfait|rabais|vendredi fou|mon reçu|obtenir|combien|reconversion)\b",
            question,
            re.IGNORECASE,
        )
        else "en"
    )
    paragraphs, sources = [], []
    for row in rows:
        active = (not row.get("starts") or row["starts"] <= now) and (
            not row.get("ends") or now < row["ends"]
        )
        paragraphs.append(row[language] if active else row["expired_" + language])
        for source in row["sources"]:
            if source not in sources:
                sources.append(source)
    return "\n\n".join(paragraphs), sources
