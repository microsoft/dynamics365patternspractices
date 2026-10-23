from app.richtext import looks_like_html, markdown_to_html, normalize_rich_text


def test_detects_html_fragments():
    assert looks_like_html(
        '<div><a href="https://learn.microsoft.com/x">https://learn.microsoft.com/x</a> </div>'
    )
    assert not looks_like_html("Common asset classifications include:\n * Tangible")


def test_markdown_bullets_become_html_list():
    html = markdown_to_html(
        "Intro sentence.\n\nCommon types:\n * Tangible\n * Intangible\n"
    )
    assert "<ul>" in html
    assert "<li>Tangible</li>" in html
    assert "<li>Intangible</li>" in html
    assert "<p>Intro sentence.</p>" in html


def test_normalize_passthrough_html():
    raw = '<div><a href="https://example.com">https://example.com</a> </div>'
    assert normalize_rich_text(raw, field_type="HTML") == raw.strip()
    assert (
        normalize_rich_text(raw, field_type="HTML", convert_markdown_to_html=True)
        == raw.strip()
    )


def test_normalize_preserves_markdown_by_default():
    raw = "* Introduction\n * Overview"
    assert normalize_rich_text(raw, field_type="html") == raw.strip()


def test_normalize_converts_markdown_when_requested():
    raw = "* Introduction\n * Overview"
    out = normalize_rich_text(raw, field_type="html", convert_markdown_to_html=True)
    assert "<ul>" in out
    assert "Introduction" in out
