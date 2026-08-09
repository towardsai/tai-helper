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
