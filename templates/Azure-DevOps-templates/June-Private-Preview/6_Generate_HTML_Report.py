import csv
import datetime as dt
import html
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from ado_setup_config import load_config


SCRIPT_DIR = Path(__file__).resolve().parent


def safe_path_part(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return slug.strip("._-") or "ado-project"


def project_output_dir(config, base_output: str) -> Path:
    org = urlparse(config.ado_org_url).path.strip("/").split("/")[-1] or config.ado_org_url.rstrip("/").split("/")[-1]
    return Path(base_output) / safe_path_part(f"{org}_{config.ado_project}")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return max(0, sum(1 for _ in csv.reader(handle)) - 1)


def read_csv_by_key(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row.get("Key", ""): row for row in csv.DictReader(handle) if row.get("Key")}


def latest_import_output_time(out_dir: Path) -> dt.datetime | None:
    names = {
        "ado-id-map.csv",
        "import-failures.json",
        "import-plan.json",
        "import-preview.csv",
        "skipped-deprecated-deleted.csv",
        "import-context.json",
    }
    files = [path for path in out_dir.glob("*") if path.is_file() and path.name in names]
    if not files:
        return None
    return dt.datetime.fromtimestamp(max(path.stat().st_mtime for path in files)).astimezone()


def tracked_run(out_dir: Path) -> dict[str, Any]:
    tracker_path = out_dir.parent / "import-run-tracker.json"
    tracker = read_json(tracker_path, {})
    end = latest_import_output_time(out_dir)
    started_raw = tracker.get("startedAt")
    started = dt.datetime.fromisoformat(started_raw) if started_raw else None
    elapsed = str(end - started).split(".")[0] if started and end else ""
    return {
        "startedAt": started.isoformat(timespec="seconds") if started else "",
        "lastImportUpdate": end.isoformat(timespec="seconds") if end else "",
        "elapsed": elapsed,
        "workers": tracker.get("workers", ""),
    }


def file_link(path: str | Path) -> str:
    try:
        return Path(path).resolve().as_uri()
    except ValueError:
        return ""


def ado_links(config, out_dir: Path, logs: list[dict[str, Any]]) -> list[dict[str, str]]:
    org = config.ado_org_url.rstrip("/")
    project_segment = quote(config.ado_project, safe="")
    process_query = quote(config.process_name, safe="")
    links = [
        {"label": "Open ADO project", "href": f"{org}/{project_segment}", "kind": "web"},
        {"label": "Open Boards", "href": f"{org}/{project_segment}/_boards/board/t", "kind": "web"},
        {"label": "Open Work Items", "href": f"{org}/{project_segment}/_workitems", "kind": "web"},
        {"label": "Open Process Settings", "href": f"{org}/_settings/process?process-name={process_query}", "kind": "web"},
        {"label": "Open output folder", "href": file_link(out_dir), "kind": "file"},
    ]
    for name in ("ado-id-map.csv", "import-failures.json", "import-preview.csv", "bpc-ado-setup-summary.html"):
        path = out_dir / name
        if path.exists():
            links.append({"label": f"Open {name}", "href": file_link(path), "kind": "file"})
    for log in logs:
        href = file_link(log["path"])
        if href:
            links.append({"label": f"Open {log['phase']} log", "href": href, "kind": "file"})
    return links


def latest_phase_logs() -> list[dict[str, Any]]:
    patterns = {
        "Phase 1": "1_ADO_Creation_Script_Log_*.txt",
        "Phase 2": "2_ADO_Page_Layout_Script_Threaded_Log_*.txt",
        "Phase 3": "3_ADO_Teams_Areas_Log_*.txt",
        "Phase 4": "4_ADO_Backlog_Config_Log_*.txt",
        "Wizard": "bpc_ado_setup_wizard*.log",
    }
    logs = []
    for phase, pattern in patterns.items():
        matches = sorted(SCRIPT_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if matches:
            logs.append(analyze_log(phase, matches[0]))
    return logs


def analyze_log(phase: str, path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    status_counts: dict[str, int] = {}
    for status in re.findall(r"Response \[(\d{3})\]", text):
        status_counts[status] = status_counts.get(status, 0) + 1
    lines = text.splitlines()
    warning_lines = [line for line in lines if re.search(r"\bWARNING\b", line, re.IGNORECASE)]
    response_errors = [
        line for line in lines
        if (match := re.search(r"Response \[(\d{3})\]", line)) and int(match.group(1)) >= 400
    ]
    error_lines = response_errors + [
        line for line in lines
        if re.search(r"\b(ERROR|FAILED|Exception|Traceback)\b", line, re.IGNORECASE)
        and not line.startswith("Response [")
    ]
    error_lines = dedupe_lines(error_lines)
    return {
        "phase": phase,
        "path": str(path),
        "modified": dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "size": path.stat().st_size,
        "statusCounts": status_counts,
        "warnings": warning_lines[:20],
        "errors": error_lines[:10],
        "warningCount": len(warning_lines),
        "errorCount": len(error_lines),
    }


def dedupe_lines(lines: list[str]) -> list[str]:
    seen = set()
    result = []
    for line in lines:
        normalized = re.sub(r"\s+", " ", line).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(line[:1200])
    return result


def summarize_import(out_dir: Path) -> dict[str, Any]:
    failures = read_json(out_dir / "import-failures.json", [])
    context = read_json(out_dir / "import-context.json", {})
    id_map = read_csv_by_key(out_dir / "ado-id-map.csv")
    raw_failures = failures if isinstance(failures, list) else []
    resolved_failures = []
    unresolved_failures = []
    for failure in raw_failures:
        imported = id_map.get(str(failure.get("key") or ""))
        if imported:
            resolved = dict(failure)
            resolved["resolvedAdoId"] = imported.get("ADO ID")
            resolved_failures.append(resolved)
        else:
            unresolved_failures.append(failure)
    run = tracked_run(out_dir)
    if not run.get("workers"):
        run["workers"] = context.get("parallelWorkers") or os.getenv("BPC_ADO_IMPORT_PARALLEL_WORKERS", "")
    run["maxRetries"] = context.get("maxRetries") or os.getenv("BPC_ADO_IMPORT_MAX_RETRIES", "")
    run["retryDelaySeconds"] = context.get("retryDelaySeconds") or os.getenv("BPC_ADO_IMPORT_RETRY_DELAY_SECONDS", "")
    return {
        "context": context,
        "outDir": str(out_dir),
        "planned": count_csv_rows(out_dir / "import-preview.csv"),
        "imported": count_csv_rows(out_dir / "ado-id-map.csv"),
        "skipped": count_csv_rows(out_dir / "skipped-deprecated-deleted.csv"),
        "failures": raw_failures,
        "resolvedFailures": resolved_failures,
        "unresolvedFailures": unresolved_failures,
        "run": run,
        "files": [
            {
                "name": path.name,
                "path": str(path),
                "size": path.stat().st_size,
                "modified": dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            }
            for path in sorted(out_dir.glob("*")) if path.is_file()
        ] if out_dir.exists() else [],
    }


def escape(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def status_badge(failures: int) -> str:
    return "Failed" if failures else "Completed"


def render_report(config, import_summary: dict[str, Any], logs: list[dict[str, Any]]) -> str:
    unresolved_failures = import_summary["unresolvedFailures"]
    resolved_failures = import_summary["resolvedFailures"]
    status = status_badge(len(unresolved_failures))
    generated = dt.datetime.now().isoformat(timespec="seconds")
    links = ado_links(config, Path(import_summary["outDir"]), logs)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BPC ADO Setup Report</title>
  <script>
    (() => {{
      const param = new URLSearchParams(window.location.search).get("scoutTheme");
      const theme =
        param || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      document.documentElement.setAttribute("data-theme", theme);
    }})();
  </script>
  <style>
    :root {{
      color-scheme: light;
      --cp-bg: #f7f4ef;
      --cp-bg-elevated: #fcfbf8;
      --cp-surface: #ffffff;
      --cp-surface-soft: #f5f5f5;
      --cp-border: #dedede;
      --cp-border-strong: #919191;
      --cp-text: #242424;
      --cp-text-muted: #5c5c5c;
      --cp-text-soft: #6f6f6f;
      --cp-accent: #b11f4b;
      --cp-accent-hover: #9a1a41;
      --cp-accent-soft: rgba(177, 31, 75, 0.08);
      --cp-accent-fg: #ffffff;
      --cp-success: #16a34a;
      --cp-danger: #dc2626;
      --cp-warning: #f59e0b;
      --cp-link: #0078d4;
      --cp-shadow: 0 18px 48px rgba(0, 0, 0, 0.12);
      --cp-overlay: rgba(255, 255, 255, 0.8);
      --cp-panel: rgba(255, 255, 255, 0.86);
      --cp-panel-strong: rgba(255, 255, 255, 0.96);
      --cp-sheen: rgba(255, 255, 255, 0.55);
      --cp-highlight: rgba(177, 31, 75, 0.12);
    }}
    html[data-theme="dark"] {{
      color-scheme: dark;
      --cp-bg: #3d3b3a;
      --cp-bg-elevated: #343231;
      --cp-surface: #292929;
      --cp-surface-soft: #2e2e2e;
      --cp-border: #474747;
      --cp-border-strong: #5f5f5f;
      --cp-text: #dedede;
      --cp-text-muted: #919191;
      --cp-text-soft: #b0b0b0;
      --cp-accent: #fd8ea1;
      --cp-accent-hover: #fb7b91;
      --cp-accent-soft: rgba(253, 142, 161, 0.14);
      --cp-accent-fg: #1a1a1a;
      --cp-success: #4ade80;
      --cp-danger: #f87171;
      --cp-warning: #fbbf24;
      --cp-link: #4da6ff;
      --cp-shadow: 0 18px 48px rgba(0, 0, 0, 0.32);
      --cp-overlay: rgba(41, 41, 41, 0.88);
      --cp-panel: rgba(41, 41, 41, 0.72);
      --cp-panel-strong: rgba(41, 41, 41, 0.96);
      --cp-sheen: rgba(255, 255, 255, 0.04);
      --cp-highlight: rgba(253, 142, 161, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--cp-bg);
      color: var(--cp-text);
      font-family: "Segoe UI", Aptos, Calibri, -apple-system, BlinkMacSystemFont, sans-serif;
      line-height: 1.45;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 32px; }}
    header {{ margin-bottom: 24px; }}
    h1 {{ margin: 0 0 8px; font-size: 32px; }}
    h2 {{ margin: 0 0 16px; font-size: 20px; }}
    h3 {{ margin: 0 0 8px; font-size: 16px; }}
    .muted {{ color: var(--cp-text-muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }}
    .card {{
      background: var(--cp-surface);
      border: 1px solid var(--cp-border);
      border-radius: 16px;
      box-shadow: var(--cp-shadow);
      padding: 20px;
      margin-bottom: 16px;
    }}
    .metric {{ font-size: 28px; font-weight: 700; }}
    .label {{ color: var(--cp-text-muted); font-size: 13px; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 0.625rem;
      padding: 4px 10px;
      background: var(--cp-accent-soft);
      color: var(--cp-accent);
      border: 1px solid var(--cp-border);
      font-weight: 600;
      font-size: 13px;
    }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }}
    .button {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1px solid var(--cp-border);
      border-radius: 0.625rem;
      padding: 8px 12px;
      background: var(--cp-surface-soft);
      color: var(--cp-text);
      text-decoration: none;
      font-weight: 600;
      font-size: 13px;
    }}
    .button.primary {{
      background: var(--cp-accent);
      color: var(--cp-accent-fg);
      border-color: var(--cp-accent);
    }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid var(--cp-border); vertical-align: top; }}
    th {{ color: var(--cp-text-muted); font-size: 13px; }}
    code, pre {{ font-family: Consolas, "Courier New", Courier, monospace; }}
    pre {{ white-space: pre-wrap; background: var(--cp-surface-soft); border: 1px solid var(--cp-border); border-radius: 0.625rem; padding: 12px; overflow: auto; }}
    a {{ color: var(--cp-link); }}
    .danger {{ color: var(--cp-danger); }}
    .success {{ color: var(--cp-success); }}
    .warning {{ color: var(--cp-warning); }}
    .note {{ background: var(--cp-surface-soft); border: 1px solid var(--cp-border); border-radius: 0.625rem; padding: 12px; }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="badge">{escape(status)}</div>
    <h1>Business Process Catalog ADO Setup Report</h1>
    <div class="muted">Generated {escape(generated)} for {escape(config.ado_org_url)} / {escape(config.ado_project)}</div>
    {render_quick_links(links)}
  </header>
  <section class="grid">
    <div class="card"><div class="metric">{import_summary["planned"]:,}</div><div class="label">Planned work items</div></div>
    <div class="card"><div class="metric">{import_summary["imported"]:,}</div><div class="label">Imported or recorded</div></div>
    <div class="card"><div class="metric">{import_summary["skipped"]:,}</div><div class="label">Skipped deprecated/deleted</div></div>
    <div class="card"><div class="metric {'danger' if unresolved_failures else 'success'}">{len(unresolved_failures):,}</div><div class="label">Unresolved failures</div></div>
    <div class="card"><div class="metric">{len(resolved_failures):,}</div><div class="label">Resolved prior failures</div></div>
    <div class="card"><div class="metric">{escape(import_summary["run"].get("elapsed")) or "n/a"}</div><div class="label">Tracked elapsed time</div></div>
    <div class="card"><div class="metric">{escape(import_summary["run"].get("workers")) or "n/a"}</div><div class="label">Threads / workers used</div></div>
  </section>
  {render_run(import_summary["run"])}
  {render_failures(unresolved_failures, resolved_failures)}
  {render_logs(logs)}
  {render_files(import_summary["files"])}
</main>
</body>
</html>
"""


def render_quick_links(links: list[dict[str, str]]) -> str:
    if not links:
        return ""
    buttons = []
    for index, link in enumerate(links):
        css = "button primary" if index == 0 else "button"
        target = "_blank" if link.get("kind") == "web" else "_self"
        buttons.append(
            f"<a class=\"{css}\" href=\"{escape(link['href'])}\" target=\"{target}\">{escape(link['label'])}</a>"
        )
    return f"<nav class=\"actions\">{''.join(buttons)}</nav>"


def render_run(run: dict[str, Any]) -> str:
    if not run.get("elapsed"):
        return ""
    return f"""<section class="card">
  <h2>Run timing</h2>
  <p class="note">Started {escape(run.get("startedAt"))}; latest import output update {escape(run.get("lastImportUpdate"))}; workers/threads {escape(run.get("workers"))}; max retries {escape(run.get("maxRetries"))}; retry delay seconds {escape(run.get("retryDelaySeconds"))}; elapsed wall-clock time {escape(run.get("elapsed"))}.</p>
</section>"""


def render_failures(unresolved: list[dict[str, Any]], resolved: list[dict[str, Any]]) -> str:
    if not unresolved and not resolved:
        return '<section class="card"><h2>Failures</h2><p class="success">No import failures were found.</p></section>'
    rows = []
    for failure in unresolved[:100]:
        rows.append(
            "<tr>"
            f"<td><code>{escape(failure.get('key'))}</code></td>"
            f"<td>{escape(failure.get('workItemType'))}</td>"
            f"<td>{escape(failure.get('title'))}<div class=\"muted\">{escape(failure.get('sourceFile'))} row {escape(failure.get('sourceRow'))}</div></td>"
            f"<td><pre>{escape(failure.get('message'))}</pre></td>"
            "</tr>"
        )
    return f"""<section class="card">
  <h2>Failures</h2>
  {render_resolved_note(resolved)}
  {render_unresolved_table(rows)}
</section>"""


def render_resolved_note(resolved: list[dict[str, Any]]) -> str:
    if not resolved:
        return ""
    rows = []
    for failure in resolved[:25]:
        rows.append(
            "<tr>"
            f"<td><code>{escape(failure.get('key'))}</code></td>"
            f"<td>{escape(failure.get('workItemType'))}</td>"
            f"<td>{escape(failure.get('title'))}</td>"
            f"<td>{escape(failure.get('resolvedAdoId'))}</td>"
            "</tr>"
        )
    return f"""<p class="success">Prior failure records below are now resolved because their keys are present in <code>ado-id-map.csv</code>.</p>
  <table><thead><tr><th>Key</th><th>Type</th><th>Title</th><th>ADO ID</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"""


def render_unresolved_table(rows: list[str]) -> str:
    if not rows:
        return '<p class="success">No unresolved failures remain.</p>'
    return f'<h3>Unresolved failures</h3><table><thead><tr><th>Key</th><th>Type</th><th>Source</th><th>Message</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'


def render_logs(logs: list[dict[str, Any]]) -> str:
    rows = []
    for log in logs:
        status_counts = ", ".join(f"{escape(k)}: {v}" for k, v in sorted(log["statusCounts"].items())) or "No API responses found"
        rows.append(
            "<tr>"
            f"<td>{escape(log['phase'])}</td>"
            f"<td><a href=\"{escape(file_link(log['path']))}\">Open log</a><br><code>{escape(log['path'])}</code><div class=\"muted\">{escape(log['modified'])}</div></td>"
            f"<td>{status_counts}</td>"
            f"<td><span class=\"warning\">{log['warningCount']}</span></td>"
            f"<td><span class=\"danger\">{log['errorCount']}</span>{render_log_details(log)}</td>"
            "</tr>"
        )
    return f"""<section class="card">
  <h2>Latest phase logs</h2>
  <p class="muted">These are historical findings in the latest phase log files. They may include transient API errors that were retried successfully or issues fixed in later reruns.</p>
  <table><thead><tr><th>Phase</th><th>Log file</th><th>API status counts</th><th>Warnings</th><th>Log findings</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</section>"""


def render_log_details(log: dict[str, Any]) -> str:
    if not log["errors"]:
        return ""
    items = "".join(f"<li><code>{escape(line)}</code></li>" for line in log["errors"][:5])
    return f"<details><summary>Details</summary><ul>{items}</ul></details>"


def render_files(files: list[dict[str, Any]]) -> str:
    rows = []
    for file in files:
        rows.append(
            "<tr>"
            f"<td><a href=\"{escape(file_link(file['path']))}\">{escape(file['name'])}</a></td>"
            f"<td><code>{escape(file['path'])}</code></td>"
            f"<td>{file['size']:,}</td>"
            f"<td>{escape(file['modified'])}</td>"
            "</tr>"
        )
    return f"""<section class="card">
  <h2>Import output files</h2>
  <table><thead><tr><th>Name</th><th>Path</th><th>Bytes</th><th>Modified</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</section>"""


def main() -> int:
    config = load_config(default_log_file="6_Generate_HTML_Report_Log.txt", require_process=True, ignore_unknown_args=True)
    base_output = os.getenv("BPC_ADO_IMPORT_OUTPUT") or str(SCRIPT_DIR / "out")
    out_dir = project_output_dir(config, base_output)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "bpc-ado-setup-summary.html"
    import_summary = summarize_import(out_dir)
    logs = latest_phase_logs()
    report_path.write_text(render_report(config, import_summary, logs), encoding="utf-8")
    print(f"HTML setup report written to: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
