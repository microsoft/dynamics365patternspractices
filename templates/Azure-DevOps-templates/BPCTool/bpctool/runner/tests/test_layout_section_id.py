"""Layout section lookup must not silently fall back to Section1."""

from app.writers.layout import _section_id


LAYOUT = {
    "pages": [
        {
            "id": "page-details",
            "label": "Details",
            "sections": [
                {"id": "Section1", "label": "Section 1"},
                {"id": "Section2", "label": "Section 2"},
            ],
        }
    ]
}


def test_section_id_matches_id_or_label() -> None:
    assert _section_id(LAYOUT, "page-details", "Section2") == "Section2"
    assert _section_id(LAYOUT, "page-details", "Section 2") == "Section2"


def test_section_id_returns_none_when_missing() -> None:
    assert _section_id(LAYOUT, "page-details", "Section3") is None
    assert _section_id(LAYOUT, "missing-page", "Section1") is None
    assert _section_id(None, "page-details", "Section1") is None
