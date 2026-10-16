"""Plain-language run outcome shared by the HTML report and the UI results card."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .timing import format_duration_ms

STEP_TITLES = {
    "process": "Process Template",
    "layout": "Page Layout",
    "project": "Project Creation",
    "teams": "Teams & Areas",
    "backlog": "Backlog Configuration",
    "catalog": "Catalog Import",
    "report": "Report",
}

LIVE_SUMMARY_NAME = "bpc-ado-setup-summary"
REHEARSAL_SUMMARY_NAME = "rehearsal-summary"

# name → (label, description); order is display order.
OUTPUT_FILES: dict[str, tuple[str, str]] = {
    f"{LIVE_SUMMARY_NAME}.html": ("Run report", "This summary as a web page."),
    f"{REHEARSAL_SUMMARY_NAME}.html": ("Rehearsal report", "What a live run would do."),
    "import-failures.csv": (
        "Rows that failed",
        "One line per catalog row that was not imported, with the problem and how to fix it. Opens in Excel.",
    ),
    "import-prevalidate.csv": (
        "Data checks",
        "Every catalog value that was changed or needs review, with source file and row. Opens in Excel.",
    ),
    "ado-id-map.csv": (
        "Imported items",
        "Catalog key → Azure DevOps work item ID. Used to resume; keep this file.",
    ),
    "import-preview.csv": ("Catalog sample", "First 50 catalog rows as they will be sent."),
    f"{LIVE_SUMMARY_NAME}.json": ("Run report (JSON)", "Machine-readable version of the report."),
    f"{REHEARSAL_SUMMARY_NAME}.json": ("Rehearsal report (JSON)", "Machine-readable version."),
    "import-failures.json": ("Rows that failed (JSON)", "Machine-readable failures with raw errors."),
    "import-prevalidate.json": ("Data checks (JSON)", "Machine-readable data-check summary."),
}


PROJECT_PLACEHOLDER_TEXT = "Your Project Name Here"


def catalog_placeholder_count(prevalidate: dict[str, Any] | None) -> int:
    for group in (prevalidate or {}).get("automaticFixes") or []:
        if group.get("kind") == "project_placeholder_replaced":
            return int(group.get("count") or 0)
    return 0


def project_name_notice(project: str, *, template_rows: int, catalog_values: int) -> str:
    """One sentence telling the user the workbook placeholder was swapped for their project name."""
    where = []
    if template_rows:
        where.append(f"{_plural(template_rows, 'template area/iteration row')}")
    if catalog_values:
        where.append(f"{_plural(catalog_values, 'catalog Area/Iteration Path value')}")
    if not where:
        return ""
    return f"Project name applied: '{PROJECT_PLACEHOLDER_TEXT}' → '{project}' in {' and '.join(where)}."


def n(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _plural(count: Any, word: str, plural: str | None = None) -> str:
    value = int(count or 0)
    return f"{n(value)} {word if value == 1 else (plural or word + 's')}"


def _warning_note(result: dict[str, Any]) -> str:
    warnings = int(result.get("warnings") or 0)
    return f" {_plural(warnings, 'warning')} — see the run log." if warnings else ""


def describe_step(step_id: str, result: dict[str, Any], *, dry_run: bool) -> tuple[str, str]:
    """Return (status, plain sentence) for one step result."""
    if result.get("skipped") is True:
        return "skipped", result.get("reason") or "Skipped by plan or policy."
    if dry_run:
        return "rehearsed", "Rehearsed — no changes made."
    if step_id == "process":
        text = (
            f"{_plural(result.get('wits_created'), 'work item type')} created, "
            f"{n(result.get('wits_updated'))} updated, {n(result.get('wits_disabled'))} disabled; "
            f"{_plural(result.get('fields_created'), 'field')} created"
            + (f" ({n(result.get('fields_skipped'))} already existed)" if result.get("fields_skipped") else "")
            + f"; {_plural(result.get('picklists'), 'picklist')}."
        )
        return "ok", text
    if step_id == "layout":
        status = "warning" if result.get("warnings") else "ok"
        return status, (
            f"{_plural(result.get('wits_processed'), 'form')} laid out with "
            f"{n(result.get('controls'))} controls ({n(result.get('hidden_fields'))} hidden fields)."
            + _warning_note(result)
        )
    if step_id == "project":
        if result.get("existed"):
            return "ok", "Project already existed — kept" + (
                ", description updated." if result.get("description_updated") else "."
            )
        return "ok", "Project created." if result.get("created") else "Project checked."
    if step_id == "teams":
        status = "warning" if result.get("warnings") else "ok"
        return status, (
            f"{_plural(result.get('teams'), 'team')}, {_plural(result.get('areas'), 'new area path')}, "
            f"{_plural(result.get('assignments'), 'team area assignment')}." + _warning_note(result)
        )
    if step_id == "backlog":
        status = "warning" if result.get("warnings") else "ok"
        return status, (
            f"{_plural(result.get('behaviors'), 'backlog level')}, {_plural(result.get('iterations'), 'iteration')}, "
            f"settings for {_plural(result.get('team_settings'), 'team')}." + _warning_note(result)
        )
    if step_id == "catalog":
        drafts = int(result.get("drafts") or 0)
        done = int(result.get("created") or 0) + int(result.get("skipped") or 0)
        failed = int(result.get("failed") or 0)
        summary = result.get("failure_summary") or {}
        text = f"{n(done)} of {n(drafts)} catalog items in Azure DevOps"
        if result.get("skipped"):
            text += f" ({n(result.get('created'))} new this run, {n(result.get('skipped'))} from earlier runs)"
        if failed:
            roots = summary.get("rootCauses", failed - int(result.get("missing_parent") or 0))
            blocked = summary.get("blockedByParent", result.get("missing_parent"))
            text += f"; {_plural(roots, 'row')} failed and blocked {n(blocked)} more."
            return "error", text
        if result.get("cancelled"):
            return "warning", text + f"; {n(result.get('cancelled'))} not started (cancelled)."
        return "ok", text + "."
    if step_id == "report":
        return "ok", "Report written."
    return "ok", "Finished."


def _file_rows(output_dir: Path, run_started: float | None, *, dry_run: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    skip = LIVE_SUMMARY_NAME if dry_run else REHEARSAL_SUMMARY_NAME
    for name, (label, description) in OUTPUT_FILES.items():
        if name.startswith(skip):
            continue
        path = output_dir / name
        if not path.is_file():
            continue
        mtime = path.stat().st_mtime
        rows.append(
            {
                "name": name,
                "label": label,
                "description": description,
                "updatedThisRun": run_started is None or mtime >= run_started - 1,
                "updatedAt": datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds"),
                "primary": not name.endswith(".json") and name != "import-preview.csv",
            }
        )
    return rows


def _example_text(example: dict[str, Any]) -> str:
    where = f"{example.get('sourceFile') or 'catalog'} row {example.get('sourceRow') or '?'}"
    key = example.get("key")
    text = f"{where} ({key})" if key else where
    problem = str(example.get("problem") or "")
    if not problem and example.get("value") not in (None, ""):
        label = example.get("fieldLabel") or "value"
        problem = f"{label}: '{str(example['value'])[:80]}'"
    elif not problem and example.get("fieldLabel"):
        problem = f"{example['fieldLabel']} is empty"
    return f"{text} — {problem}" if problem else text


def build_outcome(
    step_results: dict[str, Any],
    *,
    dry_run: bool,
    output_dir: Path | None,
    run_started: float | None = None,
    error: str | None = None,
    cancelled: bool = False,
    earlier_steps: dict[str, str] | None = None,
    notices: list[str] | None = None,
) -> dict[str, Any]:
    """Headline, per-step sentences, prioritized attention items, and output files.

    ``earlier_steps`` (step id → finishedAt) lists only steps that did not run this
    time and whose results in ``step_results`` were carried over from an earlier run.
    """
    earlier = earlier_steps or {}
    steps: list[dict[str, Any]] = []
    for step_id in STEP_TITLES:
        result = step_results.get(step_id)
        if not isinstance(result, dict):
            continue
        status, text = describe_step(step_id, result, dry_run=dry_run and step_id not in earlier)
        steps.append(
            {
                "id": step_id,
                "title": STEP_TITLES[step_id],
                "status": status,
                "summary": text,
                "duration": format_duration_ms(result.get("duration_ms")) if result.get("duration_ms") else "",
                "earlierRun": earlier.get(step_id, ""),
            }
        )

    attention: list[dict[str, Any]] = []
    catalog = step_results.get("catalog") if isinstance(step_results.get("catalog"), dict) else {}
    catalog_note = (
        f" (from the run on {earlier['catalog'][:16].replace('T', ' ')})" if "catalog" in earlier else ""
    )
    for group in (catalog.get("failure_summary") or {}).get("groups") or []:
        blocked = int(group.get("blockedChildren") or 0)
        attention.append(
            {
                "severity": "error",
                "title": f"{_plural(group['count'], 'row')}: {group['label']}{catalog_note}",
                "detail": (
                    f"These rows were not imported"
                    + (f", and {_plural(blocked, 'child row')} under them were blocked." if blocked else ".")
                ),
                "fix": group.get("fix", ""),
                "examples": [_example_text(ex) for ex in (group.get("examples") or [])[:3]],
                "file": "import-failures.csv",
                "count": group["count"] + blocked,
            }
        )
    if int(catalog.get("outcome_unknown") or 0):
        attention.append(
            {
                "severity": "error",
                "title": f"{_plural(catalog['outcome_unknown'], 'create')} had a network error with unknown outcome",
                "detail": "Azure DevOps may or may not have created these items.",
                "fix": "Search Azure DevOps for duplicates of these rows before re-running Catalog Import.",
                "examples": [],
                "file": "import-failures.csv",
                "count": int(catalog["outcome_unknown"]),
            }
        )
    prevalidate = catalog.get("prevalidate") or {}
    for group in prevalidate.get("needsReview") or []:
        attention.append(
            {
                "severity": "warning",
                "title": f"{_plural(group['count'], 'value')}: {group['label']}{catalog_note}",
                "detail": group.get("outcome", ""),
                "fix": group.get("fix", ""),
                "examples": [_example_text(ex) for ex in (group.get("examples") or [])[:3]],
                "file": "import-prevalidate.csv",
                "count": group["count"],
            }
        )
    for step in steps:
        if step["status"] == "warning" and step["id"] != "catalog":
            attention.append(
                {
                    "severity": "warning",
                    "title": f"{step['title']} reported warnings",
                    "detail": step["summary"],
                    "fix": "Read the run log lines for this step; most warnings are safe to re-run.",
                    "examples": [],
                    "file": "",
                    "count": 0,
                }
            )
    severity_rank = {"error": 0, "warning": 1, "info": 2}
    attention.sort(key=lambda item: (severity_rank[item["severity"]], -int(item["count"] or 0)))

    automatic = [
        {
            "kind": group.get("kind", ""),
            "label": group["label"],
            "count": group["count"],
            "outcome": group.get("outcome", ""),
        }
        for group in prevalidate.get("automaticFixes") or []
    ]

    drafts = int(catalog.get("drafts") or 0)
    done = int(catalog.get("created") or 0) + int(catalog.get("skipped") or 0)
    failure_summary = catalog.get("failure_summary") or {}
    errors = [item for item in attention if item["severity"] == "error"]
    review_total = int(prevalidate.get("needsReviewTotal") or 0)

    if cancelled:
        status = "cancelled"
        headline = "Run cancelled"
        subline = "Run again to continue — Catalog Import resumes from the imported-items list."
    elif error:
        status = "failed"
        headline = "Run stopped with an error"
        subline = error
    elif dry_run:
        status = "rehearsal"
        headline = "Rehearsal finished — nothing was changed in Azure DevOps"
        parts = []
        if drafts:
            remaining = drafts - int(catalog.get("skipped") or 0)
            parts.append(f"A live run would import {n(remaining)} of {n(drafts)} catalog items.")
        if review_total:
            parts.append(f"{_plural(review_total, 'value')} need review before the live run.")
        subline = " ".join(parts) or "Uncheck “Rehearsal only” and run again for the live run."
    elif errors and "catalog" in earlier:
        status = "attention"
        headline = "Finished — problems from an earlier Catalog Import are still open"
        stamp = earlier["catalog"][:16].replace("T", " ")
        when = f"the Catalog Import on {stamp}" if stamp else "an earlier Catalog Import"
        roots = failure_summary.get("rootCauses")
        subline = (
            f"The steps run this time finished. {_plural(roots, 'row')} from {when} "
            f"still {'needs' if roots == 1 else 'need'} fixing; "
            "then re-run Catalog Import."
            if roots
            else f"The steps run this time finished. See the items below from {when}."
        )
    elif errors:
        status = "attention"
        if drafts:
            headline = f"Finished with problems: {n(done)} of {n(drafts)} catalog items imported"
        else:
            headline = "Finished with problems"
        roots = failure_summary.get("rootCauses")
        if roots:
            subline = (
                f"{_plural(roots, 'row')} {'needs' if roots == 1 else 'need'} fixing; "
                f"{'it' if roots == 1 else 'they'} blocked {n(failure_summary.get('blockedByParent'))} more. "
                "Fix them, then re-run Catalog Import — it skips items already imported."
            )
        else:
            subline = "See What needs attention below."
    elif attention:
        status = "attention"
        headline = "Finished — a few things to review"
        subline = "Everything was applied. Review the items below when convenient."
    else:
        status = "success"
        headline = "Finished — everything was applied"
        subline = (
            f"All {n(drafts)} catalog items are in Azure DevOps." if drafts else "All selected steps completed."
        )

    return {
        "status": status,
        "headline": headline,
        "subline": subline,
        "dryRun": dry_run,
        "notices": [notice for notice in notices or [] if notice],
        "steps": steps,
        "attention": attention,
        "automaticFixes": automatic,
        "files": _file_rows(output_dir, run_started, dry_run=dry_run) if output_dir else [],
        "outputFolder": output_dir.name if output_dir else "",
        "outputDir": str(output_dir) if output_dir else "",
        "outputRoot": str(output_dir.parent) if output_dir else "",
    }
