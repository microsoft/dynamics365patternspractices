from __future__ import annotations

import html
import os
import re
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from .excel_ir import build_ir, find_template_workbook
from .fs_browser import list_directory, list_roots
from .jobs import (
    ApplyInProgressError,
    active_job_count,
    cancel_job,
    create_job,
    get_job,
    run_dry_run,
)
from .models import DryRunRequest, DryRunResponse, JobCreateRequest, JobStatusResponse
from .paths import bpc_files_root, output_root, resolve_release_folder
from .run_outcome import OUTPUT_FILES

app = FastAPI(
    title="BPC Runner",
    description="Local Excel→IR→plan→apply engine for BPCTool (no external Python scripts)",
    version="0.2.0",
)

# No CORS: the UI reaches the runner through the Vite /api proxy, so web pages on other
# origins cannot read runner responses. The Host check blocks DNS-rebinding pages.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

def _discover_template(release_folder: Path | None) -> Path | None:
    env = (os.environ.get("BPCTOOL_TEMPLATE") or "").strip()
    if env:
        path = Path(env).expanduser()
        return path if path.is_file() else None
    return find_template_workbook(release_folder) if release_folder else None


@app.get("/health")
def health() -> dict[str, str | int]:
    # Include writer fingerprints so the UI/logs can detect a stale runner.
    writers = Path(__file__).resolve().parent / "writers"
    def _mtime(name: str) -> str:
        path = writers / name
        return str(int(path.stat().st_mtime)) if path.exists() else "missing"

    return {
        "status": "ok",
        "teams_writer_mtime": _mtime("teams.py"),
        "backlog_writer_mtime": _mtime("backlog.py"),
        "active_jobs": active_job_count(),
    }


@app.get("/defaults")
def defaults() -> dict[str, str | None]:
    root = bpc_files_root()
    release = resolve_release_folder(root)
    template = _discover_template(release)
    return {
        "excel_file": str(template) if template else None,
        "catalog_source_dir": str(release) if release else None,
        "release_label": release.name if release and release != root else None,
        "bpc_files_root": str(root),
        "bpc_files_root_exists": "yes" if root.is_dir() else "no",
        "output_root": str(output_root()),
    }


@app.get("/fs/roots")
def fs_roots() -> dict:
    return {"roots": list_roots()}


@app.get("/fs/list")
def fs_list(
    path: str | None = Query(default=None),
    directories_only: bool = Query(default=False),
) -> dict:
    try:
        return list_directory(path, directories_only=directories_only)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/plan/dry-run", response_model=DryRunResponse)
def dry_run(request: DryRunRequest) -> DryRunResponse:
    try:
        return run_dry_run(request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/ir/parse")
def parse_ir(request: DryRunRequest) -> dict:
    try:
        return build_ir(
            request.excel_file,
            catalog_source_dir=request.catalog_source_dir,
            workbook_version=request.workbook_version,
            process_name=request.process_name,
            project_name=request.project_name,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


_OUTPUT_LINK_RE = re.compile(
    r'href="(' + "|".join(re.escape(name) for name in OUTPUT_FILES) + r')"'
)


@app.get("/outputs/{folder}/{name}")
def output_file(
    folder: str,
    name: str,
    root: Annotated[str | None, Query(description="Run output folder chosen in the UI")] = None,
) -> FileResponse:
    """Serve a known run output (report, failures, data checks) from the output root."""
    if name not in OUTPUT_FILES or "/" in folder or "\\" in folder or folder.startswith("."):
        raise HTTPException(status_code=404, detail="Unknown output file")
    custom = Path(root).expanduser() if (root or "").strip() else None
    if custom is not None and not custom.is_absolute():
        raise HTTPException(status_code=400, detail="root must be an absolute path")
    base = (custom or output_root()).resolve()
    path = (base / folder / name).resolve()
    if path.parent.parent != base or not path.is_file():
        raise HTTPException(status_code=404, detail=f"{name} has not been written yet")
    if name.endswith(".html"):
        if custom is None:
            return FileResponse(path, media_type="text/html; charset=utf-8")
        # Relative links to sibling outputs would lose ?root= and hit the default folder.
        suffix = html.escape(f"?root={quote(str(custom))}")
        page = _OUTPUT_LINK_RE.sub(
            lambda match: f'href="{match.group(1)}{suffix}"',
            path.read_text(encoding="utf-8"),
        )
        return HTMLResponse(page)
    media = "text/csv; charset=utf-8" if name.endswith(".csv") else "application/json"
    return FileResponse(path, media_type=media, filename=f"{folder}-{name}")


@app.post("/jobs", response_model=JobStatusResponse)
def post_job(request: JobCreateRequest) -> JobStatusResponse:
    try:
        return create_job(request)
    except ApplyInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def job_status(
    job_id: str,
    since: int = Query(0, ge=0, description="Return events from this index onward"),
) -> JobStatusResponse:
    try:
        return get_job(job_id, since=since)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}") from exc


@app.post("/jobs/{job_id}/cancel", response_model=JobStatusResponse)
def job_cancel(job_id: str) -> JobStatusResponse:
    try:
        return cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}") from exc
