from __future__ import annotations

from tai_helper.api import CONTACT_FORM_URL
from tai_helper.settings import repo_root


def test_widget_network_failures_keep_a_clickable_contact_handoff() -> None:
    source = (repo_root() / "static" / "widget.js").read_text()

    assert f'var contactFormUrl = "{CONTACT_FORM_URL}";' in source
    assert "contactLinkMarkdown" in source
    assert "The helper is unavailable on this page. Please " in source
    assert "Something went wrong. Please " in source
    assert "renderMarkdown(" in source


def test_widget_offers_a_reset_control_beside_minimize() -> None:
    source = (repo_root() / "static" / "widget.js").read_text()

    reset_index = source.index("data-reset")
    close_index = source.index("data-close aria-label='Minimize helper'")
    assert reset_index < close_index, "reset must render to the left of minimize"
    assert "aria-label='Reset conversation'" in source
    assert "title='Reset conversation'" in source
    assert "resetBtn.addEventListener(\"click\", resetConversation)" in source


def test_widget_reset_clears_the_whole_conversation() -> None:
    source = (repo_root() / "static" / "widget.js").read_text()
    body = source[source.index("function resetConversation()") :]
    body = body[: body.index("\n  }\n")]

    assert 'state.threadId = ""' in body
    assert "state.messages = []" in body
    assert "state.firstMessageSent = false" in body
    assert 'msgs.querySelectorAll(".msg")' in body
    assert 'prompts.classList.remove("hidden")' in body
    assert "renderPrompts()" in body
    assert "setBusy(false)" in body


def test_widget_reset_discards_replies_from_the_previous_conversation() -> None:
    """A reply still in flight when the visitor resets must not land in the new
    conversation, or a stale answer would appear under a fresh question."""

    source = (repo_root() / "static" / "widget.js").read_text()

    assert "generation: 0," in source
    assert "state.generation += 1;" in source
    assert "var generation = state.generation;" in source
    # every fetch callback must bail out when the conversation moved on
    assert source.count("if (generation !== state.generation) return;") == 3
