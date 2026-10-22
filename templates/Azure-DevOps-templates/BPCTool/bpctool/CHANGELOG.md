# Changelog

All notable changes to BPCTool (React UI + local runner) are documented here.

## 2026-10 — Run results a standard user can act on

- **Rehearsal change report**: when the project exists, a rehearsal reads its catalog work items (`workitemsbatch`, 200 per request) and compares them with the workbook. Shown as *Changes since the last import* in the results card and `rehearsal-summary.html`. **`import-changes.csv`** lists every difference: field value, parent, or work item type differs; item not found in Azure DevOps; imported earlier but no longer in the workbook; new row. Each field is marked as usually edited in the workbook or in Azure DevOps. `import-changes.json` holds the counts. Only fields the workbook fills are compared, and formatting differences are ignored (HTML markup, number format, multi-select/tag order, path case, identities, booleans, dates). The report is information only: live Catalog Import is still create-only
- Rehearsals now make **read-only** Azure DevOps calls, only in the catalog step, through a new `ReadOnlyAdoClient` that refuses anything except GET and the `wiql` / `workitemsbatch` reads. The step looks up the project; if it exists, it reads the project's area paths and states (so a rehearsal's data checks match a live run's) and its catalog work items. If neither the project nor an earlier import exists, the report says there is nothing to compare. If the ID map exists but the project doesn't, it reports that the project was deleted or renamed. An unreadable Azure DevOps (for example an expired PAT) skips the comparison without failing the rehearsal
- **Existing project without `ado-id-map.csv`**: the rehearsal matches workbook rows to the project's work items by Microsoft ID (+ Process sequence ID), compares them, and flags matched rows under **What needs attention** as rows a live Catalog Import would create again (duplicates). Rows matching several items are listed separately
- Fix: the project existence check (live runs, project and teams steps) read only the first 100 projects in the organization; it now looks the project up by name
- Fix: a rehearsal's "a live run would import N" count was too low when `ado-id-map.csv` listed items no longer in the workbook; it now counts only workbook rows, matching the change report's new rows
- Change report examples for long text (e.g. Description) start just before the first difference, so both sides no longer look identical when the edit is past the first 120 characters
- Fix: Preview plan's data checks used the Root area path as typed (empty or missing) while runs default it to the project name; both now use the same default
- **Deprecated / Deleted catalog rows are skipped by default**, as the Microsoft July importer does: a row whose Catalog status contains *Deprecated* or *Deleted* (700 rows in the July workbooks) and every row below it in the Title outline. Listed in the new `skipped-deprecated-deleted.csv`, under *Fixed automatically* in the results card / report, and as a Preview plan notice (Preview plan's data checks skip them too). New Run configuration checkbox **Import Deprecated / Deleted rows** (API `include_deprecated_deleted`, also on `POST /plan/dry-run`) imports them. Existing work items are never closed or removed; a rehearsal reports items imported before their row was retired as *Deprecated or deleted in the workbook — still in Azure DevOps*
- Docs: workflow & reference-script comparison re-checked against Microsoft's July 2026 package (`setup_wizard.py`, `ado_setup_validation.py`, phases 1–6, `bpc_ado_import`). New rows: pre-run checks, disabled WITs, Test Case `New` state, deprecated / deleted rows, repeated sequence IDs, catalog area / iteration nodes, failure handling, dry run; corrected Multivalue (the July Phase 2 installs or skips controls), create retries, prevalidate and report rows; residual list updated
- Page header now reads **BPCTool** with a one-line description and four plain steps (connect, name, pick steps, Preview plan → Rehearsal → live); the mode line is in plain language and the browser tab title is *BPCTool*
- `npm start` on a fresh clone or copy no longer leaves the runner down with *Python runner venv not found*: the launcher runs the Python setup (`ensure-env`) first, logged as `[bpc-setup]`, then starts the runner. When the runner can't be reached, the UI says so and points to the terminal window (status line, path picker, Preview plan, runs) instead of *Failed to fetch*. On page open it keeps retrying the runner defaults for up to 3 minutes while the runner starts
- Fix: a live run whose first Azure DevOps check failed (expired PAT, network) ended without a summary or results card; it now writes both, with the reason
- Fix: a rehearsal without `ado-id-map.csv` failed its change report when a project had more than 20,000 items of one type (Azure DevOps' WIQL limit); the Microsoft ID search now reads 10,000 IDs at a time
- `npm start` / Start BPCTool no longer start the runner with `--reload`, which restarted it (and cut off a run in progress) whenever its code changed, e.g. a `git pull` mid-import. Relaunch to load new code; `npm run dev` keeps `--reload` for development
- Fix: pressing Cancel just as the last step finished reported a completed run as cancelled
- An Area Path that is both renamed to the target project and moved under the Root area path now says both in the data checks
- Fix: a Fetch existing projects / processes still in flight when the org URL or PAT changed recorded its list against the new connection
- Fix: the **Backlog** step now counts as changing the process for the existing-target policy (it renames, creates and deletes the process's backlog levels, shared by every project on it). A Backlog-only run against an existing process needs **Confirm process update** and is refused under *create-only*, in the UI and the runner
- Fix: job / plan `steps` must name known steps — an unknown name (e.g. `backlogg`) used to be ignored and report success, and an empty list ran every step. Both are rejected (HTTP 422); `null` still runs every step, and steps always run in engine order
- Fix: a failed project description update on an existing project now marks the Project step as a warning (listed under What needs attention) instead of reporting success; the run continues
- Fix: team area assignments are grouped by team name ignoring case, as Azure DevOps does — rows for `Accounting` and `accounting` used to send two updates, the second replacing the first's areas
- Fix: the **Teams** step turned off *Include sub areas* whenever it updated a team's areas, so a Teams-only re-run left it off until Backlog ran. Teams now sends the Teams sheet's *Include sub areas* value itself
- Fix: **Page Layout** treated any 400 when adding a field to a work item type as "already there", so the fallback payloads for boolean fields never ran and a rejected field went unreported (and then failed again as a control). Fields already on the type are now read up front and skipped; a 400 tries the next payload and is reported if all fail
- Page Layout reads each work item type's fields and form once instead of once or twice per field (the August run spent about 10 minutes here for about 1,100 placements); the form is re-read only after a page, group or control is added
- Teams reads the project's area tree once instead of checking each area node with its own request
- Backlog configures teams in parallel, using the **Catalog workers** setting (the August run spent about 3 minutes on team settings one team at a time)
- Preview plan is about twice as fast on first run (about 2.1 s → 1.2 s for the July catalog) and about three times faster on repeat (about 0.65 s): each catalog workbook is read once and reused until the file changes, header names are no longer re-normalized for every row, and the required-field list is built once
- The runner forgets a job's PAT as soon as the job ends, and keeps only the 20 most recent finished jobs (with their event logs) instead of every job since it started
- Fix: Cancel during **Backlog** now stops promptly — with teams configured in parallel, every team still queued went on to change its settings after Cancel; now only teams already in progress finish
- Fix: under **Skip steps for existing targets**, an existing process with a new project still had its backlog levels renamed, created or deleted by the Backlog step. Backlog now leaves the process alone in that case and only sets up iterations and team settings; Preview plan says so
- Fix: Page Layout treated a 400 when adding an HTML control as success; it is now a warning with the Azure DevOps reason. Warnings for a group or page that couldn't be created now include the reason too
- Finished jobs no longer keep a second copy of their event log in the stored result (the job's own event list has every event); after a page reload, a job the runner no longer has says it may have been dropped as one of the oldest
- Fix: two projects whose names give the same results folder name (`Finance Team` and `Finance_Team` → `contoso_Finance_Team`) shared one folder — and one `ado-id-map.csv`, so the second project's Catalog Import skipped rows that were only created in the first. Each results folder now records its organization and project in `bpctool-target.json`; another project gets its own `<org>_<project>-<8 characters>` folder (the run log says so), and runs that would share a folder name wait for each other. Before any step, a run reads up to 20 of the work items in `ado-id-map.csv`: an older folder (no `bpctool-target.json`) is claimed only when they are in this project; when they are in another project, the folder is recorded as that project's and this run moves to its own folder, so the real owner keeps its list
- Fix: a live Catalog Import into a project that had been deleted and created again with the same name skipped every row in the old `ado-id-map.csv`, created nothing and reported success. When none of the sampled items exist any more (or the map lists another project's items in this project's folder), a run that includes Catalog Import now stops before the first step and says to move the file aside; other runs log a warning
- Fix: the **Process** step reported success when Azure DevOps refused to create a work item type, picklist or field (for example a 403 because the PAT lacked process rights): failures were only logged and Layout then failed on the missing types. It now tries every item, then fails the step with the first reasons, so the run stops and shows as failed. Update and disable failures are warnings, and the step shows as *warning* with the count. A picklist that can't be created is reported once, not again for its field
- Process no longer sends an update for organization fields that already exist: Azure DevOps' Fields update API only locks or restores fields, so every re-run logged a 404 per `MSBPC.*` field. Existing fields are counted as *already existed* (that count previously showed built-in fields the workbook doesn't create)
- CSV reports (`import-failures.csv`, `import-prevalidate.csv`, `import-changes.csv`, `import-preview.csv`, `skipped-deprecated-deleted.csv`, `backfill-links-report.csv`) now prefix text starting with `=`, `+`, `-`, `@`, tab or carriage return with `'`, so workbook or Azure DevOps text can't run as an Excel formula. `ado-id-map.csv` is unchanged because BPCTool reads it back
- `npm run runner` and `npm run runner:install` work on Windows (they called `.venv/bin/…`, which only exists on macOS / Linux) through the new `scripts/runner.mjs`. New `npm run runner:install-dev` (installs the new `runner/requirements-dev.txt`, which adds pytest) and `npm run runner:test`. Two runner tests that only passed on macOS / Linux (a `/data/out` absolute path and an unencoded `?root=` link) are portable
- Docs: PAT scopes by run type (rehearsal, catalog-only, full setup, installing the Multivalue extension) replace the old list — creating the process needs Work Items *Read, write, & manage* and creating the project and teams needs Project and Team *Read, write, & manage*; Identity isn't used. The PAT note now says sessionStorage is cleared when the tab closes rather than "never on disk", and a new note covers what reports contain and how long they're kept. Node requirement corrected to 20.19+ or 22.12+ (Vite 8)
- Connection panel: the PAT field and note no longer say "session only, not saved"; they say the org URL and PAT are kept in this tab's session storage until it closes (never in profiles or results) and point to the PAT scopes in the User Guide. The Run output folder hint mentions the `-<code>` folder used when another project's results already have the name. Screenshots retaken: `ui-connection.png`, `ui-run-config.png`
- Docs: new one-page [Quick reference](./docs/QUICK_REFERENCE.md) (start, PAT scopes, run order, which button changes what, run modes, update policy, results files, common problems, developer commands), linked from the README and User Guide. User Guide troubleshooting gains entries for a run stopped by `ado-id-map.csv` and for *Process step: … could not be created*; the PAT and run-in-progress entries match the current scopes and message
- Removed `docs/reference/MSBPC-process-analysis.md` (a snapshot of the process from one template release, 2026-08-09) and its links in the README and workflow comparison
- UI hints for **Rehearsal only** and **Root area path**, User Guide, README and workflow comparison updated for the read-only rehearsal and change report; screenshots retaken (connection, actions, rehearsal, results card)

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
- Fix: catalog rows that repeat another row's **Process sequence ID** were silently dropped (31 rows in the July Business Process Catalog workbook), and their child rows were linked under the first row. Repeats now get their own tracking key in `ado-id-map.csv` (`<id>#<Microsoft ID>`; the first row keeps the plain ID so existing files still resume). The work item's Process sequence ID field is not changed. Repeats are imported on the next Catalog Import and listed under *Fixed automatically*. Preview plan's catalog row count now matches the number imported. Children already imported under the wrong parent are reported as `conflict_existing_parent` in `backfill-links-report.csv` and left unchanged
- Fix: links inside the HTML report (failures, data checks) opened from the results card now work with a custom **Run output folder**
- When a live run doesn't include Catalog Import but an earlier one left failures, the headline says the problems are from the earlier Catalog Import instead of reporting them as this run's result
- New run mode **Run from selected step onward**: runs the selected card and every later card, including completed ones (Process + Layout gate still applies)
- Durations of an hour or more show as `1h 55m`
- Removed wording that described BPCTool as part of a larger toolkit — it is a standalone app
- Fix: two rehearsal/live runs for the same org + project could run at once (e.g. two browser tabs), creating duplicate work items and overwriting reports. The runner now refuses the second with HTTP 409 until the first finishes
- Security: the runner no longer sends wildcard CORS headers, so other websites open in the browser can't read it (job results, output files, the local folder browser), and it only answers requests addressed to `127.0.0.1` / `localhost` (blocks DNS rebinding). The UI is unaffected — it uses the `/api` proxy
- Fix: with the existing process/project list not fetched, **Create only** and **Require confirmation** were not enforced and a live run updated existing targets. Live runs now check Azure DevOps for the process and project before applying the policy; Preview plan / Rehearsal say when existence wasn't checked
- Existing projects and processes load automatically once the org URL and PAT are filled in, and again after each live run, so the confirm boxes and Preview plan / Rehearsal policy checks are right without clicking **Fetch existing …** (the buttons now refresh). The UI's confirm rules now only apply to the steps that change that target (process: Process Template / Page Layout; project: Project Creation), as the runner's do, so Teams / Backlog / Catalog re-runs aren't blocked by an existing project
- Fix: Project Creation reused an existing project without checking its process. A project created from a different process now stops the run with how to fix it
- Fix: a **Root area path** below the project (e.g. `Proj\Imported`) was shown in the plan but ignored by live runs. Teams & areas now creates the area tree and team assignments under it, and Catalog Import moves catalog Area Paths there to match (*Area path placed under the Root area path* in the data checks)
- Fix: launching BPCTool could stop a runner with a run in progress, or an unrelated program on port 8787. The launcher now reuses a busy BPCTool runner, replaces only an idle one, and leaves other programs alone. `/health` reports `active_jobs`
- Fix (Windows): first-launch setup failed when the BPCTool folder path contains spaces (pip ran through `cmd.exe` unquoted)
- Security: dev-tool dependencies updated to clear `npm audit` (vitest / @vitest/mocker 4.1.12, brace-expansion 5.0.12, nanoid 3.3.20, source-map-js 1.2.2); no change to the app's runtime dependencies
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

- **No hard-coded user paths.** Catalog root defaults to `~/BPC Files` (was `/Users/bill/BPC Files` in runner + UI); the UI catalog field starts empty and is filled from the runner
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
- Docs renamed: `docs/workflow-and-july-comparison.md` → [`docs/workflow-and-script-comparison.md`](./docs/workflow-and-script-comparison.md); `docs/reference/MSBPC-Jul26-analysis.md` → `docs/reference/MSBPC-process-analysis.md`
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

- Added `docs/reference/MSBPC-process-analysis.md` — WIT/states/fields snapshot of process `MSBPCTemplate` after template apply

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
- Catalog sources default: `/Users/bill/BPC Files` (current quarterly package)
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
