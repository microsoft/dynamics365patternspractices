"""Emit the HTML/JSON run summary (written at the end of every run)."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..run_outcome import (
    LIVE_SUMMARY_NAME,
    REHEARSAL_SUMMARY_NAME,
    build_outcome,
    catalog_placeholder_count,
    project_name_notice,
)

Emit = Callable[[str, str], None]

_STATUS_ICON = {
    "ok": "✓",
    "warning": "!",
    "error": "✕",
    "skipped": "–",
    "rehearsed": "○",
}
_BANNER_CLASS = {
    "success": "ok",
    "attention": "warn",
    "failed": "error",
    "cancelled": "warn",
    "rehearsal": "info",
}


def summary_paths(output_dir: Path, *, dry_run: bool) -> tuple[Path, Path]:
    stem = REHEARSAL_SUMMARY_NAME if dry_run else LIVE_SUMMARY_NAME
    return output_dir / f"{stem}.json", output_dir / f"{stem}.html"


def _previous_steps(json_path: Path, ir: dict[str, Any]) -> dict[str, Any]:
    """Step results from the last summary for the same process/project (live runs only)."""
    try:
        previous = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if (
        previous.get("processName") != ir["targets"]["process_name"]
        or previous.get("projectName") != ir["targets"]["project_name"]
    ):
        return {}
    steps = previous.get("stepResults")
    return steps if isinstance(steps, dict) else {}


def write_run_summary(
    ir: dict[str, Any],
    *,
    step_results: dict[str, Any],
    output_dir: Path,
    org_url: str,
    dry_run: bool,
    run_id: str = "",
    run_started: float | None = None,
    error: str | None = None,
    cancelled: bool = False,
) -> dict[str, Any]:
    """Write <summary>.json/.html and return the outcome dict shown in the UI."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path, html_path = summary_paths(output_dir, dry_run=dry_run)
    finished_at = datetime.now(timezone.utc).isoformat()

    merged: dict[str, Any] = {}
    earlier: dict[str, str] = {}
    if not dry_run:
        for step_id, result in _previous_steps(json_path, ir).items():
            if step_id in step_results or not isinstance(result, dict):
                continue
            merged[step_id] = result
            earlier[step_id] = str(result.get("finishedAt") or "")
    for step_id, result in step_results.items():
        if isinstance(result, dict):
            merged[step_id] = {**result, "runId": run_id, "finishedAt": finished_at}

    notices = [
        project_name_notice(
            ir["targets"]["project_name"],
            template_rows=int((ir.get("project") or {}).get("project_placeholders_replaced") or 0),
            catalog_values=catalog_placeholder_count((merged.get("catalog") or {}).get("prevalidate")),
        )
    ]
    outcome = build_outcome(
        merged,
        dry_run=dry_run,
        output_dir=output_dir,
        run_started=run_started,
        error=error,
        cancelled=cancelled,
        earlier_steps=earlier,
        notices=notices,
    )
    summary = {
        "runId": run_id,
        "generatedAt": finished_at,
        "mode": "rehearsal" if dry_run else "live",
        "orgUrl": org_url,
        "processName": ir["targets"]["process_name"],
        "projectName": ir["targets"]["project_name"],
        "workbookFingerprint": ir["source"]["fingerprint"],
        "outcome": outcome,
        "counts": ir["counts"],
        "stepResults": merged,
        "richText": {
            "htmlFieldsInTemplate": ir["counts"].get("html_fields", 0),
            "convertMarkdownToHtml": (merged.get("catalog") or {}).get("convert_markdown_to_html", False),
            "catalogMarkdownPreserved": (merged.get("catalog") or {}).get("markdown_preserved", 0),
            "catalogMarkdownConverted": (merged.get("catalog") or {}).get("markdown_converted", 0),
            "catalogHtmlPassthrough": (merged.get("catalog") or {}).get("html_passthrough", 0),
        },
    }
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    html_path.write_text(render_html(summary), encoding="utf-8")
    # The file list is computed before these two files are rewritten; refresh it.
    outcome["files"] = build_outcome(
        merged,
        dry_run=dry_run,
        output_dir=output_dir,
        run_started=run_started,
        error=error,
        cancelled=cancelled,
        earlier_steps=earlier,
        notices=notices,
    )["files"]
    return outcome


def apply_report(
    ir: dict[str, Any],
    *,
    step_results: dict[str, Any],
    output_dir: Path,
    org_url: str,
    emit: Emit,
    dry_run: bool = False,
    run_id: str = "",
    run_started: float | None = None,
) -> dict[str, Any]:
    write_run_summary(
        ir,
        step_results=step_results,
        output_dir=output_dir,
        org_url=org_url,
        dry_run=dry_run,
        run_id=run_id,
        run_started=run_started,
    )
    json_path, html_path = summary_paths(output_dir, dry_run=dry_run)
    emit("report", f"Wrote {html_path.name} and {json_path.name} under {output_dir}")
    return {"html_path": str(html_path), "json_path": str(json_path)}


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _short_time(iso: str) -> str:
    return str(iso or "")[:16].replace("T", " ")


def _step_row(step: dict[str, Any]) -> str:
    earlier = ""
    if step.get("earlierRun"):
        earlier = f' <span class="earlier">(from an earlier run, {_e(_short_time(step["earlierRun"]))})</span>'
    status = step["status"]
    return (
        f'<tr class="{status}"><td class="icon">{_STATUS_ICON.get(status, "")}</td>'
        f"<td>{_e(step['title'])}</td><td>{_e(step['summary'])}{earlier}</td>"
        f"<td class=\"num\">{_e(step.get('duration'))}</td></tr>"
    )


def _counts_text(counts: dict[str, Any]) -> str:
    return ", ".join(
        "{} {:,}".format(key.replace("_", " "), value)
        for key, value in counts.items()
        if isinstance(value, int)
    )


def _changes_html(changes: dict[str, Any] | None) -> str:
    if not changes:
        return ""
    parts = [f"<h2>Changes since the last import</h2><p>{_e(changes['summary'])}</p>"]
    if changes.get("items"):
        parts.append("<ul>" + "".join(f"<li>{_e(item)}</li>" for item in changes["items"]) + "</ul>")
    if changes.get("fields"):
        rows = "".join(
            f"""<tr><td>{_e(field['field'])}</td><td class="num">{int(field['count']):,}</td>
<td>{'Azure DevOps — often edited after import' if field['teamOwned'] else 'Workbook'}</td>
<td>{'<br/>'.join(_e(ex) for ex in field['examples'])}</td></tr>"""
            for field in changes["fields"]
        )
        parts.append(
            "<table><thead><tr><th>Field</th><th>Items</th><th>Usually edited in</th>"
            "<th>Examples (Azure DevOps → workbook)</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    if changes.get("partialWorkbook"):
        parts.append(
            "<p class=\"earlier\">The rehearsal read only part of the workbook (row limit), "
            "so items missing from the workbook are not listed.</p>"
        )
    if changes.get("note"):
        parts.append(f"<p class=\"earlier\">{_e(changes['note'])}</p>")
    if changes.get("file"):
        parts.append(f'<a class="file" href="{_e(changes["file"])}">Open {_e(changes["file"])}</a>')
    return "".join(parts)


def render_html(summary: dict[str, Any]) -> str:
    outcome = summary["outcome"]
    banner = _BANNER_CLASS.get(outcome["status"], "info")

    attention_html = ""
    if outcome["attention"]:
        items = []
        for item in outcome["attention"]:
            examples = "".join(f"<li>{_e(ex)}</li>" for ex in item.get("examples") or [])
            link = (
                f'<a class="file" href="{_e(item["file"])}">Open {_e(item["file"])}</a>'
                if item.get("file")
                else ""
            )
            items.append(
                f"""<li class="attention {item['severity']}">
  <h3>{_e(item['title'])}</h3>
  <p>{_e(item.get('detail'))}</p>
  <p class="fix"><strong>How to fix:</strong> {_e(item.get('fix'))}</p>
  {f'<p class="examples-label">For example:</p><ul class="examples">{examples}</ul>' if examples else ''}
  {link}
</li>"""
            )
        attention_html = f"<h2>What needs attention</h2><ol class=\"attention-list\">{''.join(items)}</ol>"
    else:
        attention_html = "<h2>What needs attention</h2><p>Nothing — no failures or questionable values.</p>"

    step_rows = "".join(_step_row(step) for step in outcome["steps"])
    notices_html = "".join(f'<p class="notice">{_e(notice)}</p>' for notice in outcome.get("notices") or [])

    automatic_html = ""
    if outcome.get("automaticFixes"):
        rows = "".join(
            "<li><strong>{:,}</strong> — {}. {}</li>".format(
                int(fix["count"] or 0), _e(fix["label"]), _e(fix["outcome"])
            )
            for fix in outcome["automaticFixes"]
        )
        automatic_html = (
            "<details><summary>Fixed automatically (no action needed)</summary>"
            f"<ul>{rows}</ul><p>Full list: <a href=\"import-prevalidate.csv\">import-prevalidate.csv</a></p></details>"
        )

    changes_html = _changes_html(outcome.get("changes"))

    file_rows = "".join(
        f"""<tr><td><a href="{_e(f['name'])}">{_e(f['label'])}</a></td><td>{_e(f['description'])}</td>
<td>{'' if f['updatedThisRun'] else '<span class="earlier">earlier run</span>'}</td></tr>"""
        for f in outcome["files"]
        if f.get("primary")
    )

    technical = json.dumps(summary["stepResults"], indent=2)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>BPCTool run report — {_e(summary['projectName'])}</title>
<style>
  :root {{ --ok:#15803d; --warn:#b45309; --error:#b91c1c; --info:#1d4ed8; --muted:#6b7280; }}
  body {{ font: 15px/1.5 -apple-system, "Segoe UI", system-ui, sans-serif; margin: 0; background: #f6f7f9; color: #111827; }}
  main {{ max-width: 980px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 .25rem; }}
  h2 {{ font-size: 1.15rem; margin: 2rem 0 .75rem; }}
  h3 {{ font-size: 1rem; margin: 0 0 .25rem; }}
  .meta {{ color: var(--muted); font-size: .9rem; margin-bottom: 1.25rem; }}
  .banner {{ border-radius: 10px; padding: 1rem 1.25rem; color: #fff; }}
  .banner p {{ margin: .25rem 0 0; opacity: .95; }}
  .banner.ok {{ background: var(--ok); }} .banner.warn {{ background: var(--warn); }}
  .banner.error {{ background: var(--error); }} .banner.info {{ background: var(--info); }}
  .notice {{ background: #eff6ff; border: 1px solid #bfdbfe; border-left: 5px solid var(--info); border-radius: 8px; padding: .6rem 1rem; margin: .75rem 0 0; font-weight: 600; }}
  .attention-list {{ list-style: none; padding: 0; margin: 0; display: grid; gap: .75rem; }}
  .attention {{ background: #fff; border: 1px solid #e5e7eb; border-left: 5px solid var(--warn); border-radius: 8px; padding: .85rem 1rem; }}
  .attention.error {{ border-left-color: var(--error); }}
  .attention p {{ margin: .25rem 0; }}
  .fix {{ background: #f9fafb; border-radius: 6px; padding: .4rem .6rem; }}
  .examples-label {{ color: var(--muted); font-size: .85rem; margin-bottom: 0; }}
  .examples {{ margin: .15rem 0 .4rem 1.1rem; padding: 0; font-size: .9rem; }}
  a.file {{ display: inline-block; margin-top: .25rem; font-weight: 600; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }}
  th, td {{ padding: .55rem .75rem; border-bottom: 1px solid #f0f1f3; text-align: left; vertical-align: top; }}
  th {{ background: #f9fafb; font-size: .85rem; color: #374151; }}
  td.icon {{ width: 1.5rem; font-weight: 700; text-align: center; }}
  td.num {{ white-space: nowrap; color: var(--muted); }}
  tr.ok td.icon {{ color: var(--ok); }} tr.warning td.icon {{ color: var(--warn); }}
  tr.error td.icon {{ color: var(--error); }} tr.skipped td.icon, tr.rehearsed td.icon {{ color: var(--muted); }}
  .earlier {{ color: var(--muted); font-size: .85rem; }}
  details {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: .6rem 1rem; margin-top: .75rem; }}
  summary {{ cursor: pointer; font-weight: 600; }}
  pre {{ white-space: pre-wrap; font-size: .8rem; max-height: 480px; overflow: auto; }}
  dl {{ display: grid; grid-template-columns: max-content 1fr; gap: .25rem 1rem; margin: .5rem 0; }}
  dt {{ color: var(--muted); }} dd {{ margin: 0; word-break: break-all; }}
</style>
</head>
<body>
<main>
  <h1>BPCTool run report</h1>
  <div class="meta">{_e(summary['processName'])} · {_e(summary['projectName'])} · {_e(summary['orgUrl'])} ·
    {_e(summary['generatedAt'][:16].replace('T', ' '))} UTC · {'Rehearsal (no changes made)' if summary['mode'] == 'rehearsal' else 'Live run'}</div>
  <div class="banner {banner}">
    <strong>{_e(outcome['headline'])}</strong>
    <p>{_e(outcome['subline'])}</p>
  </div>
  {notices_html}
  {attention_html}
  {automatic_html}
  {changes_html}
  <h2>Steps</h2>
  <table>
    <thead><tr><th></th><th>Step</th><th>Result</th><th>Time</th></tr></thead>
    <tbody>{step_rows}</tbody>
  </table>
  <h2>Files</h2>
  <table>
    <thead><tr><th>File</th><th>What it is</th><th></th></tr></thead>
    <tbody>{file_rows}</tbody>
  </table>
  <details>
    <summary>Run details</summary>
    <dl>
      <dt>Run ID</dt><dd>{_e(summary['runId'])}</dd>
      <dt>Workbook fingerprint</dt><dd>{_e(summary['workbookFingerprint'])}</dd>
      <dt>Output folder</dt><dd>{_e(outcome['outputDir'])}</dd>
      <dt>Template counts</dt><dd>{_e(_counts_text(summary['counts']))}</dd>
    </dl>
  </details>
  <details>
    <summary>Technical detail (raw step results)</summary>
    <pre>{_e(technical)}</pre>
  </details>
</main>
</body>
</html>
"""
