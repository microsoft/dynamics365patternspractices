from __future__ import annotations

import argparse
import concurrent.futures
import csv
import getpass
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .ado import AzureDevOpsClient, parse_project_url
from .mapping import load_template
from .sources import find_source_files, load_rows
from .transform import WorkItemDraft, build_drafts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import Business Process Catalog files into Azure DevOps.")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_common(sub.add_parser("plan", help="Build a local import plan and CSV previews."))
    import_parser = sub.add_parser("import", help="Create work items in Azure DevOps from the source files.")
    _add_common(import_parser)
    import_parser.add_argument("--pat-env", default="AZURE_DEVOPS_PAT", help="Environment variable containing the PAT. If unset, the importer prompts securely.")
    import_parser.add_argument("--dry-run", action="store_true", help="Build API payloads without calling ADO.")
    import_parser.add_argument("--continue-on-error", action="store_true", help="Continue after individual work item failures.")
    import_parser.add_argument("--skip-unknown-fields", action="store_true", help="Drop fields that do not exist in the target project.")
    import_parser.add_argument("--progress-interval-seconds", type=int, default=60, help="Minimum seconds between progress summaries.")
    import_parser.add_argument("--print-created-items", action="store_true", help="Print every created work item. By default the importer prints timed summaries only.")
    import_parser.add_argument("--max-retries", type=int, default=3, help="Retry count for transient create failures.")
    import_parser.add_argument("--retry-delay-seconds", type=float, default=5, help="Base delay between transient create retries.")
    import_parser.add_argument("--recovery-field", default="MSBPC.microsoftid", help="Field used to find a work item after an ambiguous transient failure.")
    import_parser.add_argument("--parallel-workers", type=int, default=4, help="Number of parent-aware create workers. Use 1 for serial import.")
    import_parser.add_argument("--include-deprecated-deleted", action="store_true", help="Include rows whose Catalog status is Deprecated or Deleted. Create mode skips them by default.")
    backfill_parser = sub.add_parser("backfill-links", help="Backfill missing parent-child links for already-created work items.")
    _add_common(backfill_parser)
    backfill_parser.add_argument("--pat-env", default="AZURE_DEVOPS_PAT", help="Environment variable containing the PAT. If unset, prompts securely.")
    backfill_parser.add_argument("--dry-run", action="store_true", help="Write a link plan without modifying Azure DevOps.")
    backfill_parser.add_argument("--id-map", help="Path to ado-id-map.csv. Defaults to the project-scoped output folder.")
    args = parser.parse_args(argv)

    if args.command == "plan":
        return plan(args)
    if args.command == "import":
        return import_to_ado(args)
    if args.command == "backfill-links":
        return backfill_links(args)
    return 1


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", required=True, help="Folder containing the four BPC source workbooks/CSVs.")
    parser.add_argument("--template", help="ADO template guideline workbook with Fields and Work item types sheets.")
    parser.add_argument("--project-url", required=True, help="Azure DevOps project URL.")
    parser.add_argument("--output", default="out", help="Base output folder for plans, CSV previews, logs, and ID maps.")
    parser.add_argument("--disable-project-output-scope", action="store_true", help="Write directly to --output instead of a project-specific subfolder.")


def plan(args: argparse.Namespace) -> int:
    _progress("Loading source files and template...")
    drafts = _load_drafts(args.source, args.template)
    project = parse_project_url(args.project_url)
    _normalize_tree_paths(drafts, project.project)
    out = _resolve_output_dir(args, project)
    out.mkdir(parents=True, exist_ok=True)
    _write_output_context(out, project, args)
    _remove_stale_outputs(out)
    _write_plan(out / "import-plan.json", drafts)
    _write_preview_csv(out / "import-preview.csv", drafts)
    _write_issues_csv(out / "import-issues.csv", drafts)
    print(f"Planned {len(drafts)} work items.")
    print(f"Wrote {out / 'import-plan.json'}")
    print(f"Wrote {out / 'import-preview.csv'}")
    return 0


def import_to_ado(args: argparse.Namespace) -> int:
    pat = _get_pat(args.pat_env, args.dry_run)
    args._resolved_pat = pat

    _progress("Loading source files and template...")
    drafts = _load_drafts(args.source, args.template)
    drafts, skipped = _filter_create_mode_drafts(drafts, args.include_deprecated_deleted)
    _progress(f"Loaded {len(drafts)} planned work items. Skipped {len(skipped)} deprecated/deleted row(s).")

    _progress("Connecting to Azure DevOps...")
    client = AzureDevOpsClient(args.project_url, pat or "dry-run")
    _normalize_tree_paths(drafts, client.project.project)
    out = _resolve_output_dir(args, client.project)
    out.mkdir(parents=True, exist_ok=True)
    _write_output_context(out, client.project, args)
    _progress("Writing local import plan and preview files...")
    _write_plan(out / "import-plan.json", drafts)
    _write_preview_csv(out / "import-preview.csv", drafts)
    _write_skipped_csv(out / "skipped-deprecated-deleted.csv", skipped)

    _progress("Reading Azure DevOps fields and work item types...")
    valid_fields = client.get_fields() if not args.dry_run else set()
    work_item_type_refs = client.get_work_item_type_references() if not args.dry_run else {}
    args._work_item_type_refs = {_work_item_type_key(key): value for key, value in work_item_type_refs.items()}
    valid_wits = set(work_item_type_refs) if not args.dry_run else set()
    if not args.dry_run:
        _progress("Checking and creating Area Path / Iteration Path nodes...")
        _ensure_classification_nodes(client, drafts)

    id_map: dict[str, int] = _read_id_map(out / "ado-id-map.csv")
    _progress(f"Starting import. {len(id_map)} work item(s) already recorded in {out / 'ado-id-map.csv'}.")
    reporter = ProgressReporter(len(drafts), len(id_map), args.progress_interval_seconds)
    failures, payloads = _import_drafts(
        args=args,
        drafts=drafts,
        id_map=id_map,
        id_map_path=out / "ado-id-map.csv",
        valid_fields=valid_fields,
        valid_wits=valid_wits,
        reporter=reporter,
    )

    if payloads:
        (out / "dry-run-payloads.json").write_text(json.dumps(payloads, indent=2), encoding="utf-8")
    if failures:
        (out / "import-failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
        print(f"Import completed with {len(failures)} failure(s). See {out / 'import-failures.json'}", file=sys.stderr)
        return 2
    reporter.report(len(drafts), len(id_map), "completed")
    print("Import completed successfully." if not args.dry_run else "Dry run completed successfully.")
    return 0


def backfill_links(args: argparse.Namespace) -> int:
    pat = _get_pat(args.pat_env, args.dry_run)
    _progress("Loading source files and template...")
    drafts = _load_drafts(args.source, args.template)
    client = AzureDevOpsClient(args.project_url, pat or "dry-run")
    _normalize_tree_paths(drafts, client.project.project)
    out = _resolve_output_dir(args, client.project)
    out.mkdir(parents=True, exist_ok=True)
    _write_output_context(out, client.project, args)
    id_map_path = Path(args.id_map) if args.id_map else out / "ado-id-map.csv"
    id_map = _read_id_map(id_map_path)
    if not id_map:
        raise SystemExit(f"No imported work item IDs found in: {id_map_path}")

    candidates = [
        draft
        for draft in drafts
        if draft.key in id_map and draft.parent_key and draft.parent_key in id_map
    ]
    _progress(f"Found {len(candidates)} already-created work item(s) with known parent IDs.")

    report_rows: list[dict[str, Any]] = []
    for index, draft in enumerate(candidates, start=1):
        child_id = id_map[draft.key]
        expected_parent_id = id_map[draft.parent_key or ""]
        status = "planned"
        message = ""
        if args.dry_run:
            status = "would_check_or_link"
        else:
            current_parent_id = client.get_parent_id(child_id)
            if current_parent_id == expected_parent_id:
                status = "already_linked"
            elif current_parent_id is not None:
                status = "conflict_existing_parent"
                message = f"Existing parent {current_parent_id}; expected {expected_parent_id}"
            else:
                client.add_parent_link(child_id, expected_parent_id)
                status = "linked"
        report_rows.append(
            {
                "Key": draft.key,
                "ADO ID": child_id,
                "Parent Key": draft.parent_key or "",
                "Parent ADO ID": expected_parent_id,
                "Work Item Type": draft.work_item_type,
                "Title": draft.title,
                "Source File": draft.source_file,
                "Source Row": draft.source_row,
                "Status": status,
                "Message": message,
            }
        )
        if index % 100 == 0 or index == len(candidates):
            _progress(f"Backfill progress: {index}/{len(candidates)} checked.")

    report_path = out / ("backfill-links-dry-run.csv" if args.dry_run else "backfill-links-report.csv")
    _write_backfill_report(report_path, report_rows)
    counts: dict[str, int] = {}
    for row in report_rows:
        counts[row["Status"]] = counts.get(row["Status"], 0) + 1
    _progress("Backfill summary: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    _progress(f"Wrote {report_path}")
    return 2 if counts.get("conflict_existing_parent") else 0


def _filter_create_mode_drafts(drafts: list[WorkItemDraft], include_deprecated_deleted: bool) -> tuple[list[WorkItemDraft], list[WorkItemDraft]]:
    if include_deprecated_deleted:
        return drafts, []
    excluded_keys: set[str] = set()
    for draft in drafts:
        if _is_deprecated_or_deleted(draft):
            excluded_keys.add(draft.key)
    changed = True
    while changed:
        changed = False
        for draft in drafts:
            if draft.key in excluded_keys:
                continue
            if draft.parent_key in excluded_keys:
                excluded_keys.add(draft.key)
                changed = True
    kept = [draft for draft in drafts if draft.key not in excluded_keys]
    skipped = [draft for draft in drafts if draft.key in excluded_keys]
    return kept, skipped


def _is_deprecated_or_deleted(draft: WorkItemDraft) -> bool:
    status = str(draft.fields.get("MSBPC.catalogstatus") or "")
    normalized = status.lower()
    return "deprecated" in normalized or "deleted" in normalized


def _import_drafts(
    args: argparse.Namespace,
    drafts: list[WorkItemDraft],
    id_map: dict[str, int],
    id_map_path: Path,
    valid_fields: set[str],
    valid_wits: set[str],
    reporter: "ProgressReporter",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    workers = max(1, int(args.parallel_workers or 1))
    if workers == 1:
        return _import_drafts_serial(args, drafts, id_map, id_map_path, valid_fields, valid_wits, reporter)
    return _import_drafts_parallel(args, drafts, id_map, id_map_path, valid_fields, valid_wits, reporter, workers)


def _import_drafts_serial(
    args: argparse.Namespace,
    drafts: list[WorkItemDraft],
    id_map: dict[str, int],
    id_map_path: Path,
    valid_fields: set[str],
    valid_wits: set[str],
    reporter: "ProgressReporter",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    client = AzureDevOpsClient(args.project_url, "dry-run" if args.dry_run else args._resolved_pat)
    failures: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    next_dry_run_id = 1000000
    for index, draft in enumerate(drafts, start=1):
        if draft.key in id_map:
            reporter.maybe_report(index, len(id_map), "skipping previously imported rows")
            continue
        prepared = _prepare_fields(draft, valid_fields, valid_wits, args.skip_unknown_fields)
        if isinstance(prepared, str):
            failures.append(_failure(draft, prepared))
            if not args.continue_on_error:
                break
            continue
        parent_id = id_map.get(draft.parent_key or "")
        try:
            result = _create_draft(client, args, draft, prepared, parent_id)
            if args.dry_run:
                result["dryRunSyntheticId"] = next_dry_run_id
                result["id"] = next_dry_run_id
                next_dry_run_id += 1
                payloads.append({"key": draft.key, "payload": result})
            id_map[draft.key] = int(result["id"])
            if not args.dry_run:
                _append_id_map(id_map_path, draft, int(result["id"]))
            _print_create_result(args, draft, result)
            reporter.maybe_report(index, len(id_map), _activity_for_result(result))
        except Exception as exc:
            failures.append(_failure(draft, str(exc)))
            if not args.continue_on_error:
                break
    return failures, payloads


def _import_drafts_parallel(
    args: argparse.Namespace,
    drafts: list[WorkItemDraft],
    id_map: dict[str, int],
    id_map_path: Path,
    valid_fields: set[str],
    valid_wits: set[str],
    reporter: "ProgressReporter",
    workers: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _progress(f"Using parent-aware parallel import with {workers} worker(s).")
    pending = {draft.key: draft for draft in drafts if draft.key not in id_map}
    in_flight: dict[concurrent.futures.Future, WorkItemDraft] = {}
    id_lock = threading.Lock()
    failures: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    next_dry_run_id = 1000000
    sequence_by_key = {draft.key: index for index, draft in enumerate(drafts, start=1)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        while pending or in_flight:
            submitted = 0
            for draft in _ready_drafts(pending, id_map, workers - len(in_flight)):
                prepared = _prepare_fields(draft, valid_fields, valid_wits, args.skip_unknown_fields)
                if isinstance(prepared, str):
                    failures.append(_failure(draft, prepared))
                    del pending[draft.key]
                    if not args.continue_on_error:
                        break
                    continue
                parent_id = id_map.get(draft.parent_key or "")
                future = executor.submit(_parallel_create_worker, args, draft, prepared, parent_id)
                in_flight[future] = draft
                del pending[draft.key]
                submitted += 1
            if failures and not args.continue_on_error:
                for future in in_flight:
                    future.cancel()
                break
            if not in_flight:
                if pending:
                    for draft in list(pending.values())[:20]:
                        failures.append(_failure(draft, f"Parent not imported: {draft.parent_key}"))
                    pending.clear()
                break
            done, _ = concurrent.futures.wait(in_flight, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                draft = in_flight.pop(future)
                try:
                    result = future.result()
                    with id_lock:
                        if args.dry_run:
                            result["dryRunSyntheticId"] = next_dry_run_id
                            result["id"] = next_dry_run_id
                            next_dry_run_id += 1
                            payloads.append({"key": draft.key, "payload": result})
                        id_map[draft.key] = int(result["id"])
                        if not args.dry_run:
                            _append_id_map(id_map_path, draft, int(result["id"]))
                    _print_create_result(args, draft, result)
                    reporter.maybe_report(sequence_by_key[draft.key], len(id_map), _activity_for_result(result))
                except Exception as exc:
                    failures.append(_failure(draft, str(exc)))
                    if not args.continue_on_error:
                        for pending_future in in_flight:
                            pending_future.cancel()
                        pending.clear()
                        break
    return failures, payloads


def _ready_drafts(pending: dict[str, WorkItemDraft], id_map: dict[str, int], limit: int) -> list[WorkItemDraft]:
    if limit <= 0:
        return []
    ready = [
        draft
        for draft in pending.values()
        if not draft.parent_key or draft.parent_key in id_map
    ]
    ready.sort(key=lambda draft: (draft.source_file, draft.source_row, draft.key))
    return ready[:limit]


def _prepare_fields(
    draft: WorkItemDraft,
    valid_fields: set[str],
    valid_wits: set[str],
    skip_unknown_fields: bool,
) -> dict[str, Any] | str:
    fields = dict(draft.fields)
    if valid_fields:
        unknown = sorted(ref for ref in fields if ref not in valid_fields)
        if unknown and not skip_unknown_fields:
            return f"Unknown target fields: {', '.join(unknown)}"
        for ref in unknown:
            fields.pop(ref, None)
    if valid_wits and draft.work_item_type not in valid_wits:
        return f"Missing target work item type: {draft.work_item_type}"
    return fields


def _parallel_create_worker(args: argparse.Namespace, draft: WorkItemDraft, fields: dict[str, Any], parent_id: int | None) -> dict[str, Any]:
    client = _thread_client(args.project_url, "dry-run" if args.dry_run else args._resolved_pat)
    return _create_draft(client, args, draft, fields, parent_id)


_thread_local = threading.local()


def _thread_client(project_url: str, pat: str) -> AzureDevOpsClient:
    client = getattr(_thread_local, "client", None)
    key = (project_url, pat)
    if client is None or getattr(_thread_local, "key", None) != key:
        client = AzureDevOpsClient(project_url, pat)
        _thread_local.client = client
        _thread_local.key = key
    return client


def _create_draft(
    client: AzureDevOpsClient,
    args: argparse.Namespace,
    draft: WorkItemDraft,
    fields: dict[str, Any],
    parent_id: int | None,
) -> dict[str, Any]:
    work_item_type = _target_work_item_type(args, draft.work_item_type)
    try:
        return client.create_work_item(
            work_item_type,
            fields,
            parent_id,
            args.dry_run,
            max_retries=args.max_retries,
            retry_delay_seconds=args.retry_delay_seconds,
            recovery_field=args.recovery_field,
        )
    except RuntimeError as exc:
        if not _is_invalid_state_create_error(exc) or "System.State" not in fields:
            raise
        desired_state = fields["System.State"]
        create_fields = dict(fields)
        create_fields.pop("System.State", None)
        result = client.create_work_item(
            work_item_type,
            create_fields,
            parent_id,
            args.dry_run,
            max_retries=args.max_retries,
            retry_delay_seconds=args.retry_delay_seconds,
            recovery_field=args.recovery_field,
        )
        work_item_id = result.get("id")
        if not args.dry_run and work_item_id:
            try:
                client.update_work_item_fields(int(work_item_id), {"System.State": desired_state})
                result["stateUpdatedAfterCreate"] = desired_state
            except RuntimeError as update_exc:
                result["stateUpdateWarning"] = str(update_exc)
        return result


def _print_create_result(args: argparse.Namespace, draft: WorkItemDraft, result: dict[str, Any]) -> None:
    if not args.print_created_items:
        return
    if args.dry_run:
        action = "Planned"
    else:
        action = "Recovered existing" if result.get("recovered") else "Created"
    print(f"{action} {draft.work_item_type} {result['id']}: {draft.title}")


def _target_work_item_type(args: argparse.Namespace, work_item_type: str) -> str:
    refs = getattr(args, "_work_item_type_refs", {})
    return refs.get(_work_item_type_key(work_item_type), work_item_type)


def _work_item_type_key(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _is_invalid_state_create_error(exc: RuntimeError) -> bool:
    text = str(exc)
    return "System.State" in text and "not in the list of supported values" in text


def _activity_for_result(result: dict[str, Any]) -> str:
    if result.get("recovered"):
        return f"recovered ADO ID {result['id']}"
    return f"latest ADO ID {result['id']}"


def _get_pat(env_name: str, dry_run: bool) -> str:
    if dry_run:
        return "dry-run"
    pat = os.environ.get(env_name)
    if pat:
        _progress(f"Using PAT from {env_name}.")
        return pat
    print(f"{env_name} is not set. Paste an Azure DevOps PAT with Work Items: Read & write permission.")
    pat = getpass.getpass("Azure DevOps PAT: ").strip()
    if not pat:
        raise SystemExit("Azure DevOps PAT is required for import.")
    _progress("PAT received. Starting import workflow...")
    return pat


def _progress(message: str) -> None:
    print(f"[bpc-ado-import] {message}", flush=True)


def _resolve_output_dir(args: argparse.Namespace, project: Any) -> Path:
    base = Path(args.output)
    if getattr(args, "disable_project_output_scope", False):
        return base
    return base / _project_slug(project)


def _project_slug(project: Any) -> str:
    org = str(project.organization_url).rstrip("/").split("/")[-1]
    return _safe_path_part(f"{org}_{project.project}")


def _safe_path_part(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return slug.strip("._-") or "ado-project"


def _write_output_context(out: Path, project: Any, args: argparse.Namespace | None = None) -> None:
    context_path = out / "import-context.json"
    context = {
        "organizationUrl": project.organization_url,
        "project": project.project,
        "outputFolder": str(out),
    }
    if args is not None:
        context["parallelWorkers"] = int(getattr(args, "parallel_workers", 0) or 0)
        context["progressIntervalSeconds"] = int(getattr(args, "progress_interval_seconds", 0) or 0)
        context["maxRetries"] = int(getattr(args, "max_retries", 0) or 0)
        context["retryDelaySeconds"] = float(getattr(args, "retry_delay_seconds", 0) or 0)
    if context_path.exists():
        existing = json.loads(context_path.read_text(encoding="utf-8"))
        if existing.get("organizationUrl") != context["organizationUrl"] or existing.get("project") != context["project"]:
            raise SystemExit(
                "Output folder belongs to a different Azure DevOps project. "
                f"Existing={existing.get('organizationUrl')}/{existing.get('project')} "
                f"Requested={context['organizationUrl']}/{context['project']}"
            )
    context_path.write_text(json.dumps(context, indent=2), encoding="utf-8")


class ProgressReporter:
    def __init__(self, total: int, initial_created: int, interval_seconds: int) -> None:
        self.total = total
        self.start = time.monotonic()
        self.last_report = self.start
        self.initial_created = initial_created
        self.interval_seconds = max(1, interval_seconds)

    def maybe_report(self, checked: int, created_or_recorded: int, activity: str) -> None:
        now = time.monotonic()
        if now - self.last_report >= self.interval_seconds or checked == self.total:
            self.last_report = now
            self.report(checked, created_or_recorded, activity)

    def report(self, checked: int, created_or_recorded: int, activity: str) -> None:
        elapsed = max(0.001, time.monotonic() - self.start)
        created_this_run = max(0, created_or_recorded - self.initial_created)
        rate = created_this_run / (elapsed / 60)
        remaining = max(0, self.total - checked)
        pct = checked / self.total * 100 if self.total else 100
        _progress(
            f"Progress: {checked}/{self.total} checked ({pct:.1f}%); "
            f"{created_or_recorded} created or recorded; "
            f"{created_this_run} created this run; "
            f"{rate:.1f}/min; {remaining} remaining; {activity}."
        )


def _normalize_tree_paths(drafts: list[WorkItemDraft], project_name: str) -> None:
    for draft in drafts:
        for ref in ("System.AreaPath", "System.IterationPath"):
            value = draft.fields.get(ref)
            if isinstance(value, str):
                draft.fields[ref] = _normalize_tree_path(value, project_name)


def _normalize_tree_path(value: str, project_name: str) -> str:
    placeholders = ("Your Project Name Here", "Project name", "Project Name")
    for placeholder in placeholders:
        if value == placeholder:
            return project_name
        prefix = placeholder + "\\"
        if value.startswith(prefix):
            return project_name + value[len(placeholder) :]
    return value


def _ensure_classification_nodes(client: AzureDevOpsClient, drafts: list[WorkItemDraft]) -> None:
    area_paths = sorted({v for d in drafts for k, v in d.fields.items() if k == "System.AreaPath" and isinstance(v, str)})
    iteration_paths = sorted({v for d in drafts for k, v in d.fields.items() if k == "System.IterationPath" and isinstance(v, str)})
    _progress(f"Checking {len(area_paths)} Area Path node(s).")
    for index, path in enumerate(area_paths, start=1):
        client.ensure_classification_path("areas", path)
        if index % 25 == 0 or index == len(area_paths):
            _progress(f"Area Path progress: {index}/{len(area_paths)}")
    _progress(f"Checking {len(iteration_paths)} Iteration Path node(s).")
    for index, path in enumerate(iteration_paths, start=1):
        client.ensure_classification_path("iterations", path)
        if index % 25 == 0 or index == len(iteration_paths):
            _progress(f"Iteration Path progress: {index}/{len(iteration_paths)}")


def _load_drafts(source: str, template: str | None) -> list[WorkItemDraft]:
    source_path = _require_existing_path(source, "Source folder")
    template_path = _require_existing_path(template, "Template workbook") if template else None
    mapping = load_template(str(template_path) if template_path else None)
    files = find_source_files(str(source_path))
    if not files:
        raise SystemExit(f"No source .xlsx, .xlsm, .csv, or .tsv files found in: {source_path}")
    rows = []
    for file in files:
        rows.extend(load_rows(file))
    return build_drafts(rows, mapping)


def _remove_stale_outputs(out: Path) -> None:
    for name in ("import-failures.json", "dry-run-payloads.json"):
        path = out / name
        if path.exists():
            path.unlink()


def _require_existing_path(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.exists():
        raise SystemExit(f"{label} was not found: {path}")
    return path


def _write_plan(path: Path, drafts: list[WorkItemDraft]) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "key": d.key,
                    "parentKey": d.parent_key,
                    "aliases": sorted(d.aliases),
                    "workItemType": d.work_item_type,
                    "title": d.title,
                    "sourceFile": d.source_file,
                    "sourceRow": d.source_row,
                    "warnings": d.warnings,
                    "fields": d.fields,
                }
                for d in drafts
            ],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_preview_csv(path: Path, drafts: list[WorkItemDraft]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Key", "Parent Key", "ADO ID", "Parent ADO ID", "Work Item Type", "Title", "Source File", "Source Row"],
        )
        writer.writeheader()
        for d in drafts:
            writer.writerow(
                {
                    "Key": d.key,
                    "Parent Key": d.parent_key or "",
                    "ADO ID": "",
                    "Parent ADO ID": "",
                    "Work Item Type": d.work_item_type,
                    "Title": d.title,
                    "Source File": d.source_file,
                    "Source Row": d.source_row,
                }
            )


def _write_issues_csv(path: Path, drafts: list[WorkItemDraft]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Key", "Work Item Type", "Title", "Warning"])
        writer.writeheader()
        for d in drafts:
            for warning in d.warnings:
                writer.writerow({"Key": d.key, "Work Item Type": d.work_item_type, "Title": d.title, "Warning": warning})


def _write_backfill_report(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "Key",
        "ADO ID",
        "Parent Key",
        "Parent ADO ID",
        "Work Item Type",
        "Title",
        "Source File",
        "Source Row",
        "Status",
        "Message",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_skipped_csv(path: Path, drafts: list[WorkItemDraft]) -> None:
    fieldnames = ["Key", "Parent Key", "Work Item Type", "Title", "Source File", "Source Row", "Catalog Status"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for draft in drafts:
            writer.writerow(
                {
                    "Key": draft.key,
                    "Parent Key": draft.parent_key or "",
                    "Work Item Type": draft.work_item_type,
                    "Title": draft.title,
                    "Source File": draft.source_file,
                    "Source Row": draft.source_row,
                    "Catalog Status": draft.fields.get("MSBPC.catalogstatus", ""),
                }
            )


def _read_id_map(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["Key"]: int(row["ADO ID"]) for row in csv.DictReader(handle) if row.get("ADO ID")}


def _append_id_map(path: Path, draft: WorkItemDraft, ado_id: int) -> None:
    exists = path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Key", "ADO ID", "Work Item Type", "Title", "Source File", "Source Row"])
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "Key": draft.key,
                "ADO ID": ado_id,
                "Work Item Type": draft.work_item_type,
                "Title": draft.title,
                "Source File": draft.source_file,
                "Source Row": draft.source_row,
            }
        )


def _failure(draft: WorkItemDraft, message: str) -> dict[str, Any]:
    return {
        "key": draft.key,
        "workItemType": draft.work_item_type,
        "title": draft.title,
        "sourceFile": draft.source_file,
        "sourceRow": draft.source_row,
        "message": message,
    }


if __name__ == "__main__":
    raise SystemExit(main())
