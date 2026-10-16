# Changelog 

All notable changes to BPCTool (React UI + local runner) are documented here.

## 2026-10 — Run results a standard user can act on

- **Data checks before import** (Preview plan, Rehearsal only, live): Area Path project prefix rewritten to the target project (`MSBPCProj\…` → `<project>\…`); area paths not in the project stripped (TF401347; live runs read the project's area tree); States the type doesn't allow stripped (live runs read each type's states, e.g. `Deprecated`; state casing aligned and listed as an automatic fix); text over 255 characters in string/picklist fields and Title shortened to 254 + `…` (TF401324; multi-select keeps whole values). A removed picklist value is no longer reported again as "required field empty"
- **Preview plan** shows a **Catalog data checks** panel (counts, example file/row/value, how to fix) — `data_checks` on `POST /plan/dry-run`
- `import-prevalidate.json` splits **automaticFixes** vs **needsReview**; new **`import-prevalidate.csv`** lists every change (source file, row, value in spreadsheet, value used, how to fix; review rows first)
- New **`import-failures.csv`**: **Fix this row** vs **Blocked by parent**, plain-language problem + fix per ADO error type, value tried, source file + row, children blocked. `import-failures.json` is now `{runId, generatedAt, summary, failures}` (was a bare list)
- **Summary written after every run** (success, failure, cancel), not only when the Report step runs; steps not run this time keep their last result. Rehearsal writes `rehearsal-summary.*` instead of overwriting the live summary. All files share the job's `runId`
- **HTML report rewritten**: status banner + headline, What needs attention (largest first, with fixes and file links), Fixed automatically, step table, file list, run details; raw JSON tucked away
- **Results card** in the UI after each run: headline, Open report / Download failures / Download data checks, attention list, steps, **Set up Catalog Import re-run** (resumes from `ado-id-map.csv`). New `GET /outputs/{folder}/{file}` serves only known output files
- **Run output folder** in Run configuration (Browse…, Use default; remembered in the browser): results go to `<folder>/<org>_<project>/`. Empty = `BPCTOOL_OUTPUT_DIR`, else `runner-out`. API: `output_root` on job requests (absolute path); `GET /outputs/…?root=` serves files from it
- **`Your Project Name Here`** in area / iteration paths is replaced with the form's Project name — template Area paths, Iteration paths and Teams *Backlog iteration*, plus catalog **Area Path** / **Iteration Path**. Reported as a highlighted *Project name applied …* line (with counts) in Preview plan, the run log, the results card, and the HTML report; each value is in `import-prevalidate.csv`
- Catalog **Iteration Path** gets the same project-prefix fix as Area Path (catalog workbooks ship `MSBPCProj`, which a differently named project rejects); values are only re-prefixed, never removed
- Fix: TF401347 on **Iteration Path** was explained as an area-path problem in `import-failures.csv`; it now names the iteration path and its fix
- Fix: template placeholder count no longer double-counts an area row whose path and default segment both changed
- Data checks: a cell with several `;`-separated values in a field the template marks single-select (e.g. `Accounts payable; Warehouse management` in **Module**) is reported as *Several values in a field the template marks single-select*, with the fix (set **Multi-select field = Yes** in the template Fields sheet, re-run Process Template and Page Layout), instead of the misleading *Value is not in the picklist*
- Fix: catalog rows that repeat another row's **Process sequence ID** were silently dropped (31 rows in the July Business Process Catalog workbook), and their child rows were linked under the first row. Repeats now get their own tracking key in `ado-id-map.csv` (`<id>#<Microsoft ID>`; the first row keeps the plain ID so existing files still resume). The work item's Process sequence ID field is not changed, are imported on the next Catalog Import, and are listed under *Fixed automatically*. Preview plan's catalog row count now matches the number imported. Children already imported under the wrong parent are reported as `conflict_existing_parent` in `backfill-links-report.csv` and left unchanged
- Fix: links inside the HTML report (failures, data checks) opened from the results card now work with a custom **Run output folder**
- When a live run doesn't include Catalog Import but an earlier one left failures, the headline says the problems are from the earlier Catalog Import instead of reporting them as this run's result
- New run mode **Run from selected step onward**: runs the selected card and every later card, including completed ones (Process + Layout gate still applies)
- Durations of an hour or more show as `1h 55m`
- Removed wording that described BPCTool as part of a larger toolkit — it is a standalone app
- Tests: `test_failure_explain.py`, `test_run_outcome.py`, more `test_catalog_validate.py` cases
- **Docs rationalized:** one [`README.md`](../README.md) at the repo root covers the tool and its usage (requirements, launch, checklist, screenshots, folder layout, modes, results, documentation index, developer notes). Removed `bpctool/README.md`, `bpctool/docs/README.md`, and `bpctool/docs/reference/README.md`; their content is in the root README. Detailed docs stay in `USER_GUIDE.md`, `CHANGELOG.md`, and `docs/`
- **Docs refreshed for the current UI:** new infographic [`docs/images/bpctool-overview.svg`](docs/images/bpctool-overview.svg) (what you need, how you use it, what you get) at the top of the README and USER_GUIDE. All README screenshots retaken (dark mode, same width): the workflow shot shows the four run modes with **Run from selected step onward**, the run configuration shot shows the **Run output folder**, and new `ui-preview-plan.png` and `ui-results-card.png` show the *Project name applied* notice, catalog data checks, and the results card

## 2026-10 — Clearer run modes: Preview plan / Rehearsal only / live

- **Preview plan** (was “Preview plan (dry-run)”): builds the plan from the Excel only; no Azure DevOps calls.
- **Rehearsal only** (was “Apply dry-run”): runs every selected step without changing Azure DevOps and writes preview files. The run button reads **Rehearse selected flow**, with an amber note.
- **Live run**: the button reads **Run selected flow (live)** and is outlined red, with a note naming the target org / process / project.
- API names are unchanged (`POST /plan/dry-run`, `apply_dry_run`).
- Fix: an invalid or expired PAT (HTTP 203 sign-in page) no longer shows the Multivalue extension as “installed”; it now reports an authentication error.
- Dark-mode styling for the rehearsal checkbox box and run-mode notes; README screenshots retaken for consistency (dark mode, same width, illustrative `/Users/you/BPC Files/2026-Q4` paths): `ui-connection.png`, `ui-workflow.png`, `ui-run-config.png`, `ui-actions.png`, new `ui-actions-rehearsal.png`.

## 2026-10 — Folder layout: release folders, output root, `bpctool.env`

- **No hard-coded user paths.** Catalog root defaults to `~/BPC Files`; the UI catalog field starts empty and is filled from the runner
- **Release folders:** new `runner/app/paths.py`. When the root holds no workbooks itself, `/defaults` picks the newest release subfolder (`YYYY-Qn` names by name, otherwise newest workbook mtime; `_` / `.` folders ignored) and returns `release_label`, `bpc_files_root`, `output_root`. Flat layouts still work
- UI loads runner defaults once on page open without overwriting typed paths; release folder name pre-fills a blank **Workbook version**; Run configuration shows where run outputs go and why to keep them. Path picker adds a "Latest release" shortcut
- **Output root:** `BPCTOOL_OUTPUT_DIR` overrides `bpctool/runner-out` (keeps `ado-id-map.csv` safe from app-folder replacement)
- **`bpctool.env`:** launcher reads `BPCTOOL_*` keys from `bpctool/bpctool.env` (gitignored; see `bpctool.env.example`) so double-click users can set folders; real env vars win
- **Preview plan warnings:** several catalog workbooks of one kind in the folder (mixed releases → duplicates); catalog folder that only has release subfolders; template and catalog in sibling release folders
- Docs: USER_GUIDE §2 **Folder layout** (tree, rules, resolution order, outputs, env file), §10 new-release checklist, §11 / §15 / §18; README folder layout
- Tests: `test_paths.py` (release resolution, env overrides, warnings), `runnerEnvFile.test.js`; local-data tests use the same discovery instead of a fixed path

## 2026-10 — Release-agnostic template & catalog (quarterly updates)

- The template guideline, catalog workbooks, and Microsoft reference scripts are refreshed quarterly; code, UI, tests, and docs no longer reference one specific release
- **Template discovery** (`/defaults`, pytest fixture): newest `ADO template guideline*.xlsx` in the catalog folder (any release suffix) instead of a fixed file name; shared `excel_ir.find_template_workbook`
- UI **Workbook version** defaults to blank (placeholder suggests a release label such as `2026-Q3`); path examples no longer name a release
- Docs renamed: `docs/workflow-and-july-comparison.md` → [`docs/workflow-and-script-comparison.md`](./docs/workflow-and-script-comparison.md); `docs/reference/MSBPC-Jul26-analysis.md` → [`docs/reference/MSBPC-process-analysis.md`](./docs/reference/MSBPC-process-analysis.md)
- USER_GUIDE: quarterly release note, **one release per catalog folder**, and §10 "Moving to a new quarterly release" checklist
- `IR_VERSION` → `2026.10-1`

## 2026-10 — Work item types matrix: `H` = hidden field

- **Work item types** grid: `H` is now honoured (reference Script 2 ignored it). IR adds `hidden_field_labels` per WIT and `counts.hidden_field_placements`
- **Layout:** `H` fields are added to the WIT but get no form control; an existing control (e.g. inherited Completed Work / Activity / Stack rank) is hidden via `PATCH …/layout/groups/{group}/controls/{field}` `visible: false`. Changing `H` → `X` shows the control again
- Warning when an `H` field is required with no default value (users could not fill it on the form)
- Catalog prevalidate treats `H` fields as on the WIT (required-field defaults apply); dry-run plan / layout log report hidden counts
- Template at time of change: 15 `H` cells (inherited Action item / Bug / Business task / Issue / Task / Test case effort/build fields, Workshop → Microsoft workshop type)
- Docs: USER_GUIDE template sheet + Layout step; workflow comparison matrix section now "BPCTool extends the reference scripts"

## 2026-10 — Catalog performance, safe retries, cancel / reattach

**Runner**

- ADO client reuses **keep-alive HTTP(S) connections** per worker thread (stdlib `http.client`; idle sockets are reopened after 60 s)
- Retries: jittered exponential backoff; `Retry-After` accepted as seconds (incl. decimals) or HTTP-date, capped at 60 s; idempotent calls also retry 500/502/504
- **Work item create is no longer blindly retried.** Only 429/503 rejections are retried. A network error after a create was sent triggers a WIQL lookup (type + title + `MSBPC.microsoftid`): one match is adopted into `ado-id-map.csv`, no match is retried once, several matches fail as possible duplicates. Stats: `reconciled`, `outcome_unknown`
- Catalog scheduler: heap **ready queue** with a children-by-parent index (children queue as soon as their parent is created) instead of re-scanning all pending drafts per wave
- **Parent-link backfill** skips rows whose id-map `ParentId` matches (linked in the create payload → `already_linked`, no GET) and checks the rest in parallel with the catalog worker count
- **Cancel:** `POST /jobs/{id}/cancel`; job status `cancelled`. Stops between steps, at step progress checkpoints, and in Catalog Import after in-flight creates (recorded in the id map); backfill skipped; catalog step emits `step-cancelled`
- `GET /jobs/{id}?since=N` returns only new events (`event_offset`, `event_total`); `catalog-progress` events (create + backfill phases) about once a second; text progress lines every 500 items

**UI**

- **Cancel run** calls the runner cancel endpoint (shows **Cancelling…**); steps completed before cancel are cached, Catalog is not (re-run resumes)
- Reloading the page **reattaches** to a running Runner job (tab `sessionStorage`) and replays its log
- Catalog **progress bar** with done/total, created/skipped/failed, and ETA
- Runner mode: **Threads** renamed **Catalog workers**; Retry count and layout/backlog worksheet names hidden (Simulate/API only)
- Polling uses the incremental `since` API

**Review fixes**

- Pooled client honours `HTTPS_PROXY` / `HTTP_PROXY` / `NO_PROXY` and macOS system proxy settings (CONNECT tunnel, optional `user:pass@` proxy auth) — parity with the previous `urllib` client
- Sends a `User-Agent`; HTTP 203 sign-in page (invalid/expired PAT) raises a clear auth error instead of a JSON parse failure
- Unknown-outcome creates always record a blank `ParentId` (adopted or retried) so backfill verifies the link
- Cancel: drafts under a failed parent stay `Parent not imported` failures; only work blocked by unstarted items counts as `cancelled`
- UI polling survives up to 8 consecutive transient poll failures (backoff) before giving up; 404 still stops immediately
- **Cancel run** pressed before the runner returns the job id is queued and sent once the id arrives (previously only polling stopped)

**Tests:** ready queue, cancel, unknown-outcome create reconcile, backfill skip/parallel, client retry rules, job cancel + `since`, progress summary (vitest)

## 2026-10 — Docs: workflow & reference-script comparison (re-runs / conflicts)

- [`docs/workflow-and-script-comparison.md`](./docs/workflow-and-script-comparison.md) assessment **2026-10-06**: incremental re-run table (update policies, per-step create/skip/heal), catalog backfill conflict statuses, process rules gap (neither the guideline Excel nor BPCTool), comparison + residual rows refreshed

## 2026-08 — Docs: audit sync (re-run semantics + X vs H)

- USER_GUIDE: Work item types matrix **`X` only** (`H` ignored); §10 table for what subsequent spreadsheet runs update (catalog create-only / resume)
- Repo docs already covered Catalog parallel/resume/backfill, Multivalue required, empty Description, picklist case-normalize; workflow comparison + indexes dated 2026-08-11

## 2026-08 — Docs: workflow & reference-script comparison (current assessment)

- [`docs/workflow-and-script-comparison.md`](./docs/workflow-and-script-comparison.md): assessment date; template matrix **X vs H** parity; UI Runner/API/Simulate; Catalog parallel/resume/backfill + prevalidate notes; comparison table rows for matrix / prevalidate / execution modes

## 2026-08 — Docs: README UI screenshots

- Added `docs/images/` screenshots (Connection / Multivalue, workflow cards, run config, Catalog Threads + actions) linked from [`README.md`](../README.md#screenshots)

## 2026-08 — Docs: catalog parallel / resume / backfill

- [`docs/workflow-and-script-comparison.md`](./docs/workflow-and-script-comparison.md) updated for Catalog Import assessment (parallel workers, id-map resume, parent-link backfill, hierarchy-only relations, residual vs the reference scripts)
- USER_GUIDE / README job field `catalog_parallel_workers`, artifacts, troubleshooting, quick reference

## 2026-08 — Catalog: parallel create, resume, parent-link backfill

- Catalog Import uses **parent-aware parallel workers** (UI **Threads**, default 4; clamp 1–16; reference-script style ready queue)
- **Resume** from existing `ado-id-map.csv` (skip keys already imported; append new rows)
- After create, **parent-link backfill** checks Hierarchy-Reverse and writes `backfill-links-report.csv` (link / already_linked / conflict / failed)
- Children wait until the parent id exists (no create-unlinked when parent failed — counted as `Parent not imported`)

## 2026-08 — Docs: Multivalue required + catalog notes

- Root README, app README, USER_GUIDE, and residual-risk notes state that DevLabs **Multivalue** is **required** for process / layout / project
- Documented empty Description omit, case-insensitive picklist prevalidate, `/extmgmt-proxy`, and Connection Check/Install

## 2026-08 — Catalog: no synthetic Description

- Catalog import no longer invents `System.Description` when the spreadsheet Description is empty (removed “Imported from … row N” placeholder)

## 2026-08 — Picklist case-insensitive prevalidate

- Catalog prevalidate matches single- and multi-select picklist values **case-insensitively** and rewrites to the template Picklists-sheet casing (e.g. `Organization Administration` → `Organization administration` for `MSBPC.module`)
- Counted as `picklist_case_normalized` in `import-prevalidate.json` (no longer stripped as `invalid_picklist_value`)

## 2026-08 — DevLabs Multivalue extension preflight

- Connection panel checks whether `ms-devlabs.vsts-extensions-multivalue-control` is installed on the org (via Extension Management API)
- If missing, Run prompts to install with the current PAT; decline or install failure blocks process / layout / project setup
- Live runner apply also requires the extension before those steps (defense in depth)
- Vite `/extmgmt-proxy` → `extmgmt.dev.azure.com`

## 2026-08 — Reference: post-create process analysis

- Added [`docs/reference/MSBPC-process-analysis.md`](./docs/reference/MSBPC-process-analysis.md) — WIT/states/fields snapshot of process `MSBPCTemplate` after template apply

## 2026-08 — Repo root cleanup

- Removed Visual Studio scaffold (`BPCTool.sln`, `bpctool.esproj`), empty root `package-lock.json`, and tracked `.DS_Store`
- Slimmed root `.gitignore` / `.gitattributes` for Node + Python
- Single changelog: this file; root [`README.md`](../README.md) is the repo entry point
- Retired `DEPRECATIONS.md` (notes folded here / USER_GUIDE §17)

## 2026-08 — Template not bundled; scaffold cleanup

- ADO **template guideline** `.xlsx` is user-supplied (removed `fixtures/`); `/defaults` may discover it via `BPCTOOL_TEMPLATE` or under the catalog folder
- Removed unused `.github/copilot-instructions.md` and `.vscode/launch.json`

## 2026-08 — Catalog required-field defaults

- When a required Fields-sheet field is empty in the catalog spreadsheet but has a **Default value**, Catalog Import / prevalidate fills that default (e.g. Business process flow source → `Microsoft`)
- Remaining required empties (no default) still report in `import-prevalidate.json`

## 2026-08 — Run timings, remove profiles, cleanup

- Apply/job runs emit **Run timing** (per-step `durationMs` + total) in the event log and on `ApplyResult` / `JobStatusResponse`
- Removed **Save / Load profile** UI and `bpcProfiles` storage (org URL + PAT remain session-only)
- Removed unused Vite scaffold assets (`src/assets/*`, `public/icons.svg`), dead `plan_only` / `testConnection` helpers
- Docs updated for connection panel rename and timing summary

## 2026-08 — Docs sync (catalog, multi-value, prevalidate)

- README / USER_GUIDE / CHANGELOG updated for Catalog Import (all matching workbooks), Title 1..N parents, multi-value picklists, prevalidate artifacts, and re-import guidance
- USER_GUIDE §9 documents catalog sources, hierarchy, keys, prevalidate actions, create-only behavior, and System.State ownership

## 2026-08 — Multi-value picklists + catalog prevalidate

- Fields marked **Multi-select** (Application family, Products, Industries, …) create **suggested** picklists (`isSuggested` / `isPicklistSuggested`) so semicolon-separated values import
- Layout binds DevLabs **Multivalue** control for those fields (later: extension **required** via Connection/runner preflight — see Multivalue preflight entry above; no longer “optional fallback”)
- Catalog **prevalidate** before create: strip `Area Path=Not found`, strip Test Case `State=New`, strip invalid single picklist values, normalize multi-select tokens; writes `import-prevalidate.json` (later: case-insensitive picklist align — see picklist entry above)
- Module: `catalog_validate.py`; tests for prevalidate, multiselect labels, layout control type

## 2026-08 — Catalog parent links (Title outline)

- Parent/child links follow **Title 1..N** columns (ADO CSV import hierarchy), per [Microsoft Learn](https://learn.microsoft.com/dynamics365/guidance/business-processes/about-import-catalog-devops)
- Process sequence ID is stored on the work item / used as a key, **not** used to derive relationships
- Catalog Import loads **all** matching workbooks in the catalog folder (Business Process Catalog, Deliverables, Objectives, SbD Delivery Plan, etc.)
- Catalog import reports linked / missing-parent counts; `ado-id-map.csv` includes ParentKey/ParentId

## 2026-08 — Docs sync + UI layout

- README / USER_GUIDE rewritten for current launchers, run modes, Excel backlog/disabled WITs, project description, org URL forms, path browser, and troubleshooting
- Wider resizable content shell (~1600px); full-width PAT / org URL / long path rows; less crowded Run configuration grid

## 2026-08 — Project description

- UI field **Project description** (session-persisted) passed as `project_description` on runner jobs
- Create no longer writes `Project for process <guid>`; empty description allowed
- Re-running Project Creation PATCHes description when the field is non-empty

## 2026-08 — Disabled WITs + backlog levels from Excel

- Keep Excel-disabled WITs (Epic / Feature / User story) in IR; Process materializes then `isDisabled`
- Backlog step follows reference Script 4: rename/create levels from **Backlogs** sheet, assign WITs, set defaults
- Heal prior buggy applies that created custom Levels/Lowest beside system Epics/Features (delete duplicate, rename Agile behaviors)
- Tests for rename matrix, duplicate heal, WIT assign skip-disabled, defaults

## 2026-08 — Teams, areas, iterations

- Team area paths: aggregate all Excel paths per team into one `teamfieldvalues` PATCH (`includeChildren: false` by default)
- Area paths parse L1–L4 (skip project column); root area path UI defaults to **project name**
- Backlog step sets team `backlogIteration` from classification tree root GUID before selecting iterations (fixes blank Backlog iteration / blocked Select iteration)
- Assigns child iterations to each Teams-sheet team; optional include-children when Excel says Yes

## 2026-08 — Org URL, path picker, run modes

- Org URL normalize: `dev.azure.com/{org}`, `{org}.visualstudio.com`, bare org → `https://dev.azure.com/{org}`
- Local filesystem Browse… (`/fs` + `PathPickerModal`) for template file and catalog folder
- Run modes: **Selected step only** (default), Dependency-aware, Full — so backlog/teams can re-run without process/project confirm gates
- Launcher / Vite plugin replaces stale `:8787` and starts uvicorn with `--reload`

## 2026-08 — Zero-CLI launch

- Vite plugin auto-starts/stops the local FastAPI runner with the UI (`scripts/localRunnerPlugin.js`)
- Double-click launchers: `Start BPCTool.command` (macOS), `Start BPCTool.bat` (Windows)
- `npm run setup` / `npm start` bootstrap env and open the browser
- Default execution mode is **Runner**

## 2026-08 — Standalone reference-script replacement (P0/P1)

### Summary

Replaced the fragile “UI wraps Microsoft reference Python scripts” approach with a **standalone** control plane + execution plane:

- React UI orchestrates configuration, policy, and progress
- Local FastAPI runner owns Excel parsing, planning, and ADO apply
- No subprocess calls to the reference `.py` scripts

### Architecture

| Before | After |
|--------|-------|
| Shell out to six reference scripts via env vars | In-process writers via Azure DevOps REST |
| Process + project created together (reference phase 1) | Hard gate: **process → layout → project** |
| Excel read live during each script | Excel → IR → plan → apply → report |
| Limited UI observability | Structured job events + `runner-out/` artifacts |

Recommended engine step order:

`process → layout → project → teams → backlog → catalog → report`

### Local runner (`runner/`)

Added FastAPI app on `127.0.0.1:8787` (proxied as `/api` from Vite):

| Module | Role |
|--------|------|
| `excel_ir.py` | Parse template guideline sheets + catalog folder into IR |
| `planner.py` | Deterministic dry-run plan + update-policy gates |
| `richtext.py` | HTML detection; optional markdown→HTML |
| `catalog_import.py` | Catalog drafts, Title 1..N parents, multiline format flags |
| `catalog_validate.py` | Prevalidate / sanitize before catalog create |
| `mapping.py` | Catalog headers → ADO field refs (+ multi_select metadata) |
| `ado_client.py` | PAT Basic auth, retries on 429/503 |
| `org_url.py` | Org URL parse/normalize |
| `fs_browser.py` | Local path listing for Browse… |
| `apply_engine.py` | Step orchestration for apply / apply dry-run |
| `writers/*` | process, layout, project, teams, backlog, catalog, report |
| `jobs.py` | In-memory job store; apply runs on background thread |

API surface:

- `GET /health`, `GET /defaults`
- `POST /plan/dry-run`, `POST /ir/parse`
- `POST /jobs`, `GET /jobs/{id}`
- `GET /fs/roots`, `GET /fs/list`

### React UI

- Connection profile (org URL normalize, session PAT, Ready state)
- Fetch projects / Fetch processes via `/ado-proxy`
- Free-text process/project names + optional project description + create/update assessment
- Update policies: require confirmation / always update / skip existing / create-only
- Workbook version fingerprinting (`bpcWorkbookApplies`)
- Collapsible sections + path picker for template/catalog
- Execution modes: **Simulate**, **API** (reads), **Runner** (full engine)
- Workflow run modes: Selected step only / Dependency-aware / Full
- **Preview plan (dry-run)** wired to runner
- **Run** in Runner mode posts `/api/jobs` and polls events
- Workflow cards expanded to include **catalog** and **report**
- Removed dependency on reference script filenames as executors (labels now `runner · <step>`)

### Rich text

| Behavior | Detail |
|----------|--------|
| Default | Preserve markdown-like Excel text; set `/multilineFieldsFormat/{field}=Markdown` on create |
| Optional | UI **Convert Markdown large-text fields to HTML** / API `convert_markdown_to_html` |
| HTML cells | Always passed through (e.g. Microsoft references) |

### Inputs / defaults

- Template: user-provided ADO guideline `.xlsx` (optional discover under catalog folder / `BPCTOOL_TEMPLATE`)
- Catalog sources default: `/Users/you/BPC Files` (current quarterly package)
- Apply artifacts: `runner-out/<org>_<project>/` (gitignored)

### Tooling

- `npm run runner` / `npm run runner:install` (prefer `npm start` for day-to-day)
- Vitest frontend tests; pytest runner tests
- README + USER_GUIDE documentation

### Explicitly not done / residual risk

- **DevLabs Multivalue extension is required** for process / layout / project; UI/runner preflight + optional install via Extension Management API; Marketplace/admin if PAT cannot install
- Catalog Import: parent-aware parallel workers + id-map resume + parent-link backfill (reference-script aligned); still create-only (no WIP field upsert)
- Not every reference script edge case is ported
- Inherited system WIT disable via Process API can still fail (manual ADO UI fallback)
- Empty catalog Description omits `System.Description` (no synthetic placeholder)
- In-memory jobs only (lost on runner restart)
- UI cancel stops client polling; does not always kill an in-flight apply thread
- Large catalog imports (~15k rows across all matching workbooks) are long-running; use `apply_dry_run` / `catalog_limit` for smoke tests; start Threads at 2–8 to limit ATCPU/429
- Process re-run may log non-fatal `MSBPC.*` field 404 warnings when org fields already exist (Update API is lock/undelete only)

### Optional surfaces still wired (not primary path)

- **Simulate** / **API** execution modes (stubs / ADO reads); Runner is the apply path
- UI fields `threads` (also Catalog Import parallel workers in Runner), `maxRetries`, `layoutSheet`, `backlogSheet` (`maxRetries` / sheet names remain Simulate/API-oriented)
- `POST /ir/parse` (manual API; UI does not call it)
- `npm run runner` / `runner:install` (prefer `npm start` + Vite plugin)

---

## Earlier baseline (pre-runner)

- React workflow cards modeling process/layout/project/teams/backlog
- Simulate executors and ADO read adapters
- Connection / policy / fingerprint foundations later reused by the runner
