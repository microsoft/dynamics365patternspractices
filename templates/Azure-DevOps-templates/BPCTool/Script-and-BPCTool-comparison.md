# BPCTool workflow & reference-script comparison

Engine order from `STEP_ORDER` in `runner/app/planner.py`. ADO paths via runner writers + `ado_client.py` / `catalog_runtime.py`. Comparison vs the Microsoft Azure DevOps Python reference scripts (phases 1–6) and the process / template model they implement.

BPCTool does **not** spawn those scripts — it reimplements the intent with Excel → IR → plan → apply.

**Quarterly releases:** Microsoft refreshes the ADO template guideline, the catalog workbooks, and the reference scripts on a quarterly basis. BPCTool is not tied to one release: keep each release in its own folder (`~/BPC Files/<YYYY-Qn>/` with the template and catalog workbooks together — see USER_GUIDE §2 Folder layout); Load runner defaults selects the newest one and uses its name as **Workbook version**. Sheet names and the matrix / L1–L4 conventions below are what BPCTool expects; re-check them when a new release lands.

**Assessment date:** 2026-10-15. Covers orchestration, template matrix (`X` shown / `H` hidden), Catalog parallel/resume/backfill, incremental re-runs, and conflict handling vs reference Phase 5 / Scripts 1–6.

---

## Workflow diagram

```text
Multivalue preflight (extmgmt)
        │
        ▼
   process  →  layout  →  project  →  teams  →  backlog  →  catalog  →  report
   WITs/fields   pages     create     areas     behaviors   parallel+     local
   picklists     controls  / bind     assign    iterations  resume+       artifacts
                                                            backfill
```

| Step | Purpose |
|------|---------|
| **Preflight** | Require DevLabs Multivalue on the org (live process / layout / project only) |
| **process** | Inherited process, WITs, picklists, custom fields |
| **layout** | Pages, groups, controls (`HtmlFieldControl`, MultivalueContribution); `H` fields on the WIT with hidden controls |
| **project** | Create or bind project to process |
| **teams** | Teams + area paths (reference Script 3 semantics) |
| **backlog** | Backlog behaviors, WIT assignment, iterations, team settings (reference Script 4) |
| **catalog** | Import catalog workbooks: prevalidate → parent-aware parallel create → resume → parent-link backfill |
| **report** | Local HTML/JSON summary in the run output folder (also written at the end of every run) |

**Live apply only:** Multivalue preflight runs when process, layout, or project is selected and **Rehearsal only** is off (**Run selected flow (live)**). **Preview plan** (plan only) and **Rehearsal only** (`apply_dry_run`: writers run, no ADO client) skip ADO mutation (and the Multivalue UI gate). **Report** never calls ADO. Full, dependency-aware, and run-from-selected-step-onward runs enforce the sequence above; selected-step mode can run a single card alone.

Recommended hard sequence (planner): `process → layout → verify → project → teams → backlog → catalog → report`.

### Execution modes (UI)

| Mode | Role |
|------|------|
| **Runner** (default) | Live Excel → IR → plan → apply via local FastAPI (`/api/jobs`) |
| **API** | Live ADO **reads** only (`/ado-proxy`) — credential proof / inventory; not process/layout/catalog apply |
| **Simulate** | Local stubs for orchestration testing |

Catalog/report have no API-mode executor; setup apply is Runner-only.

---

## Template matrix: X vs H (current assessment)

On the **ADO template guideline** workbook, sheet **Work item types**, cells in the field-label grid (roughly `K2:FU44` in recent releases) mark which fields apply to each WIT.

| Flag | Reference Script 2 | BPCTool (`excel_ir` / layout) |
|------|---------------|-------------------------------|
| **X** | Applicable — add field to WIT and place layout control | Same — `applicable_field_labels`; a control hidden by an earlier `H` run is shown again |
| **H** | Ignored (not `"X"`) — no add / no layout bind | **Hidden** — `hidden_field_labels`: field added to the WIT (so values can be stored and imported) but no control is placed; an existing control (e.g. inherited system field) is set `visible: false` |
| empty / other | Skipped | Skipped |

The reference script only continues when `wit_field_flags.get(field_label) == "X"`; there is no path for `H`. In the guideline, `H` marks fields that belong on the type but should not show on the form. Typically these are **system effort/build fields** on inherited types (Completed Work, Activity, Original Estimate, Remaining Work, Integration Build, Stack rank, Estimate on Action item / Bug / Business task / Issue / Task / Test case), plus **Microsoft workshop type** on Workshop. The exact set varies by release; Preview plan reports `hidden_field_placements` for the workbook you load.

Hiding uses `PATCH …/layout/groups/{groupId}/controls/{fieldRef}` with `visible: false` (the Process API equivalent of "Hide from layout"). A hidden field that is **required** with no default value logs a warning, because users cannot fill it on the form. Catalog prevalidate treats `H` fields as on the WIT (required-field defaults apply).

**Verdict:** BPCTool extends the reference scripts — `H` is honoured as "on the type, hidden from the form" instead of being ignored.

**Process custom rules:** Neither the guideline sheets nor BPCTool apply WIT Process Rules (conditions/actions). Fields sheet **Required** / **Default value** drive layout + catalog defaults only. Post-apply MSBPC snapshots show Custom Rules → None. (Exporting source-org rules into a future Rules sheet is out of scope for current BPCTool.)

---

## Incremental re-runs & conflicts (current assessment)

Re-runs against an existing org/process/project are supported, but “incremental update” is **not** a full spreadsheet overwrite. Update policy gates **process** and **project** only; other steps are mostly create-if-missing / heal.

### Update policies (process / project)

| Policy | Behavior |
|--------|----------|
| **Require confirmation** | Fail plan/apply if process/project exists and confirm boxes are unchecked |
| **Always update** | Proceed; writers reuse/update existing targets (still create-if-missing, not full rewrite) |
| **Skip existing** | Skip process (and layout with it) and/or project (and teams/backlog with it) when targets exist |
| **Create only** | Fail if selected process/project already exists |

Catalog is **not** gated by update policy.

### Per-step re-run behavior

| Step | On subsequent run | Conflicts / collisions |
|------|-------------------|------------------------|
| **process** | Create missing WITs/picklists/fields; PATCH some field metadata; disable Excel-disabled WITs when possible | WIT create **409** → skip; org field re-PATCH may log non-fatal `MSBPC.*` 404 |
| **layout** | Add missing pages/groups/controls for `X` fields; add `H` fields to the WIT and hide their controls; re-show a control when `H` → `X` | Field/control **400/409** → treat as already present; does **not** remove controls for fields that became blank |
| **project** | Reuse existing; update description when UI description is non-empty | Does **not** re-bind process template on an existing project |
| **teams** | Create missing teams/areas; PATCH team area assignments | Team/area create **409** → exists |
| **backlog** | Rename/heal/create behaviors; assign WITs; create missing iterations; team settings | Duplicate custom levels healed (prefer system Agile); name already present → reuse |
| **catalog** | **Create-only fields** — keys in `ado-id-map.csv` **skipped** (no WIP field refresh); new keys created; then parent-link backfill | See backfill statuses below |
| **report** | Regenerates local HTML/JSON | N/A (no ADO) |

### Catalog parent-link conflict statuses

After create (and on re-run for mapped drafts), backfill writes `backfill-links-report.csv`:

| Status | Meaning |
|--------|---------|
| `linked` | Missing Hierarchy-Reverse added |
| `already_linked` | Expected parent already set |
| `conflict_existing_parent` | Different parent already exists — **not overwritten** |
| `failed` | API/other error |

If a parent never imports, children fail with `Parent not imported` (not created unlinked).

**Verdict vs reference Phase 5:** Same operational model (resume + Hierarchy-Reverse + conflict statuses). BPCTool runs backfill automatically after create; the reference scripts expose `backfill-links` as a CLI. Neither refreshes field values for keys already in the id map.

---

## Catalog Import (current assessment)

Aligned with reference Phase 5 on the operational import model; still create-only for **field** updates (no WIP upsert).

| Capability | Behavior |
|------------|----------|
| **Hierarchy** | Title 1..N outline (ADO CSV / BPC guidance). Only `System.LinkTypes.Hierarchy-Reverse` is created — same as the reference scripts (no Related / Predecessor / etc.) |
| **Parallelism** | Heap ready queue + children-by-parent index + ThreadPool (UI **Catalog workers** → `catalog_parallel_workers`, default 4, clamp 1–16). A child is queued when its parent is created |
| **Connections** | Per-thread keep-alive HTTP(S) connections in `ado_client` (no new TLS handshake per request) |
| **Create retries** | Only 429/503 rejections are retried. A network error after send triggers a WIQL lookup (type + title + `MSBPC.microsoftid`): adopt one match, retry once if none, fail as possible duplicate if several |
| **Resume** | Load existing `ado-id-map.csv`; skip keys already imported; append new rows |
| **Parent-link backfill** | Rows whose id-map `ParentId` matches were linked at create → `already_linked` with no GET. The rest: parallel `GET` relations + `PATCH` missing Hierarchy-Reverse. Writes `backfill-links-report.csv` (`linked` / `already_linked` / `conflict_existing_parent` / `failed`) |
| **Cancel / progress** | `POST /jobs/{id}/cancel` stops after in-flight creates (recorded in the id map), skips backfill; `catalog-progress` events drive a UI progress bar + ETA |
| **Failures** | If a parent never imports, children fail with `Parent not imported` (not created unlinked). `import-failures.csv` separates root causes from blocked children, explains each ADO error (TF401347, TF401324, invalid State, …) in plain language with a fix |
| **Prevalidate** | Local sanitize before create (`import-prevalidate.csv` / `.json`; also in Preview plan): `Your Project Name Here` → project name in Area / Iteration Path, Area Path and Iteration Path project-prefix rewrite, strip area paths not in the project (live: read from ADO), strip States the type doesn't allow (live: read from ADO; Test Case New always), shorten text over 255 chars, case-insensitive picklist normalize, required-field defaults, empty Description omitted (no synthetic placeholder) |
| **Not done** | WIT `$batch` / native CSV bulk upload; WIP field upsert against existing work items |

**Performance note:** Parallel workers cut wall time vs the former 1×N serial create loop (often several× when network-bound). Keep-alive connections and skipping backfill GETs for links made at create remove roughly one round-trip plus a TLS handshake per item. Start at 2–8 workers; higher counts risk ATCPU/429. Chunked WIT `$batch` would reduce round-trips further but is not implemented.

Key modules: `writers/catalog.py`, `catalog_runtime.py`, `ado_client.create_work_item` / `get_parent_id` / `add_parent_link`.

---

## Local runner APIs

Vite proxies `/api/*` → FastAPI on `127.0.0.1:8787`.

| Endpoint | Role |
|----------|------|
| `GET /health` | Liveness + writer mtimes |
| `GET /defaults` | Newest release folder under `BPCTOOL_CATALOG` / `~/BPC Files`, its template, release label, output root |
| `POST /plan/dry-run` | Excel → IR → plan (**Preview plan**) |
| `POST /jobs` | Start live apply or rehearsal (`apply_dry_run`, UI **Rehearsal only**) |
| `GET /jobs/{id}?since=N` | Poll step results + events from index N (incremental) |
| `POST /jobs/{id}/cancel` | Cooperative stop → status `cancelled` |
| `GET /outputs/{folder}/{file}?root=` | Serve a known run output (report, failures / data-check CSV) for the results card |
| `GET /fs/roots`, `GET /fs/list` | Path picker Browse… |
| `POST /ir/parse` | Full IR dump (manual; UI does not call) |

Job body fields: `catalog_parallel_workers` (1–16; UI **Catalog workers**); `output_root` (UI **Run output folder**); `update_policy` + confirm flags for process/project gates. The UI stores the active job id in `sessionStorage` and reattaches after a page reload.

Browser inventory reads use `/ado-proxy/{org}` → `dev.azure.com`. Extension check/install uses `/extmgmt-proxy/{org}` → `extmgmt.dev.azure.com`.

---

## Azure DevOps APIs per step

Hosts:

- `https://dev.azure.com/{org}` — Process, WIT, Project, Work
- `https://extmgmt.dev.azure.com/{org}` — Multivalue extension management

| Step | Runner entry | Primary REST surface |
|------|--------------|----------------------|
| **Preflight** | UI Connection / Run gate; `require_multivalue_extension` | `GET\|POST /_apis/extensionmanagement/installedextensionsbyname/ms-devlabs/vsts-extensions-multivalue-control` (`7.1-preview.1`) |
| **process** | `POST /api/jobs` → `apply_process` | `GET\|POST /_apis/work/processes` · WIT create/PATCH · `GET\|POST\|PUT /_apis/work/processes/lists` · `GET\|POST\|PATCH /_apis/wit/fields` |
| **layout** | `apply_layout` | GET layout · POST pages/groups/controls · POST `…/workItemTypes/{wit}/fields` · `PATCH …/layout/groups/{group}/controls/{field}` (`visible` for `H`) · MultivalueContribution / HtmlFieldControl |
| **project** | `apply_project` | GET processes · `GET\|POST /_apis/projects` · `PATCH /_apis/projects/{id}` (description) |
| **teams** | `apply_teams` (reference Script 3) | `GET\|POST …/projects/{id}/teams` · `GET\|POST` classificationnodes/Areas · `PATCH` teamsettings/teamfieldvalues |
| **backlog** | `apply_backlog` (reference Script 4) | Process behaviors (GET/PUT/POST/DELETE) · WIT↔behavior · Iterations nodes · `GET\|PATCH` teamsettings · team iterations |
| **catalog** | `apply_catalog` + prevalidate + `catalog_runtime` | Parallel `PATCH …/wit/workitems/$Type` (fields + optional Markdown format + optional Hierarchy-Reverse); resume via `ado-id-map.csv`; `POST …/wit/wiql` only to reconcile a create with unknown outcome; backfill `GET …?$expand=Relations` + `PATCH …/workitems/{id}` for parent links not recorded at create |
| **report** | `apply_report` | None — writes `bpc-ado-setup-summary.json` / `.html` under `<Run output folder>/<org>_<project>/` (also written automatically at the end of every live run; Rehearsal writes `rehearsal-summary.*`) |

Key sources: `runner/app/planner.py`, `apply_engine.py`, `ado_client.py`, `catalog_runtime.py`, `writers/*.py`.

---

## Phase ↔ step map

| Reference phase script | BPCTool engine step |
|-------------------|---------------------|
| `1_ADO_Creation_Script.py` (process half) | **process** |
| `2_ADO_Page_Layout_Script_Threaded.py` | **layout** |
| `1_ADO_Creation_Script.py` (project half) | **project** (only after layout) |
| `3_ADO_Teams_Areas_Script.py` | **teams** |
| `4_ADO_Backlog_Config_Script.py` | **backlog** |
| `5_BPC_Catalog_Import.py` (+ `bpc_ado_import`) | **catalog** |
| `6_Generate_HTML_Report.py` | **report** |

---

## Microsoft reference scripts vs BPCTool

| Area | Reference scripts | BPCTool | Verdict |
|------|--------------|---------|---------|
| **Orchestration** | `setup_wizard` shells out to six `.py` scripts via env vars (subprocess) | In-process writers in local FastAPI runner; React UI posts `/api/jobs` and polls events | Improved / ported |
| **Sequence** | Phase 1 creates process + project together; layout is a later phase | Hard gate **process → layout → project** (layout before any project on full runs) | Improved / ported |
| **Excel handling** | Each script re-reads Excel during mutation | Parse once to IR → plan → apply; fingerprint + Preview plan + rehearsal runs | Improved / ported |
| **WIT×field matrix (`X`/`H`)** | Script 2: only `X` adds field/layout; `H` ignored | `X` adds field + control; `H` adds field to the WIT and hides its control (`visible: false`) | Improved |
| **Process custom rules** | Not authored in guideline Excel; not applied by phase scripts | Same — no Rules sheet / no `…/rules` apply | Parity (gap vs full process) |
| **Multivalue extension** | Layout binds Multivalue; install often assumed / Marketplace-manual | **Required** for process/layout/project; Connection check + optional API install; Preview plan / rehearsal skip gate | Stricter |
| **Process / fields / picklists** | Script 1 creates inherited process, WITs, fields, picklists | Ported via `apply_process`; multi-select → suggested picklists (`isSuggested`); re-run create-if-missing + limited PATCH | Improved / ported |
| **Page layout** | Script 2 threaded layout + DevLabs MultivalueContribution | `apply_layout` mirrors Script 2; re-run adds missing controls (no stale remove) | Improved / ported |
| **Teams & areas** | Script 3 teams, L1–L4 areas, `set_team_area` | `apply_teams` — reference semantics; re-run upserts areas/assignments | Improved / ported |
| **Backlog & iterations** | Script 4 Parts 1–4: behaviors, WIT assign, defaults, team iterations | `apply_backlog` — rename/heal levels, WIT↔behavior, iterations, team settings | Improved / ported |
| **Incremental process/project** | Script re-runs with exist checks / warnings | Explicit update policies + confirm flags; writers still not full overwrite | Improved / ported |
| **Catalog hierarchy** | Parent-child Hierarchy-Reverse only | Same — Title 1..N; no other WIT relation types | Parity |
| **Catalog parallelism** | `--catalog-parallel-workers` parent-aware pool | UI **Catalog workers** / `catalog_parallel_workers` parent-aware ready queue; keep-alive connections | Improved / ported |
| **Create retry safety** | Retries via shared session helpers | Create never blindly retried; unknown outcomes reconciled by WIQL lookup before any retry | Improved |
| **Cancel / long runs** | Ctrl-C the script; rerun to resume | Runner cancel endpoint (cooperative, id map kept); progress bar + ETA; UI reattaches after reload | Improved |
| **Catalog resume** | Skip keys in `ado-id-map.csv` on rerun | Same append/skip resume model | Improved / ported |
| **Catalog parent backfill** | `backfill-links` CLI (`linked` / `already_linked` / `conflict_existing_parent` / `failed`) | Automatic parallel post-create backfill → same statuses; links recorded at create skip the GET; conflicts **not** force-reparented | Improved / ported |
| **Catalog prevalidate** | Phase 5 sanitizes / maps before create | Local prevalidate + case-insensitive picklist rewrite; empty Description omitted | Improved / ported |
| **Catalog field updates** | Create/import mode; limited recovery updates | Create-only fields (no WIP upsert); spreadsheet edits to mapped keys do not refresh ADO | Near parity / residual |
| **Report** | Script 6 HTML summary from artifacts | Plain-language HTML/JSON (headline, what needs attention, steps, files) written after every run, plus a UI results card (no ADO calls) | Improved |
| **UI execution modes** | N/A (CLI scripts) | Runner = apply; API = reads only; Simulate = stubs | Improved / ported |
| **Edge-case parity** | Full script surface + many ADO quirk workarounds | Template-shaped, not line-for-line; residual: system WIT disable fragility, field 404 on re-run, Deliverables picklist mismatches | Gap / residual |
| **Observability / UX** | Per-script console/files; limited structured UI | Job events, Run timing, plan preview with data checks, results card, Excel-ready failures / data-check CSVs with fixes, id-map / backfill artifacts | Improved |

### Known residual vs the reference scripts

- Not every reference-script quirk is ported (state recovery paths, deprecated/deleted cascade filters, print/recovery-field options, etc.).
- Catalog fields remain **create-only** (no bulk WIP upsert). Resume skips existing keys; it does not refresh field values.
- Parent-link `conflict_existing_parent` is reported only — no automatic re-parent.
- Existing projects are not re-bound to a different process template on re-run.
- Layout does not remove controls that are no longer marked `X` in Excel.
- No WIT Process Rules import/apply (the guideline also does not encode them).
- No WIT `$batch` or native Boards CSV bulk path yet.
- Backfill trusts `ParentId` recorded in `ado-id-map.csv`; a parent changed by hand in ADO after create is not re-checked for those rows.
- Cancel is cooperative; one long-running ADO request finishes before the job stops.
- Inherited system WIT disable can still fail in the Process API (manual ADO UI fallback).
- Re-run Process may log non-fatal `MSBPC.*` field 404s when org fields already exist (Update API is lock/undelete only).

See also: [USER_GUIDE.md](../USER_GUIDE.md) (§9 catalog, §10 re-runs, §17 limitations), [CHANGELOG.md](../CHANGELOG.md) (standalone replacement + residual risk), [reference/MSBPC-process-analysis.md](./reference/MSBPC-process-analysis.md) (post-create process snapshot).
