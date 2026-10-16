"""Catalog import runtime: resume id-map, parent-aware parallel create, backfill."""

from __future__ import annotations

import csv
import heapq
import threading
import time
from collections import defaultdict
from concurrent.futures import (
    FIRST_COMPLETED,
    CancelledError,
    Future,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from pathlib import Path
from typing import Any, Callable

from .ado_client import AdoClient, AdoError
from .catalog_import import WorkItemDraft

Emit = Callable[[str, str], None]
Progress = Callable[[dict[str, Any]], None]
ShouldCancel = Callable[[], bool]

ID_MAP_FIELDS = [
    "Key",
    "WorkItemId",
    "WorkItemType",
    "Title",
    "ParentKey",
    "ParentId",
]

# Field set on every draft (defaults to the row key) and used to find a work
# item whose create outcome is unknown.
RECONCILE_FIELD_REF = "MSBPC.microsoftid"
RECONCILE_DELAY_S = 2.0
PROGRESS_INTERVAL_S = 1.0
TEXT_PROGRESS_EVERY = 500

BACKFILL_REPORT_FIELDS = [
    "Key",
    "Parent Key",
    "ADO ID",
    "Parent ADO ID",
    "Work Item Type",
    "Title",
    "Status",
    "Message",
]


def clamp_parallel_workers(value: int | None, *, default: int = 4) -> int:
    try:
        workers = int(value) if value is not None else default
    except (TypeError, ValueError):
        workers = default
    return max(1, min(workers, 16))


def _never_cancel() -> bool:
    return False


def _read_id_map_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_id_map(path: Path) -> dict[str, int]:
    """Load Key → ADO work item id from ado-id-map.csv (resume)."""
    mapping: dict[str, int] = {}
    for row in _read_id_map_rows(path):
        key = str(row.get("Key") or "").strip()
        raw_id = str(row.get("WorkItemId") or "").strip()
        if not key or not raw_id:
            continue
        try:
            mapping[key] = int(raw_id)
        except ValueError:
            continue
    return mapping


def load_id_map_parents(path: Path) -> dict[str, int]:
    """Key → ParentId for rows created with the parent relation in the payload."""
    parents: dict[str, int] = {}
    for row in _read_id_map_rows(path):
        key = str(row.get("Key") or "").strip()
        raw_parent = str(row.get("ParentId") or "").strip()
        if not key or not raw_parent:
            continue
        try:
            parents[key] = int(raw_parent)
        except ValueError:
            continue
    return parents


def open_id_map_for_append(path: Path) -> tuple[Any, csv.DictWriter]:
    """Open id-map CSV for append, writing header only when creating a new file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.is_file() or path.stat().st_size == 0
    handle = path.open("a", encoding="utf-8", newline="")
    writer = csv.DictWriter(handle, fieldnames=ID_MAP_FIELDS)
    if write_header:
        writer.writeheader()
        handle.flush()
    return handle, writer


def append_id_map_row(
    writer: csv.DictWriter,
    handle: Any,
    draft: WorkItemDraft,
    work_item_id: int,
    parent_id: int | None,
    *,
    lock: threading.Lock | None = None,
) -> None:
    row = {
        "Key": draft.key,
        "WorkItemId": work_item_id,
        "WorkItemType": draft.work_item_type,
        "Title": draft.title,
        "ParentKey": draft.parent_key or "",
        "ParentId": parent_id or "",
    }

    def _write() -> None:
        writer.writerow(row)
        handle.flush()

    if lock is None:
        _write()
    else:
        with lock:
            _write()


def _draft_order(draft: WorkItemDraft) -> tuple[str, int, str]:
    return (draft.source_file, draft.source_row, draft.key)


class ReadyQueue:
    """Parent-aware scheduler: children become ready when their parent is created.

    Ready drafts pop in source order (file, row, key). Drafts whose parent
    never gets created stay in ``remaining()``.
    """

    def __init__(self, pending: dict[str, WorkItemDraft], id_map: dict[str, int]) -> None:
        self._pending = dict(pending)
        self._children: dict[str, list[str]] = defaultdict(list)
        self._heap: list[tuple[tuple[str, int, str], str]] = []
        for key, draft in self._pending.items():
            if not draft.parent_key or draft.parent_key in id_map:
                heapq.heappush(self._heap, (_draft_order(draft), key))
            else:
                self._children[draft.parent_key].append(key)

    def pop(self, limit: int) -> list[WorkItemDraft]:
        batch: list[WorkItemDraft] = []
        while self._heap and len(batch) < limit:
            _, key = heapq.heappop(self._heap)
            draft = self._pending.pop(key, None)
            if draft is not None:
                batch.append(draft)
        return batch

    def parent_created(self, key: str) -> None:
        for child_key in self._children.pop(key, []):
            draft = self._pending.get(child_key)
            if draft is not None:
                heapq.heappush(self._heap, (_draft_order(draft), child_key))

    def remaining(self) -> list[WorkItemDraft]:
        return sorted(self._pending.values(), key=_draft_order)


class _ProgressTracker:
    def __init__(
        self,
        *,
        phase: str,
        total: int,
        baseline: int,
        counts: dict[str, int],
        emit: Emit,
        progress: Progress | None,
        text_label: str,
    ) -> None:
        self.phase = phase
        self.total = total
        self.baseline = baseline
        self.done = baseline
        self.counts = counts
        self.emit = emit
        self.progress = progress
        self.text_label = text_label
        self.started = time.monotonic()
        self._last_sent = 0.0

    def advance(self) -> None:
        self.done += 1
        if self.done % TEXT_PROGRESS_EVERY == 0:
            summary = ", ".join(f"{k} {v}" for k, v in self.counts.items() if v)
            self.emit(
                "catalog",
                f"{self.text_label} {self.done}/{self.total}"
                + (f" ({summary})" if summary else "")
                + "...",
            )
        self.flush(force=False)

    def flush(self, *, force: bool = True) -> None:
        if self.progress is None:
            return
        now = time.monotonic()
        if not force and now - self._last_sent < PROGRESS_INTERVAL_S:
            return
        self._last_sent = now
        self.progress(
            {
                "phase": self.phase,
                "done": self.done,
                "total": self.total,
                "baseline": self.baseline,
                "elapsedMs": int((now - self.started) * 1000),
                **self.counts,
            }
        )


def import_drafts_parent_aware(
    client: AdoClient,
    drafts: list[WorkItemDraft],
    *,
    project: str,
    id_map: dict[str, int],
    id_map_path: Path,
    parallel_workers: int,
    emit: Emit,
    progress: Progress | None = None,
    should_cancel: ShouldCancel | None = None,
) -> tuple[dict[str, int], list[dict[str, Any]], dict[str, int]]:
    """
    Create drafts with resume + parent-aware parallelism.

    Returns (id_map, failures, stats) where stats has created/skipped/linked/failed/
    missing_parent (stuck without parent)/cancelled (not started before cancel)/
    reconciled (outcome-unknown creates resolved by lookup)/outcome_unknown.
    """
    cancel = should_cancel or _never_cancel
    workers = clamp_parallel_workers(parallel_workers)
    stats = {
        "created": 0,
        "skipped": 0,
        "linked": 0,
        "failed": 0,
        "missing_parent": 0,
        "cancelled": 0,
        "reconciled": 0,
        "outcome_unknown": 0,
    }
    failures: list[dict[str, Any]] = []

    already = [d for d in drafts if d.key in id_map]
    stats["skipped"] = len(already)
    if already:
        emit(
            "catalog",
            f"Resume: skipping {len(already)} work item(s) already in {id_map_path.name}",
        )

    pending = {d.key: d for d in drafts if d.key not in id_map}
    if not pending:
        emit("catalog", "Resume: nothing left to create")
        return id_map, failures, stats

    emit(
        "catalog",
        f"Creating {len(pending)} work item(s) with {workers} parent-aware worker(s)",
    )

    counts = {"created": 0, "skipped": stats["skipped"], "failed": 0}
    tracker = _ProgressTracker(
        phase="create",
        total=len(drafts),
        baseline=stats["skipped"],
        counts=counts,
        emit=emit,
        progress=progress,
        text_label="Imported",
    )
    tracker.flush()

    queue = ReadyQueue(pending, id_map)
    handle, writer = open_id_map_for_append(id_map_path)
    lock = threading.Lock()
    in_flight: dict[Future, WorkItemDraft] = {}
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            while True:
                if not cancel():
                    for draft in queue.pop(workers - len(in_flight)):
                        parent_id = id_map.get(draft.parent_key) if draft.parent_key else None
                        future = executor.submit(
                            _create_one, client, draft, project=project, parent_id=parent_id
                        )
                        in_flight[future] = draft
                if not in_flight:
                    break
                completed, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                for future in completed:
                    draft = in_flight.pop(future)
                    try:
                        work_item_id, linked_parent_id, reconciled = future.result()
                    except (AdoError, KeyError, TypeError, ValueError) as exc:
                        stats["failed"] += 1
                        if getattr(exc, "outcome_unknown", False):
                            stats["outcome_unknown"] += 1
                        failures.append(_failure(draft, str(exc)))
                    else:
                        id_map[draft.key] = work_item_id
                        append_id_map_row(
                            writer, handle, draft, work_item_id, linked_parent_id, lock=lock
                        )
                        stats["created"] += 1
                        if linked_parent_id is not None:
                            stats["linked"] += 1
                        if reconciled:
                            stats["reconciled"] += 1
                        queue.parent_created(draft.key)
                    counts["created"] = stats["created"]
                    counts["failed"] = stats["failed"]
                    tracker.advance()
    finally:
        handle.close()

    leftover = queue.remaining()
    cancelled_keys = _blocked_only_by_unstarted(leftover, id_map) if cancel() else set()
    for draft in leftover:
        if draft.key in cancelled_keys:
            stats["cancelled"] += 1
            continue
        stats["missing_parent"] += 1
        stats["failed"] += 1
        failures.append(_failure(draft, f"Parent not imported: {draft.parent_key}"))
    if stats["cancelled"]:
        emit(
            "catalog",
            f"Cancelled: {stats['cancelled']} work item(s) not started; "
            f"re-run resumes from {id_map_path.name}",
        )
    counts["failed"] = stats["failed"]
    tracker.flush()
    if stats["outcome_unknown"]:
        emit(
            "catalog",
            f"{stats['outcome_unknown']} create(s) had a network error with unknown outcome "
            "and could not be reconciled — check import-failures.csv before re-running.",
        )
    return id_map, failures, stats


def _blocked_only_by_unstarted(
    leftover: list[WorkItemDraft], id_map: dict[str, int]
) -> set[str]:
    """Keys whose ancestor chain reaches an imported item (or a root) via unstarted drafts.

    Those were stopped by cancel; the rest descend from a parent that failed or is missing.
    """
    remaining = {draft.key: draft for draft in leftover}
    result: set[str] = set()
    for draft in leftover:
        seen = {draft.key}
        parent = draft.parent_key
        while parent in remaining and parent not in seen:
            seen.add(parent)
            parent = remaining[parent].parent_key
        if not parent or parent in id_map:
            result.add(draft.key)
    return result


def _failure(draft: WorkItemDraft, error: str) -> dict[str, Any]:
    return {
        "key": draft.key,
        "workItemType": draft.work_item_type,
        "title": draft.title,
        "parentKey": draft.parent_key,
        "error": error,
        "sourceFile": draft.source_file,
        "sourceRow": draft.source_row,
    }


def _send_create(
    client: AdoClient, draft: WorkItemDraft, *, project: str, parent_id: int | None
) -> int:
    created = client.create_work_item(
        project,
        draft.work_item_type,
        draft.fields,
        parent_id=parent_id,
        dry_run=False,
        markdown_format_fields=draft.markdown_format_fields,
    )
    return int(created["id"])


def _create_one(
    client: AdoClient,
    draft: WorkItemDraft,
    *,
    project: str,
    parent_id: int | None,
) -> tuple[int, int | None, bool]:
    """Return (work item id, parent id linked in the create payload, reconciled)."""
    try:
        return _send_create(client, draft, project=project, parent_id=parent_id), parent_id, False
    except AdoError as exc:
        if not exc.outcome_unknown:
            raise
        original = exc

    # After an unknown-outcome create, record no ParentId so backfill verifies the link.
    existing = _find_existing_after_unknown_create(client, draft, project=project, original=original)
    if existing is not None:
        return existing, None, True
    return _send_create(client, draft, project=project, parent_id=parent_id), None, True


def _find_existing_after_unknown_create(
    client: AdoClient,
    draft: WorkItemDraft,
    *,
    project: str,
    original: AdoError,
) -> int | None:
    time.sleep(RECONCILE_DELAY_S)
    try:
        ids = client.find_work_item_ids(
            project,
            draft.work_item_type,
            title=draft.title,
            field_ref=RECONCILE_FIELD_REF,
            field_value=draft.fields.get(RECONCILE_FIELD_REF),
        )
    except AdoError as lookup_exc:
        raise AdoError(
            f"{original}; duplicate check failed ({lookup_exc}). "
            "Check Azure DevOps for this item before re-running.",
            outcome_unknown=True,
        ) from lookup_exc
    if not ids:
        return None
    if len(ids) == 1:
        return ids[0]
    raise AdoError(
        f"{original}; {len(ids)} matching work items already exist "
        f"({', '.join(str(i) for i in ids[:5])}). Remove duplicates, then add the "
        "correct id to ado-id-map.csv before re-running.",
        outcome_unknown=True,
    )


def _check_parent_link(
    client: AdoClient, project: str, child_id: int, expected_parent_id: int
) -> tuple[str, str]:
    try:
        current_parent_id = client.get_parent_id(project, child_id)
        if current_parent_id == expected_parent_id:
            return "already_linked", ""
        if current_parent_id is not None:
            return (
                "conflict_existing_parent",
                f"Existing parent {current_parent_id}; expected {expected_parent_id}",
            )
        client.add_parent_link(project, child_id, expected_parent_id)
        return "linked", ""
    except (AdoError, KeyError, TypeError, ValueError) as exc:
        return "failed", str(exc)


def backfill_parent_links(
    client: AdoClient,
    drafts: list[WorkItemDraft],
    id_map: dict[str, int],
    *,
    project: str,
    output_dir: Path,
    emit: Emit,
    recorded_parents: dict[str, int] | None = None,
    parallel_workers: int = 4,
    progress: Progress | None = None,
    should_cancel: ShouldCancel | None = None,
) -> dict[str, int]:
    """
    For created items with a known parent id, ensure Hierarchy-Reverse exists.

    Items whose id-map row records the expected ParentId were linked in the create
    payload and are reported ``already_linked`` without a GET. The rest are
    checked in parallel. Writes backfill-links-report.csv (reference-script compatible statuses).
    """
    cancel = should_cancel or _never_cancel
    recorded = recorded_parents or {}
    candidates = [
        draft
        for draft in drafts
        if draft.key in id_map and draft.parent_key and draft.parent_key in id_map
    ]
    counts = {
        "linked": 0,
        "already_linked": 0,
        "conflict_existing_parent": 0,
        "failed": 0,
        "candidates": len(candidates),
        "linked_at_create": 0,
        "checked": 0,
        "cancelled": 0,
    }
    if not candidates:
        emit("catalog", "Parent-link backfill: no candidates")
        return counts

    rows: list[dict[str, Any]] = []
    to_check: list[int] = []
    for draft in candidates:
        child_id = id_map[draft.key]
        expected_parent_id = id_map[draft.parent_key or ""]
        row = {
            "Key": draft.key,
            "Parent Key": draft.parent_key or "",
            "ADO ID": child_id,
            "Parent ADO ID": expected_parent_id,
            "Work Item Type": draft.work_item_type,
            "Title": draft.title,
            "Status": "planned",
            "Message": "",
        }
        if recorded.get(draft.key) == expected_parent_id:
            row["Status"] = "already_linked"
            row["Message"] = "Linked at create (ado-id-map.csv)"
            counts["already_linked"] += 1
            counts["linked_at_create"] += 1
        else:
            to_check.append(len(rows))
        rows.append(row)

    workers = clamp_parallel_workers(parallel_workers)
    emit(
        "catalog",
        f"Parent-link backfill: {counts['linked_at_create']} linked at create; "
        f"checking {len(to_check)} work item(s) with {workers} worker(s)…",
    )

    if to_check:
        tracker = _ProgressTracker(
            phase="backfill",
            total=len(to_check),
            baseline=0,
            counts={"linked": 0, "conflict": 0, "failed": 0},
            emit=emit,
            progress=progress,
            text_label="Parent-link backfill",
        )
        tracker.flush()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _check_parent_link,
                    client,
                    project,
                    int(rows[index]["ADO ID"]),
                    int(rows[index]["Parent ADO ID"]),
                ): index
                for index in to_check
            }
            cancelled = False
            for future in as_completed(futures):
                if not cancelled and cancel():
                    cancelled = True
                    for pending in futures:
                        pending.cancel()
                index = futures[future]
                try:
                    status, message = future.result()
                except CancelledError:
                    rows[index]["Message"] = "Not checked (run cancelled)"
                    counts["cancelled"] += 1
                    continue
                rows[index]["Status"] = status
                rows[index]["Message"] = message
                counts[status] += 1
                counts["checked"] += 1
                tracker.counts.update(
                    linked=counts["linked"],
                    conflict=counts["conflict_existing_parent"],
                    failed=counts["failed"],
                )
                tracker.advance()
        tracker.flush()

    report_path = output_dir / "backfill-links-report.csv"
    with report_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BACKFILL_REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    summary = ", ".join(
        f"{k}={v}"
        for k, v in sorted(counts.items())
        if k != "candidates" and v
    )
    emit(
        "catalog",
        f"Parent-link backfill finished: {summary or 'no changes'}; "
        f"wrote {report_path.name}",
    )
    return counts
