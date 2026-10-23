from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ENGINE_STEPS = ("process", "layout", "project", "teams", "backlog", "catalog", "report")


class DryRunRequest(BaseModel):
    org_url: str = Field(min_length=3)
    process_name: str = Field(min_length=3)
    project_name: str = Field(min_length=3)
    project_description: str = Field(
        default="",
        description="Optional Azure DevOps project description set on create/update",
    )
    excel_file: str = Field(min_length=3, description="Path to ADO template guideline .xlsx")
    catalog_source_dir: str | None = Field(
        default=None,
        description="Folder with BPC catalog source workbooks (phase 5 inputs)",
    )
    workbook_version: str = ""
    update_policy: Literal[
        "require-confirmation",
        "always-update",
        "skip-existing",
        "create-only",
    ] = "require-confirmation"
    confirm_process_update: bool = False
    confirm_project_update: bool = False
    known_process_exists: bool | None = None
    known_project_exists: bool | None = None
    root_area_path: str = ""
    pat: str | None = Field(
        default=None,
        description="PAT required for apply mode; never logged",
    )
    steps: list[str] | None = Field(
        default=None,
        description=(
            "Subset of engine steps to run (process, layout, project, teams, backlog, catalog, "
            "report); null runs every step. An empty list or an unknown step is rejected."
        ),
    )
    catalog_limit: int | None = Field(
        default=None,
        description="Optional cap on catalog drafts (useful for smoke applies)",
    )
    convert_markdown_to_html: bool = Field(
        default=False,
        description=(
            "Override: convert markdown-like large-text Excel "
            "content to HTML. Default false preserves markdown and sets "
            "multilineFieldsFormat=Markdown on create."
        ),
    )
    include_deprecated_deleted: bool = Field(
        default=False,
        description=(
            "Import catalog rows whose Catalog status is Deprecated or Deleted (and the rows "
            "below them). Default false skips them, as the Microsoft importer does."
        ),
    )
    output_root: str | None = Field(
        default=None,
        description=(
            "Folder that holds the <org>_<project> run output folders; "
            "empty uses BPCTOOL_OUTPUT_DIR or bpctool/runner-out"
        ),
    )
    catalog_parallel_workers: int = Field(
        default=4,
        ge=1,
        le=16,
        description=(
            "Parent-aware parallel workers for Catalog Import "
            "(UI Catalog workers control). Use 1 for serial."
        ),
    )

    @field_validator("steps")
    @classmethod
    def _known_steps(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        steps = [str(step).strip().lower() for step in value]
        if not steps:
            raise ValueError("steps must list at least one step; use null to run every step.")
        unknown = sorted({step for step in steps if step not in ENGINE_STEPS})
        if unknown:
            raise ValueError(
                f"Unknown step(s): {', '.join(unknown)}. Valid steps: {', '.join(ENGINE_STEPS)}."
            )
        return [step for step in ENGINE_STEPS if step in steps]

    @field_validator("output_root")
    @classmethod
    def _absolute_output_root(cls, value: str | None) -> str | None:
        text = (value or "").strip()
        if not text:
            return None
        if not Path(text).expanduser().is_absolute():
            raise ValueError("Run output folder must be an absolute path.")
        return text


class PlanAction(BaseModel):
    step_id: str
    action: Literal["create", "update", "skip", "verify", "import", "report"]
    entity_type: str
    entity_name: str
    detail: str
    count: int = 1


class DryRunResponse(BaseModel):
    ok: bool
    ir_version: str
    excel_file: str
    catalog_source_dir: str | None
    workbook_fingerprint: str
    summary: dict[str, Any]
    steps: list[dict[str, Any]]
    actions: list[PlanAction]
    errors: list[str] = []
    warnings: list[str] = []
    notices: list[str] = Field(
        default_factory=list,
        description="Informational lines, e.g. the project name substituted into workbook paths",
    )
    data_checks: dict[str, Any] | None = Field(
        default=None,
        description="Catalog data checks (needs review / fixed automatically) from Preview plan",
    )


class ApplyResult(BaseModel):
    ok: bool
    dry_run: bool
    plan: DryRunResponse | None = None
    step_results: dict[str, Any] = {}
    output_dir: str | None = None
    error: str | None = None
    cancelled: bool = False
    events: list[dict[str, Any]] = []
    duration_ms: int | None = None
    timings: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Per-step duration rows: stepId, durationMs, skipped",
    )
    run_id: str | None = None
    outcome: dict[str, Any] | None = Field(
        default=None,
        description="Plain-language results: headline, steps, attention items, output files",
    )


class JobCreateRequest(DryRunRequest):
    mode: Literal["dry-run", "apply"] = "dry-run"
    apply_dry_run: bool = Field(
        default=False,
        description="When mode=apply, run writers without ADO mutations (preview artifacts only)",
    )


class JobStatusResponse(BaseModel):
    id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    mode: str
    cancel_requested: bool = False
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    result: DryRunResponse | None = None
    apply_result: ApplyResult | None = None
    error: str | None = None
    events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Events from index event_offset onward (all when since=0)",
    )
    event_offset: int = 0
    event_total: int = 0
