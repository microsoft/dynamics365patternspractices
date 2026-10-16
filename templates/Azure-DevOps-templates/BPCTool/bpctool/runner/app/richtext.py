"""Normalize Excel cell content for Azure DevOps HTML fields.

Catalog sources mix:
- already-HTML fragments (e.g. Microsoft references with <div><a>...)
- markdown-like plain text (bullets with '*', numbered lists, blank-line paragraphs)

ADO HTML fields accept HTML; plain markdown-like text renders poorly. This module
detects HTML and converts markdown-like content to safe HTML while leaving real
HTML intact.
"""

from __future__ import annotations

import html
import re
from typing import Any

_HTML_TAG_RE = re.compile(
    r"</?(?:div|p|br|ul|ol|li|a|span|strong|em|b|i|h[1-6]|table|tr|td|th|pre|code|blockquote)\b",
    re.IGNORECASE,
)
_HTML_ENTITY_RE = re.compile(r"&(?:amp|lt|gt|quot|nbsp|#\d+|#x[0-9a-f]+);", re.IGNORECASE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BARE_URL_RE = re.compile(r"(?<![\"'=])(https?://[^\s<>\"']+)")
_BULLET_RE = re.compile(r"^(\s*)([-*•]|\*)\s+(.*)$")
_NUMBERED_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")


def looks_like_html(value: Any) -> bool:
    text = "" if value is None else str(value)
    if not text.strip():
        return False
    sample = text[:4000]
    if _HTML_TAG_RE.search(sample):
        return True
    # Compact fragments that are still HTML-ish
    lowered = sample.lstrip().lower()
    return lowered.startswith("<") and ">" in lowered[:80]


def _escape_keep_newlines(text: str) -> str:
    return html.escape(text, quote=False)


def _inline_markdown(text: str) -> str:
    """Escape then restore simple markdown links / bare URLs as anchors."""
    placeholders: list[str] = []

    def stash(fragment: str) -> str:
        placeholders.append(fragment)
        return f"\x00{len(placeholders) - 1}\x00"

    def replace_md_link(match: re.Match[str]) -> str:
        label = html.escape(match.group(1), quote=False)
        href = html.escape(match.group(2), quote=True)
        return stash(f'<a href="{href}">{label}</a>')

    working = _MD_LINK_RE.sub(replace_md_link, text)

    def replace_bare(match: re.Match[str]) -> str:
        url = match.group(1).rstrip(".,);]")
        trailing = match.group(1)[len(url) :]
        href = html.escape(url, quote=True)
        return stash(f'<a href="{href}">{html.escape(url, quote=False)}</a>') + trailing

    working = _BARE_URL_RE.sub(replace_bare, working)
    escaped = _escape_keep_newlines(working)
    for index, fragment in enumerate(placeholders):
        escaped = escaped.replace(f"\x00{index}\x00", fragment)
    return escaped


def _list_indent(prefix: str) -> int:
    return len(prefix.replace("\t", "    ")) // 2


def markdown_to_html(value: Any) -> str:
    """Convert markdown-like plain text (catalog workbook style) to ADO HTML."""
    text = "" if value is None else str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = text.strip("\n")
    if not text.strip():
        return ""

    lines = text.split("\n")
    parts: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None  # "ul" | "ol"
    list_items: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if not paragraph:
            return
        body = "<br/>".join(_inline_markdown(line) for line in paragraph)
        parts.append(f"<p>{body}</p>")
        paragraph = []

    def flush_list() -> None:
        nonlocal list_kind, list_items
        if not list_kind or not list_items:
            list_kind = None
            list_items = []
            return
        items = "".join(f"<li>{item}</li>" for item in list_items)
        parts.append(f"<{list_kind}>{items}</{list_kind}>")
        list_kind = None
        list_items = []

    for raw in lines:
        if not raw.strip():
            flush_list()
            flush_paragraph()
            continue

        bullet = _BULLET_RE.match(raw)
        numbered = _NUMBERED_RE.match(raw)
        if bullet:
            flush_paragraph()
            kind = "ul"
            content = _inline_markdown(bullet.group(3).strip())
            if list_kind and list_kind != kind:
                flush_list()
            list_kind = kind
            list_items.append(content)
            continue
        if numbered:
            flush_paragraph()
            kind = "ol"
            content = _inline_markdown(numbered.group(3).strip())
            if list_kind and list_kind != kind:
                flush_list()
            list_kind = kind
            list_items.append(content)
            continue

        flush_list()
        paragraph.append(raw.rstrip())

    flush_list()
    flush_paragraph()

    if not parts:
        return f"<div>{_inline_markdown(text)}</div>"
    if len(parts) == 1:
        return parts[0]
    return "<div>" + "".join(parts) + "</div>"


def normalize_rich_text(
    value: Any,
    *,
    field_type: str = "html",
    convert_markdown_to_html: bool = False,
) -> str:
    """Normalize Excel content for ADO large-text / HTML fields.

    Behavior:
    - Existing HTML is always preserved.
    - Markdown-like text is preserved by default (caller should also set
      /multilineFieldsFormat/{field}=Markdown on create).
    - Optional convert_markdown_to_html converts markdown → HTML instead.
    """
    if value is None:
        return ""
    text = str(value)
    if not text.strip():
        return ""

    ft = (field_type or "").strip().lower()
    is_html_field = "html" in ft or ft in {"", "richtext", "rich text"}

    if looks_like_html(text):
        # Preserve authoring HTML from Excel (references, pasted content).
        return text.strip()

    if not is_html_field:
        return text.strip()

    if convert_markdown_to_html:
        return markdown_to_html(text)

    # Default: keep markdown/plain text as authored.
    return text.strip()


def normalize_field_value(
    value: Any,
    field_type: str,
    *,
    convert_markdown_to_html: bool = False,
) -> Any:
    """Coerce a catalog/template value for ADO, applying rich-text rules for HTML."""
    if value is None:
        return None
    ft = (field_type or "").strip().lower()
    if "html" in ft:
        return normalize_rich_text(
            value,
            field_type=field_type,
            convert_markdown_to_html=convert_markdown_to_html,
        )
    if "boolean" in ft or ft == "bool":
        return str(value).strip().lower() in {"true", "yes", "y", "1", "x"}
    return value if not isinstance(value, str) else value.strip()