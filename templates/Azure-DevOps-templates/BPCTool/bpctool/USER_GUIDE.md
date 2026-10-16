# BPCTool User Guide

This guide covers requirements, installation, step-by-step usage, architecture, API, and troubleshooting for the Business Process Catalog (BPC) Azure DevOps setup tool.

For a short overview, see the [README](../README.md). For release history, see [CHANGELOG.md](./CHANGELOG.md).

![BPCTool at a glance: what you need, the seven steps, and what you get](./docs/images/bpctool-overview.svg)

---

## 1. What this tool does

BPCTool configures an Azure DevOps organization for the Microsoft Business Process Catalog pattern:

1. Create/update an **inherited process** from the ADO template guideline workbook (refreshed quarterly)
2. Apply **page layouts** (including HTML field controls and DevLabs Multivalue for Multi-select) **before** any project exists — requires the Multivalue extension on the org
3. Create/bind a **project** to that process (optional description)
4. Upsert **teams** and **area paths** (including multi-path team assignments)
5. Configure **backlog levels**, **WIT→backlog mapping**, **iteration paths**, and **team iteration settings**
6. **Import catalog** content — every matching workbook in the catalog folder (Business Process Catalog, Deliverables, Objectives, SbD Delivery Plan, etc.), not only the BPC file
7. Emit an **HTML/JSON summary report** — also written automatically at the end of every run, and shown in the UI as a **results card**

Excel remains the authoring format. A local FastAPI runner parses workbooks into an intermediate representation (IR), builds a plan, and applies changes through Azure DevOps REST APIs.

**Important:** This app does **not** shell out to the Microsoft reference Python scripts. It is a standalone React UI + local runner engine. The runner starts automatically with the UI.

**Quarterly releases:** Microsoft refreshes the template guideline, the catalog workbooks, and the reference scripts each quarter. BPCTool is not tied to a specific release — point it at the current quarter's files and set **Workbook version** to the release label (see §10).

---

## 2. Requirements

### Software

| Component | Requirement |
|-----------|-------------|
| Node.js | 20+ recommended (Vite 8) |
| npm | Comes with Node |
| Python | 3.11+ (3.12–3.14 tested) |
| OS | macOS / Windows / Linux with local filesystem access to Excel files |

### Azure DevOps

| Item | Notes |
|------|-------|
| Organization URL | `https://dev.azure.com/{org}`, `https://{org}.visualstudio.com`, or bare `{org}` (normalized to `https://dev.azure.com/{org}`) |
| PAT | Personal Access Token with scopes sufficient to manage processes, projects, work items, and teams. Typically: **Work Items (Read & Write)**, **Project and Team (Read & Write)**, **Identity (Read)**. Process customization may require organization-level permissions. To **install** the Multivalue extension from the UI, the account/PAT must be able to manage organization extensions (often org owner/admin). |
| Permissions | Ability to create inherited processes and projects in the target org |
| **Multivalue extension (required)** | [Multivalue control (Microsoft DevLabs)](https://marketplace.visualstudio.com/items?itemName=ms-devlabs.vsts-extensions-multivalue-control) (`ms-devlabs.vsts-extensions-multivalue-control`) **must** be installed and enabled on the organization before process template, page layout, and project setup. Connection auto-checks; Run prompts to install if missing. Without it, those steps are blocked. |

### Input files

| Input | Purpose | Example |
|-------|---------|---------|
| ADO template workbook | Process/WITs/fields/picklists/teams/areas/backlogs | `~/BPC Files/2026-Q4/ADO template guideline (…).xlsx` (any release suffix) |
| Catalog source folder | All catalog import workbooks (`.xlsx`) for step 6 | `~/BPC Files/2026-Q4` |

**Catalog Import** reads **all** matching `.xlsx` files in that folder in one step (typically ~15k rows across BPC + Deliverables + Objectives + SbD). Recognition uses name hints: *Business Process Catalog*, *Deliverables*, *Objectives*, *Delivery Plan*, *SbD* (case-insensitive). Release suffixes are fine — e.g. `Deliverables <MMM YYYY>.xlsx`. Files whose names look like the ADO **template guideline** are excluded even if they sit in the same folder — use that workbook only as **Template workbook path**. Subfolders are **not** scanned.

### Folder layout (recommended)

Microsoft ships a new template + catalog set each quarter. Keep each release in its own folder under one root, and keep run outputs somewhere they will survive app upgrades:

```text
~/BPC Files/                                  root (BPCTOOL_CATALOG; default ~/BPC Files)
  2026-Q3/                                    one quarterly release per folder
    ADO template guideline (…).xlsx           template — Template workbook path
    Business Process Catalog ….xlsx           ┐
    Deliverables ….xlsx                       │ catalog workbooks — all imported
    Objectives ….xlsx                         │ (Catalog source folder = this folder)
    SbD Delivery Plan ….xlsx                  ┘
  2026-Q4/                                    next release — same file set
  _archive/                                   "_" or "." prefix → ignored by discovery
  _runner-out/                                optional BPCTOOL_OUTPUT_DIR (see below)
      <org>_<project>/
        ado-id-map.csv                        KEEP — prevents duplicate catalog items
        bpc-ado-setup-summary.html, import-failures.csv, …
```

| Rule | Why |
|------|-----|
| **One release per folder** | Every catalog workbook in the folder is imported; two `Deliverables …` files from different quarters would both import (Preview plan warns when it sees duplicates of a kind) |
| **Template next to its catalog files** | Load runner defaults finds the template in the release folder; Preview plan warns when template and catalog come from sibling folders (e.g. Q4 template + Q3 catalog) |
| **Name release folders `YYYY-Qn`** | Load runner defaults picks the highest `YYYY-Qn` name; other names fall back to the folder with the most recently modified workbook |
| **Close Excel first** | Lock files (`~$…`) are ignored, but an open workbook can fail to read |
| **Keep the output folder** | `ado-id-map.csv` is per org + project, not per release. It is what lets a later quarter (or a re-run) skip items already created. Losing it means the next Catalog run creates duplicates |

**How Load runner defaults resolves folders** (it also runs once automatically when the page opens, without overwriting paths you typed):

1. Root = `BPCTOOL_CATALOG`, else `~/BPC Files`.
2. If the root itself contains catalog workbooks or a template, it is used as the release folder (flat layout still works).
3. Otherwise the newest release subfolder is used, and its folder name pre-fills **Workbook version** if that is blank.
4. Template = `BPCTOOL_TEMPLATE`, else the newest `ADO template guideline*.xlsx` in the release folder.

**Run outputs** go to `<run output folder>/<org>_<project>/`. Pick the folder in **Run configuration → Run output folder** (Browse…; remembered in this browser). Left empty, it uses `BPCTOOL_OUTPUT_DIR`, else `bpctool/runner-out`. Because `runner-out` is inside the app folder, replacing the app folder during an upgrade deletes it — choose a folder outside the app (e.g. `~/BPC Files/_runner-out`), or copy `runner-out/` across when upgrading. When you switch folders, move existing `<org>_<project>/` folders with you: `ado-id-map.csv` in there is what stops a Catalog re-run from creating duplicates.

**Setting the folder variables:** copy `bpctool/bpctool.env.example` to `bpctool/bpctool.env` and uncomment `BPCTOOL_CATALOG`, `BPCTOOL_TEMPLATE`, or `BPCTOOL_OUTPUT_DIR`. The launcher reads it on start (double-click launchers included); real environment variables take precedence. Restart BPCTool after editing.

### Ports

| Service | Default |
|---------|---------|
| Vite UI | `http://127.0.0.1:5173` (or next free port) |
| Local runner API | `http://127.0.0.1:8787` |

Vite proxies:

- `/api/*` → runner (`8787`)
- `/ado-proxy/*` → `https://dev.azure.com`
- `/extmgmt-proxy/*` → `https://extmgmt.dev.azure.com` (extension install/check)
- `/fs/*` → local filesystem browser (path picker)

---

## 3. Installation

### Recommended (no command line)

1. Install **Node.js 20+** and **Python 3.11+** once on the machine (system installers).
2. Double-click:
   - macOS: `Start BPCTool.command`
   - Windows: `Start BPCTool.bat`
3. First launch runs `npm run setup` automatically (npm packages + Python venv + runner requirements).

Manual equivalent (developers):

```bash
cd bpctool
npm run setup    # node_modules + .venv + runner requirements
npm start        # UI + auto-started runner; opens browser
```

`npm run setup` installs packages from `runner/requirements.txt` into `.venv`:

- fastapi, uvicorn, openpyxl, pydantic, python-multipart

---

## 4. Starting the application

**You do not need separate terminals for the UI and runner.**

| How | What happens |
|-----|----------------|
| Double-click `Start BPCTool.command` / `.bat` | Setup if needed → start UI → auto-start runner → open browser |
| `npm start` | Same as above (without the setup wrapper) |

The Vite process starts the FastAPI runner on `127.0.0.1:8787` via `scripts/localRunnerPlugin.js` (with `--reload`, and it replaces a stale process already bound to `8787`). Closing the start window / stopping Vite also stops the runner it started.

Confirm health (optional):

```bash
curl http://127.0.0.1:8787/health
# {"status":"ok"}
```

Browser URL is usually `http://127.0.0.1:5173` (opened automatically). The UI content area widens with the browser window (up to ~1600px) so long paths and PATs are readable.

---

## 5. Step-by-step: first successful run

Steps 0–5 validate Excel parsing and planning **without** changing Azure DevOps; Step 6 is the live run.

### Preview plan vs Rehearsal only vs live run

Two controls never change Azure DevOps; they differ in how far they go:

| | **Preview plan** button | **Rehearsal only** checkbox + **Rehearse selected flow** | **Run selected flow (live)** (checkbox off) |
|---|---|---|---|
| What runs | Reads the workbooks once and builds the plan; no step code runs | Every selected step runs and logs what it *would* do (`[dry-run] …` lines) | Every selected step runs for real |
| Azure DevOps | Not contacted | Not contacted (the runner creates no ADO client) | Created / updated |
| Output | On-screen plan: step order, counts, warnings, errors | Event log + results card + preview files in the output folder (`rehearsal-summary.html`, `import-prevalidate.csv`, `import-preview.csv`) | Work items, process, project, … + all artifacts incl. `ado-id-map.csv` |
| Workflow cards | Unchanged | Shown **Skipped**; never marked complete | Marked **Completed** / **Failed** |
| Use it to | Check inputs — paths, names, release folders, mixed-release warnings | Check catalog cleanup (picklist fixes, stripped area paths, defaults) before a long import | Apply |

The checkbox only affects the run button — **Preview plan ignores it**. The run button label and the coloured note under the buttons always show which one you are about to do: **Run selected flow (live)** with a red "Live run: changes Azure DevOps org … · process … · project …" note, or **Rehearse selected flow** with an amber "Rehearsal" note.

Typical order: **Preview plan** → optional rehearsal (tick **Rehearsal only**, **Rehearse selected flow**) → untick → **Run selected flow (live)**.

In the API (§12) the checkbox is `apply_dry_run`, and Preview plan is `POST /plan/dry-run`.

### Step 0 — Launch

Double-click **Start BPCTool** and wait for the browser to open.

### Step 1 — Connection

1. Expand **1. Connection**
2. Enter:
   - **Org URL** — e.g. `https://dev.azure.com/contoso`, `https://contoso.visualstudio.com`, or `contoso`
   - **PAT** — kept in this browser session only (not persisted to disk); the field uses the full panel width
3. Confirm **Execution mode** is **Runner** (default)
4. Wait until the status chip shows **Ready**
5. Confirm **Multivalue: installed** (required). If **missing**, use **Install Multivalue extension** or install from the [Marketplace](https://marketplace.visualstudio.com/items?itemName=ms-devlabs.vsts-extensions-multivalue-control) as an org admin, then **Check** again. Process / layout / project runs are blocked until it is installed and enabled.

Optional but recommended:

- **Fetch existing projects**
- **Fetch existing processes**

These populate inventory used for create-vs-update policy.

### Step 2 — Process & project names

1. Open **2. Process & project names**
2. Type the **process name** you want to create or update (free text, not select-only)
3. Type the **project name** similarly
4. Optionally enter a **project description** (Azure DevOps project overview text). On create this is what ADO stores (empty is allowed). Older builds wrote `Project for process <guid>` — that is no longer used. Re-running **Project Creation** updates an existing project’s description when this field is non-empty.
5. Choose an **update policy**:

| Policy | Behavior |
|--------|----------|
| Require confirmation before update | If process/project already exists, you must check confirm boxes |
| Always update existing targets | Proceed with update/reuse |
| Skip steps for existing targets | Skip process/project phases when targets exist |
| Create only (fail if exists) | Fail planning/apply if targets already exist |

6. If policy requires it and the name matches inventory, check **Confirm process update** / **Confirm project update**

### Step 3 — Workflow selection

1. Open **3. Workflow selection**
2. Choose a run mode (default is **Selected step only**):

| Mode | Behavior |
|------|----------|
| **Selected step only** | Re-runs just the selected card; no prerequisite gating (useful to fix backlog/teams alone) |
| **Dependency-aware** | Runs through the selected card and its incomplete prerequisites |
| **Run from selected step onward** | Runs the selected card and every card after it, **including completed ones** — e.g. after a template change, start at Page Layout to redo Layout → Project → Teams → Backlog → Catalog → Report. Project and later cards still need Process + Layout completed (or included in the run) |
| **Full** | Runs all incomplete steps in engine order |

3. Select a workflow card when using Selected step only, Dependency-aware, or Run from selected step onward (the selected card shows **Starts here**)

### Step 4 — Run configuration

1. Open **4. Run configuration**
2. Paths are usually pre-filled when the page opens. Otherwise click **Load runner defaults**: it selects the newest release folder under `~/BPC Files` (or `BPCTOOL_CATALOG`), the template inside it, and the release name as Workbook version — see §2 Folder layout
3. Confirm paths (use **Browse…** for the local filesystem picker, or paste absolute paths):
   - **Template workbook path** — absolute path to the current quarter's ADO guideline `.xlsx` (not shipped with the app)
   - **Catalog source folder** — absolute path to the folder of catalog workbooks for the same release (BPC, Deliverables, Objectives, SbD, …)
   - **Workbook version / revision label** — the release label, e.g. `2026-Q3` (blank by default; used in fingerprinting)
4. Set options:
   - **Rehearsal only — run steps without changing Azure DevOps** — leave **unchecked** for the live run (default). Tick it only to rehearse; the run button then reads **Rehearse selected flow** and the catalog step still writes `import-preview.csv` and `import-prevalidate.csv` / `.json`, and the run writes `rehearsal-summary.html`.
   - **Convert Markdown large-text fields to HTML** — leave **unchecked** unless you want HTML conversion (see §8)
5. **Root area path** defaults to the **project name** (project root); override only if needed. Area path *children* still come from the Excel Area paths sheet.
6. **Run output folder** — where run results go (`<folder>/<org>_<project>/`). Leave empty for the default; keep the same folder for every run against a project.

**"Your Project Name Here" placeholder:** wherever a workbook's area or iteration path contains `Your Project Name Here` (any casing, optionally in `<…>` / `[…]`), BPCTool substitutes the **Project name** from the form — in the template's Area paths, Iteration paths and Teams *Backlog iteration*, and in catalog rows' **Area Path** / **Iteration Path**. Every substitution is reported in a highlighted line — *Project name applied: 'Your Project Name Here' → '<project>' in N template area/iteration rows and M catalog Area/Iteration Path values* — in Preview plan, the run log, the results card, and the HTML report; each catalog value is also a row in `import-prevalidate.csv` (value in spreadsheet → value used).

### Step 5 — Preview plan (safe)

1. Click **Preview plan** — this only reads the workbooks and plans; it never contacts Azure DevOps (and ignores the Rehearsal only checkbox)
2. Review:
   - Step order: `process → layout → project → teams → backlog → catalog → report`
   - Counts (enabled WITs, disabled WITs, fields, HTML fields, teams, backlogs, catalog rows, etc.)
   - The highlighted **Project name applied …** line, if the workbooks contain `Your Project Name Here`
   - Warnings/errors
   - **Catalog data checks** (when Catalog Import is selected): values that will be removed or shortened, with example file / row / value and how to fix each, plus a collapsed list of automatic fixes
3. Fix any blocking errors (missing sheets, confirmation required, etc.) before running. Data-check items don't block a run, but fixing them in the workbook avoids changed or dropped values

![Preview plan with the project-name line and Catalog data checks](./docs/images/ui-preview-plan.png)

### Step 6 — Live apply

1. Keep **Execution mode = Runner**
2. Confirm **Rehearsal only** is **unchecked** — the button reads **Run selected flow (live)** and the red note under the buttons names the org, process, and project that will change
3. Choose run mode and workflow card (see Step 3)
4. Click **Run selected flow (live)**
5. Watch the event log for real ADO progress (not `[dry-run] Would ensure…` messages). During Catalog Import a progress bar shows done/total, created/skipped/failed, and an estimated time remaining (then the same for parent-link backfill)
6. At the end of the run, the log includes **Run timing** with per-step durations and a **total**
7. When it finishes (success or not), the **results card** under the log shows the headline, what needs attention, and buttons for the report and CSVs; files are under `<Run output folder>/<org>_<project>/` (§11)

![Results card after a rehearsal: headline, project-name line, report and data-check buttons, what needs attention](./docs/images/ui-results-card.png)

If **Rehearsal only** is ticked, steps finish quickly with `[dry-run]` log lines and **nothing is created in the org**. That run also does **not** mark steps complete for dependency tracking.

### Optional — Rehearsal

Tick **Rehearsal only**, click **Rehearse selected flow**, and inspect the results card and preview files (`rehearsal-summary.html`, `import-prevalidate.csv`, `import-preview.csv`) without changing Azure DevOps. Untick it before the live run.

**Cancel:** in Runner mode, **Cancel run** asks the runner to stop the job (`POST /jobs/{id}/cancel`); the button shows **Cancelling…** until it stops. The runner stops at the next safe point: between steps, at the next progress message inside Process/Layout/Project/Teams/Backlog, and in Catalog Import after in-flight creates finish (they are still written to `ado-id-map.csv`). Backfill is skipped; the job ends as **cancelled**. Steps that finished before the cancel are marked complete; Catalog is not, so run it again to resume. In Simulate/API modes, Cancel stops the client-side flow.

**Page refresh:** if you reload the page while a Runner job is running, the UI reattaches to that job (same browser tab session) and replays its log. Restarting the runner process clears jobs, so there is nothing to reattach to.

---

## 6. UI sections reference

### 1. Connection

| Control | Purpose |
|---------|---------|
| Org URL | Accepts `dev.azure.com/{org}`, `{org}.visualstudio.com`, or bare org; normalized for API calls; session-only |
| PAT | Full-width field; Basic auth `:${pat}` for ADO and runner apply; Show/Hide; session-only |
| Fetch projects / processes | Optional inventory for update policy |
| Multivalue extension | **Required.** Auto-checks DevLabs Multivalue control on the org; Check / Install controls. Missing or disabled blocks process / layout / project |
| Execution mode | Simulate / API / Runner (see §7) |

### 2. Process & project names

Free-text names for create or update, optional **project description**, and update policy. Existing targets are assessed when inventory was fetched or names match known lists.

### 3. Workflow selection

Four run mode radios (Selected step only, Dependency-aware, Run from selected step onward, Full), the **Will run: …** plan line, and seven engine step cards with status overlays (running/completed/failed/skipped) and hints (**Starts here**, **In this run**, **Cached — will skip**). Completion is cached per org/process/project in `localStorage`.

### 4. Run configuration

Template/catalog paths (Browse…), **Run output folder** (Browse… / Use default; remembered in the browser), workbook version, **Catalog workers** (labelled **Threads** in Simulate/API), root area path, **Rehearsal only**, markdown conversion, **Preview plan** (plan preview with data checks), **Run selected flow (live)** / **Rehearse selected flow**, live/rehearsal note, catalog progress bar, **results card**, event log. Retry count and layout/backlog worksheet names only appear in Simulate/API modes; the runner reads sheet names from the template and handles retries itself.

The layout uses a wide content shell and full-width rows for long values (paths, PAT, org URL) so fields are not clipped beside unused white space.

---

## 7. Execution modes

| Mode | When to use | What Run does |
|------|-------------|----------------|
| **Runner** (default) | Real setup/import | Posts `/api/jobs` to local engine; Excel → IR → plan → apply |
| **API** | Prove PAT + inventory | Live ADO **reads** via `/ado-proxy`; not full setup |
| **Simulate** | UI / orchestration testing | Local timed stubs; no ADO writes; no Excel apply |

**Preview plan** always calls the local runner (`POST /api/plan/dry-run`). The runner is started automatically with the app.

---

## 8. Rich text (HTML vs Markdown)

Catalog Excel cells (Description, Agenda, Microsoft references, etc.) may contain:

- Real **HTML** (`<div><a href=...>`)
- **Markdown-like** plain text (`* bullet`, numbered lists, blank-line paragraphs)

### Default (recommended) — preserve Markdown

How large-text cells are handled:

- HTML cells → passed through unchanged
- Markdown-like cells → left as authored
- Empty Description → field omitted on create (no synthetic “Imported from … row N” text)
- On work-item create, runner also sends:

```text
/multilineFieldsFormat/{FieldRef} = Markdown
```

so Azure DevOps renders Markdown correctly (without this, Markdown often appears as plain text in HTML controls).

### Optional — Convert Markdown large-text fields to HTML

UI checkbox / API field `convert_markdown_to_html: true`:

- Markdown-like cells are converted to HTML (`<p>`, `<ul>`, `<li>`, links)
- No `multilineFieldsFormat=Markdown` op is emitted
- Existing HTML still passes through

Use this only when the target process/org expects HTML storage instead of Markdown multiline format.

---

## 9. Workflow steps (engine)

Hard sequence for a full run:

```text
process → layout → project → teams → backlog → catalog → report
```

Project (and later project-phase steps) cannot start until process + layout succeed — in Dependency-aware, Run from selected step onward, and Full runs — **unless** you use **Selected step only** to re-run a later card against an already-configured org.

| Step | ID | What it does |
|------|----|--------------|
| 1. Process Template | `process` | Create/update inherited process; WITs; picklists; custom fields; multi-select → suggested lists; disable Excel-disabled WITs |
| 2. Page Layout | `layout` | Add fields to WITs; pages/groups/controls; `HtmlFieldControl` for HTML; DevLabs multivalue control for Multi-select; `H` fields added without a visible control (skips disabled WITs) |
| 3. Project Creation | `project` | Create project bound to process (or reuse existing); set/update optional description |
| 4. Teams & Areas | `teams` | Create teams; area path tree; aggregate team area assignments (`includeChildren: false` unless Excel says otherwise) |
| 5. Backlog Config | `backlog` | Rename/create backlog levels; assign WITs; set defaults; iteration paths; team backlog/iteration settings |
| 6. Catalog Import | `catalog` | Import **all** matching catalog workbooks; Title 1..N parents; prevalidate; parallel create + resume + parent-link backfill |
| 7. Report | `report` | Write HTML/JSON summary under the run output folder (the summary is also written automatically at the end of every run) |

### Template sheets that drive process & backlog

| Sheet | Role |
|-------|------|
| **Work item types** | WIT definitions; `Custom work item type = Disabled` for Epic / Feature / User story; `Backlog name` maps enabled WITs to levels; field-label grid: **`X`** = field on the WIT and shown on the form; **`H`** = field on the WIT but **hidden** from the form (no control placed; an existing control, e.g. Completed Work on Task, is set hidden); blank = not on the WIT. The reference Script 2 ignored `H`; changing a cell from `H` to `X` shows the control again on the next Layout run. A **State** grid column (if present) means the State *field* applies to that WIT — it is **not** a list of allowed `System.State` values |
| **Backlogs** | Level names, type, color, default WIT, **Rename from** (`Epic`, `Feature`, `(new)`, `(rename)`) |
| **Fields** / **Picklists** | Custom fields and lists; **Multi-select field = Yes** → suggested picklist + multivalue UI (Application family, Products, Industries, …) |
| **Area paths** / **Teams** | Hierarchy + team mappings (L1–L4 hierarchy columns; project column skipped) |
| **Iteration paths** | Iteration tree created and assigned to teams in the backlog step |

### Catalog Import (step 6) in detail

Catalog Import is **one step for all catalog content** in the configured folder—not a BPC-only import.

| Topic | Behavior |
|-------|----------|
| **Sources** | Every `.xlsx` matching name hints (Business Process Catalog, Deliverables, Objectives, Delivery Plan, SbD); template/guideline names excluded |
| **Hierarchy** | Parent/child links follow **Title 1..N** columns (same model as [ADO CSV / BPC import guidance](https://learn.microsoft.com/dynamics365/guidance/business-processes/about-import-catalog-devops)). Title 1 = root; Title 2 child of prior Title 1; etc. |
| **Keys** | Process sequence ID / Microsoft ID are stored on the work item and used as external keys for linking lookups; they do **not** derive the parent outline |
| **Prevalidate (data checks)** | Before create (and on Rehearsal only runs; Preview plan shows the same checks): normalize multi-select tokens; **case-insensitive** picklist align to template casing; replace `Your Project Name Here` in Area / Iteration Path with the project name; rewrite the Area Path and Iteration Path project prefix to the target project; strip area paths that are not in the project, States not allowed for the type, and invalid single picklist values; shorten text over 255 characters; apply Fields-sheet **Default value** when a required applicable field is empty → `import-prevalidate.csv` / `.json` (see §15 *Catalog fails on Application family / Products / picklists*) |
| **Description** | Spreadsheet Description mapped to `System.Description` only when non-empty; empty → field omitted (no synthetic “Imported from … row N”) |
| **Create-only fields** | Successful creates are not field-updated on re-run. Keys already in `ado-id-map.csv` are **skipped** (resume). Delete the map (or use a clean project) to recreate |
| **Parallelism** | UI **Catalog workers** (1–16, default 4) → `catalog_parallel_workers`. Parent-aware: a child is queued as soon as its parent is created. Start with 2–8 to limit ATCPU/429. Each worker reuses a keep-alive HTTPS connection |
| **Parent-link backfill** | After create, ensures Hierarchy-Reverse for pairs in the id map. Rows whose `ado-id-map.csv` `ParentId` already matches were linked in the create call and are reported `already_linked` without another request; the rest are checked in parallel with the same worker count. Writes `backfill-links-report.csv` (`linked` / `already_linked` / `conflict_existing_parent` / `failed`) |
| **Create retries** | Creates are retried only when ADO rejected them (429/503). If the connection drops after a create was sent, the runner looks the item up (type + title + `MSBPC.microsoftid`): one match is adopted into the id map, no match is retried once, several matches are reported as possible duplicates in `import-failures.csv` / `.json` |
| **Log stats** | `created` / `skipped` / `linked` / `missing parent` / `failed` / `cancelled` / `reconciled` / worker count |
| **Smoke tests** | API `catalog_limit` or a **Rehearsal only** run to avoid a full ~15k-row live import |

**System.State:** Allowed values come from each work item type’s process state model in Azure DevOps (not the template Picklists sheet). Catalog rows often send `New`; that is valid for many Agile-style types but **invalid for Test Case** (prevalidate strips it). Live runs read each type's states from Azure DevOps and strip any other value it would reject (e.g. `Deprecated`); Preview plan and Rehearsal only can check only the Test Case rule. **Business approval state** is a separate custom picklist.

**Example Backlogs sheet (test fixture):**

| Backlog name | Type | Default WIT | Rename from |
|--------------|------|-------------|-------------|
| Highest | Portfolio | Functional area | `(new)` |
| Kanban | Portfolio | Test Case | `(new)` |
| Levels | Portfolio | Process | `Epic` |
| Lowest | Portfolio | Scenario | `Feature` |
| Deliverables | Requirements | Configuration | `(rename)` |
| Tasks | Iteration | Task | `(rename)` |

Disabled WITs remain in the IR so Process can materialize + `isDisabled`. Layout and backlog assignment skip them. If ADO rejects a disable PATCH, set **Disabled** on that WIT in Organization Settings → Process.

If an older apply created custom **Levels** / **Lowest** while leaving system **Epics** / **Features**, re-run **Backlog Config** — the engine removes the duplicate custom levels and renames the Agile behaviors to match Excel.

---

## 10. Spreadsheet deltas & fingerprints

**Workbook version** is a label for traceability and change detection. It does not change what is created or imported, and it is never written to Azure DevOps.

- **Runner fingerprint** — a hash of the template file's contents plus the label (e.g. `sha256:39d2f0ca4f206785::2026-q4`). Shown at the top of Preview plan and as *Workbook fingerprint* in the HTML/JSON report, so you can tell which template and release a run used
- **Browser check** — after a successful run, the browser records the template path and label for that org + process in `localStorage` (`bpcWorkbookApplies`). If either differs next time, Process & project names shows *New or changed spreadsheet detected*, and with **Require confirmation before update** a Page Layout run on the existing process asks for confirmation; otherwise it shows *Workbook matches the last applied revision*
- The browser check compares path + label, not file contents: if you overwrite a template in place, change the label too (the runner fingerprint changes either way)

**What a re-run actually updates** (updated spreadsheet ≠ full overwrite):

| Step | On subsequent run |
|------|-------------------|
| **Process / layout** | Adds missing WITs/fields/controls; limited field metadata PATCH; not a full process rewrite |
| **Project** | Reuses existing; updates description when the UI field is non-empty |
| **Teams / backlog** | Upsert/heal areas, behaviors, iterations, assignments |
| **Catalog** | **Create-only fields** — keys in `ado-id-map.csv` are skipped (no WIP field refresh). New keys create; parent-link backfill can still fix missing Hierarchy-Reverse |
| **Report** | Regenerates local HTML/JSON |

### Moving to a new quarterly release

1. Create a new release folder (e.g. `~/BPC Files/2026-Q4/`) and put the new template guideline and catalog workbooks in it — never add them to the previous release's folder. Optionally move older releases under `_archive/`.
2. Click **Load runner defaults** — with `YYYY-Qn` folder names it selects the new folder and template and pre-fills **Workbook version** (or set the paths with Browse…).
3. Confirm **Workbook version** is the new release label (e.g. `2026-Q4`); the fingerprint change flags the spreadsheet delta. Keep the same output folder — the existing `ado-id-map.csv` is what makes the new release skip items already created.
4. Run **Preview plan** and read warnings/errors before any live apply — sheet or column changes in a new release show up here first.
5. Apply. Structure steps add what is new; catalog creates only keys not already in `ado-id-map.csv`. Changed field values on existing catalog rows, and fields/controls dropped from the template, are **not** propagated (see table above).

---

## 11. Outputs and artifacts

Root: `<Run output folder>/<org>_<project>/` — the folder chosen in Run configuration, else `$BPCTOOL_OUTPUT_DIR`, else `bpctool/runner-out` (see §2 Folder layout). One folder per org + project, shared by every release and re-run — back it up and keep it.

| Artifact | When |
|----------|------|
| `bpc-ado-setup-summary.html` / `.json` | **Every live run** (success, failure, or cancel) — headline, what needs attention, step table, file list. Steps not run this time keep their last result from earlier runs of the same process/project |
| `rehearsal-summary.html` / `.json` | Every Rehearsal only run (kept separate so it never overwrites the live summary) |
| `import-failures.csv` | Live catalog run with failures — one row per failed item, opens in Excel: **Fix this row** vs **Blocked by parent**, plain-language problem, how to fix, source file + row, value tried, children blocked |
| `import-failures.json` | Same data for tools: `{runId, generatedAt, summary, failures}` (was a bare list before 2026-10) |
| `import-prevalidate.csv` | Catalog step (including Rehearsal only) — every value changed or removed before import, **Needs review?** rows first, with source file + row, value in spreadsheet, value used, how to fix |
| `import-prevalidate.json` | Same checks as counts + examples, split into `automaticFixes` and `needsReview` |
| `import-preview.csv` | Catalog step (including Rehearsal only runs) — sample drafts |
| `ado-id-map.csv` | Live catalog import — `Key`, `WorkItemId`, …; **appended** across runs for resume |
| `backfill-links-report.csv` | Parent-link backfill statuses after catalog create |

Every file written by a run carries the same run id (`runId`, the runner job id) and `generatedAt`, so you can tell whether the summary and the failures file came from the same run.

**Results card.** When a run finishes, the UI shows a card under the run log with the headline, buttons to open the report and download the CSVs (served by the runner at `GET /outputs/{folder}/{file}`; only the files above), **What needs attention** (largest problems first, with example rows and the fix), a step list, and the automatic fixes. If catalog rows failed, **Set up Catalog Import re-run** selects Catalog Import as a single live step — `ado-id-map.csv` makes the re-run skip everything already created.

`runner-out/` is gitignored. After a catalog run, the event log also shows `Data checks: …`, resume/worker messages, `Parent-link backfill…`, `N row(s) failed and blocked M child row(s)`, and `Catalog import finished: created …, skipped …, linked …`. Every apply/simulate/API run ends with a **Run timing** block (per executed step + total).

---

## 12. Local runner API

Base URL (direct): `http://127.0.0.1:8787`  
Via UI proxy: `/api/...`

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness |
| GET | `/defaults` | Newest release folder + template, `release_label`, `bpc_files_root`, `output_root` |
| POST | `/plan/dry-run` | Parse Excel → IR → plan (no mutations) — UI **Preview plan**; includes `data_checks` when Catalog Import is selected |
| POST | `/ir/parse` | Return full IR JSON |
| POST | `/jobs` | Create a plan-only, rehearsal (`apply_dry_run`), or live apply job |
| GET | `/jobs/{id}?since=N` | Poll job status/results; `since` returns only events from index N (`event_offset` / `event_total` in the response) |
| POST | `/jobs/{id}/cancel` | Request a cooperative stop; status becomes `cancelled` |
| GET | `/outputs/{folder}/{file}?root=` | Open/download a run output (summary HTML/JSON, failures / data-check CSV/JSON); `root` = the run output folder used (absolute; default output root when omitted); other file names are refused |
| GET | `/fs/roots`, `/fs/list` | Local path browser used by Browse… |

### Job create body (important fields)

```json
{
  "org_url": "https://dev.azure.com/contoso",
  "pat": "<required for apply>",
  "process_name": "Business Process Catalog",
  "project_name": "Contoso-BPC",
  "project_description": "Optional overview text for the Azure DevOps project",
  "excel_file": "/absolute/path/to/ADO template guideline.xlsx",
  "catalog_source_dir": "/absolute/path/to/BPC Files",
  "workbook_version": "2026-Q3",
  "update_policy": "always-update",
  "confirm_process_update": false,
  "confirm_project_update": false,
  "known_process_exists": false,
  "known_project_exists": false,
  "root_area_path": "Contoso-BPC",
  "mode": "apply",
  "apply_dry_run": true,
  "convert_markdown_to_html": false,
  "steps": null,
  "catalog_limit": null,
  "catalog_parallel_workers": 4,
  "output_root": null
}
```

| Field | Notes |
|-------|-------|
| `project_description` | Optional; set on create; PATCH on existing project when non-empty |
| `mode` | `dry-run` = plan only; `apply` = run writers |
| `apply_dry_run` | With `mode=apply`, run writers without ADO HTTP calls — UI **Rehearsal only** |
| `convert_markdown_to_html` | Convert markdown-like text to HTML; default `false` (preserve markdown) |
| `steps` | Optional subset, e.g. `["backlog"]` or `["catalog","report"]` |
| `catalog_limit` | Cap drafts for smoke tests |
| `catalog_parallel_workers` | Parent-aware Catalog Import and backfill workers (1–16; UI **Catalog workers**; default 4) |
| `root_area_path` | Defaults to project name when omitted/empty in the UI |
| `output_root` | Absolute folder for run outputs (UI **Run output folder**); results go to `<output_root>/<org>_<project>/`. Omit / `null` for `BPCTOOL_OUTPUT_DIR`, else `bpctool/runner-out` |

Job results include `apply_result.outcome` — the same headline, notices, attention items, steps, and file list the UI results card shows. Preview plan responses include `notices` and, when Catalog Import is selected, `data_checks`.

Apply jobs run in a background thread; poll `GET /jobs/{id}?since=<events received>` until `status` is `succeeded`, `failed`, or `cancelled`. Catalog Import emits `catalog-progress` events (`phase` create/backfill, `done`, `total`, counts, `elapsedMs`) about once a second.

### Example: rehearsal (`apply_dry_run`) via curl

```bash
curl -s -X POST http://127.0.0.1:8787/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "org_url": "https://dev.azure.com/contoso",
    "pat": "012345678901234567890123456789",
    "process_name": "Business Process Catalog",
    "project_name": "Contoso-BPC",
    "project_description": "BPC sandbox project",
    "excel_file": "/Users/you/BPC Files/2026-Q4/ADO template guideline.xlsx",
    "catalog_source_dir": "/Users/you/BPC Files/2026-Q4",
    "update_policy": "always-update",
    "mode": "apply",
    "apply_dry_run": true,
    "convert_markdown_to_html": false,
    "catalog_limit": 25
  }'
```

Then poll `/jobs/{id}` from the response.

---

## 13. Architecture (for operators)

```text
React UI (Vite)
  ├─ /ado-proxy       → Azure DevOps (browser reads)
  ├─ /extmgmt-proxy   → Extension Management (Multivalue check/install)
  ├─ /fs              → Local filesystem browser
  └─ /api             → Local runner :8787
                      ├─ excel_ir.py         Excel → IR (keeps disabled WITs)
                      ├─ planner.py          IR → plan (Preview plan)
                      ├─ richtext.py         HTML detect / optional MD→HTML
                      ├─ catalog_import.py   Drafts, Title 1..N parents, multiline flags
                      ├─ catalog_runtime.py  Parallel create, id-map resume, parent backfill
                      ├─ catalog_validate.py Data checks (prevalidate) before create
                      ├─ failure_explain.py  Plain-language failure causes + fixes
                      ├─ run_outcome.py      Headline / attention / files for report + results card
                      ├─ paths.py            Release folders, output root
                      ├─ mapping.py          Catalog headers → field refs
                      ├─ ado_client.py       REST client + retries + Multivalue / parent links
                      ├─ org_url.py          Org URL normalize/parse
                      ├─ fs_browser.py       Path picker backend
                      ├─ apply_engine.py     Step orchestration (+ Multivalue gate)
                      └─ writers/*           process, layout, project, teams, backlog, catalog, report
```

Key design rules:

- Browser never owns long write jobs; runner does
- Process + layout before project (full/dependency runs)
- **DevLabs Multivalue extension is required** on the org before process / layout / project
- Excel is authoring; IR is the run source of truth
- Catalog parents follow Title outline; sequence IDs are keys only
- Catalog create is parent-aware parallel + resume + Hierarchy-Reverse backfill
- Multi-select uses suggested-picklist + DevLabs Multivalue control pattern
- Empty Description is omitted (not invented)
- No subprocess calls to the reference scripts
- Launcher replaces stale `:8787` and starts uvicorn with `--reload`

---

## 14. Testing

```bash
# Frontend unit tests
npm test

# Runner unit/integration tests (needs user template via BPCTOOL_TEMPLATE or catalog folder)
cd runner && ../.venv/bin/pytest -q

# Lint / production build
npm run lint
npm run build
```

Notable runner coverage includes Excel IR (disabled WITs, backlogs, project-name placeholder), backlog rename/heal + WIT assignment, team area aggregation, team iterations / backlogIteration GUID, org URL normalize, layout booleans / multivalue control type, project description, Title-outline catalog parents, catalog data checks (area / iteration / state / length / picklists), failure explanations, run outcome + report, output folders, an end-to-end rehearsal, and multi-select field labels. UI tests cover run-mode step resolution (including Run from selected step onward).

---

## 15. Troubleshooting

### Runner unreachable / Preview plan fails

**Symptom:** “Failed to reach local runner” or fetch to `/api/...` errors.

**Fix:**

1. Quit the Start BPCTool window and relaunch (or `npm start`)
2. On first use, wait for setup to finish creating `.venv`
3. Confirm `curl http://127.0.0.1:8787/health`
4. Ensure nothing else owns port `8787`
5. Run `npm run setup` once if the venv was never created

### Port already in use

```bash
# find / stop prior uvicorn, then relaunch the app
lsof -i :8787
pkill -f 'uvicorn app.main:app'
# Double-click Start BPCTool, or: npm start
```

### Template missing sheets

**Symptom:** `Excel template is missing required sheets: ...`

Required sheets:

- Work item types
- Fields
- Picklists
- Area paths
- Teams
- Backlogs
- Iteration paths

Use the current quarter's **ADO template guideline** workbook, not a catalog file, as the template path.

### Catalog folder empty / 0 rows

**Symptom:** Catalog step skipped or warning about missing sources.

**Fix:**

- Point **Catalog source folder** at the release folder containing the catalog `.xlsx` files (BPC, Deliverables, Objectives, SbD — all are imported together), e.g. `~/BPC Files/2026-Q4` — not the `BPC Files` root when releases live in subfolders (Preview plan warns about this)
- Filenames must include a recognized hint (see §2); rename if needed
- Paths must be absolute and readable by the Python process (not only the browser)
- Close Excel if files are locked (`~$` temp files are ignored)
- Confirm Preview plan shows a non-zero **catalog rows** / **catalog files** count

### Update confirmation required

**Symptom:** **Preview plan** and **Run** are disabled with “already exists. Confirm update…” under section 2, or the plan reports **Plan blocked** with the same message.

**Why:** Preview plan does not call Azure DevOps itself. It uses the inventory you loaded with **Fetch existing projects / processes** (section 1). If a typed name matches that inventory and the policy is **Require confirmation** (or **Create only**), the runner rejects the plan. Rehearsal and live runs apply the same check.

**Fix:** Tick the confirm-update box(es), or switch the policy to **Always update** / **Skip existing**.

### PAT / 401 / 403 on live apply

**Fix:**

- Regenerate PAT with process + project + work item scopes
- Confirm org URL matches the org the PAT belongs to
- Use **API** mode + Fetch projects as a quick credential check before Runner apply
- `Azure DevOps returned a sign-in page (HTTP 203)` means the PAT is invalid, expired, or missing scopes
- Behind a corporate proxy, the runner uses `HTTPS_PROXY` / `NO_PROXY` (or macOS system proxy settings); `http://user:pass@host:port` proxy URLs are supported

### Throttling (429 / 503)

Runner retries with jittered backoff and honours `Retry-After`. Reduce **Catalog workers** / rerun Catalog Import — resume skips keys already in `ado-id-map.csv`. Review `backfill-links-report.csv` if hierarchy links are missing.

### Markdown shows as plain text in ADO

You likely converted incorrectly, or multiline format was not applied:

1. Prefer **default preserve** (checkbox off)
2. Re-import affected items, or manually set field format to Markdown in ADO
3. If you intentionally converted to HTML, content should contain `<p>` / `<ul>` tags

### Layout / HTML controls fail

Some inherited WIT layouts can be locked. Check runner events for layout warnings. Ensure process step created/customized WITs before layout.

### Project create hangs

ADO project creation is asynchronous. The runner polls for several seconds. If it times out, verify the project in the org UI and rerun with **skip-existing** or **always-update**.

### Project description still shows “Project for process …”

That text came from older creates. Enter the desired text in **Project description** and re-run **Project Creation** (Selected step only). New creates never use the process GUID string.

### Browser path picker only gave a file name

Use **Browse…** (local runner filesystem picker) or paste a **full absolute path**. System/browser dialogs often return only a short name like `BPC Files`, which the runner then resolves relative to its own folder and fails.

### Rehearsal still seemed to call ADO

Current engine creates no ADO client when `apply_dry_run` is true. If you see ADO traffic, confirm the job body has `"apply_dry_run": true` and relaunch Start BPCTool / `npm start` to pick up code changes.

### Teams step reported 0 assignments / Areas show no Teams

1. Confirm **Rehearsal only** is **unchecked** for a live run (button reads **Run selected flow (live)**). A rehearsal never PATCHes `teamfieldvalues` (event log will say `No Azure DevOps teamfieldvalues were changed`).
2. Quit and relaunch Start BPCTool / `npm start` after pulling code changes — the UI replaces any stale process on port `8787` and starts the runner with `--reload`.
3. Re-run the **Teams & areas** card only. The log should show many `Assigned team '…' → …` lines and finish with `N team area assignments` (fixture ≈ 47).

### Team iteration paths empty in Azure DevOps

Iteration **nodes** are created in the backlog step; **team** iteration membership (and backlog iteration / bug behavior) is also applied there (reference Script 4).

If the team Iterations page shows **Default iteration = @CurrentIteration** but **Backlog iteration** is blank (and Select iteration is blocked), the backlog step set the macro without a root iteration GUID. Re-run **Backlog configuration** with **Selected step only** after relaunching the app so the runner reloads. Expect:

- `Iteration root GUID … (N child iteration(s) to assign)`
- `Updated team settings for '…': … (backlogIteration=<guid>)`
- `Added N iterations to team '…'`

### Backlog levels wrong / leftover “Epics” or “Features”

Excel expects **Levels** / **Lowest** (renamed from Epic/Feature), not a parallel custom level beside system Epics/Features.

1. Relaunch the app so the runner reloads
2. Re-run **Backlog Config** with **Selected step only**
3. Expect logs like `Removing duplicate custom backlog 'Levels'…` and `Renamed behavior 'Epics' → 'Levels'`
4. Confirm Process → Backlog levels matches the **Backlogs** sheet (Highest, Kanban, Levels, Lowest, Deliverables, Tasks)

### Epic / Feature / User story still enabled

Process attempts to materialize then disable Excel-disabled WITs. If the API rejects disable, set **Disabled** manually in Organization Settings → Process. Layout/backlog do not treat them as active types.

### Catalog work items have no parent/child links

Parent links follow **Title 1..N** (ADO CSV / [BPC import guidance](https://learn.microsoft.com/dynamics365/guidance/business-processes/about-import-catalog-devops)), not Process sequence ID. Only Hierarchy-Reverse is created (same as the reference scripts).

If many items are unlinked:

1. Open `import-failures.csv` and filter **Status = Fix this row** — children show **Blocked by parent** (with the parent key) when the parent never got an id; fixing the parent row unblocks them
2. Review `backfill-links-report.csv` — run Catalog again to resume creates and backfill missing links
3. Confirm the log shows `linked` / backfill counts; for a full rebuild after process/layout fixes, use a clean project or delete prior imports + `ado-id-map.csv`

### Catalog fails on Application family / Products / picklists

Template fields with **Multi-select = Yes** are created as suggested picklists so values like `Business Central; Finance and Operations` can be stored (DevLabs multivalue model).

**Required:** The [DevLabs Multivalue control](https://marketplace.visualstudio.com/items?itemName=ms-devlabs.vsts-extensions-multivalue-control) must be installed and enabled on the organization. Process / layout / project setup will not run without it.

**Preflight:** Connection checks the extension when URL + PAT are set. Running process / layout / project prompts to install if missing. If you decline or the PAT cannot install org extensions, setup is blocked until the extension is available.

**Fix sequence for an existing org:**

1. Use **Install Multivalue extension** in Connection (or install [Multivalue control](https://marketplace.visualstudio.com/items?itemName=ms-devlabs.vsts-extensions-multivalue-control) as an org admin)
2. Re-run **Process Template** (updates `isSuggested` / `isPicklistSuggested`) then **Page Layout** (binds multivalue control)
3. Re-run **Catalog Import** on a clean project

Catalog always runs **data checks** (prevalidate) first — `import-prevalidate.csv` lists every change, `import-prevalidate.json` the counts. **Preview plan** shows the same checks (from the workbooks only) in a **Catalog data checks** panel, so you can fix the spreadsheet before any run:

| Action | Examples |
|--------|----------|
| Automatic fix (no action needed) | Fields-sheet **Default value** applied to an empty required field (e.g. Catalog status → `10 - New`); picklist **casing** aligned to the template (e.g. `Organization Administration` → `Organization administration`); Area Path and Iteration Path project prefix rewritten to the target project (`MSBPCProj\…` → `Contoso-BPC\…`, `MSBPCProj` → `Contoso-BPC`; iteration values are never removed); `Your Project Name Here` in Area / Iteration Path replaced with the project name; State casing aligned (live runs) |
| Removed — needs review | `Area Path` not in the project (TF401347) or `Not found`; `State` not allowed for the type (e.g. `Deprecated`; live runs read the allowed states from Azure DevOps, Test Case `New` always); invalid **single** picklist values |
| Shortened — needs review | Text longer than 255 characters in a string / picklist field or Title (TF401324) — cut to 254 + `…`; multi-select keeps whole values |
| Report only | Required empty with **no** template default (and the value wasn't removed above); unknown multi-select tokens |

Anything Azure DevOps still rejects after the checks lands in `import-failures.csv` with a plain-language problem and fix.

### Recommended full setup after template/catalog updates

1. **Preview plan** — confirm catalog file/row counts  
2. **Process** → **Layout** → **Project** → **Teams** → **Backlog** (Full or Dependency-aware; after a template change, **Run from selected step onward** from the first affected card)  
3. Confirm Connection shows **Multivalue: installed** (or accept the Run-time install prompt)  
4. **Catalog Import** (Selected step only is fine once the project exists)  
5. Review the results card (or `bpc-ado-setup-summary.html`), then `import-failures.csv` and `import-prevalidate.csv` for anything flagged  

Use a **Rehearsal only** run + optional `catalog_limit` (API) for a smoke test before a full ~15k-row import.

### Completion cache looks wrong

Completion is stored per org/process/project key in `localStorage`. Use **Clear completion cache**, clear site data for localhost, or change process/project names if you need a clean slate. **Selected step only** ignores completion for the selected card.

---

## 16. Security notes

- PAT is kept in **sessionStorage** only (not persisted to disk)
- Prefer least-privilege PATs and rotate after bulk imports; extension install needs org extension-management rights
- Runner binds to `127.0.0.1` by default (local only)
- Do not commit `.venv/`, `runner-out/`, or files containing PATs

---

## 17. Known limitations

- Apply writers follow the template guideline workbook layout closely, but are not a line-for-line port of every reference-script edge case. A new quarterly release that renames sheets or columns needs a BPCTool update — run **Preview plan** first on each new release
- **DevLabs Multivalue extension is required** for process / layout / project (Connection preflight + optional API install; Marketplace/admin if the PAT cannot install). Layout binds the Multivalue form control for Multi-select fields
- Disabling inherited system WITs via the public Process API can fail; manual disable in the ADO UI may still be required
- `System.State` allowed values are owned by ADO process WIT models — not authored in the template Picklists sheet
- Some Deliverables source columns (e.g. Job purpose / Job type / Data type) may not align with template picklists; prevalidate strips or reports but does not rewrite Microsoft source data
- Catalog **Iteration Path** values only get their project name fixed; they are not checked against the project's iterations. **State** values are checked against Azure DevOps on live runs only
- Catalog import of ~15k rows (all matching workbooks) is long-running; use a **Rehearsal only** run + `catalog_limit` for smoke tests; tune **Catalog workers** (2–8 typical)
- Catalog import is **create-only** for fields (no WIP upsert); **resume** skips keys in `ado-id-map.csv` and can backfill parent links. Updated spreadsheet rows do **not** refresh existing work item fields
- Catalog still uses one REST create per work item (parent-aware parallel, keep-alive connections); no WIT `$batch`
- Backfill trusts `ParentId` recorded in `ado-id-map.csv`; a parent changed by hand in ADO after create is not re-checked for those rows
- Only Hierarchy-Reverse parent links are created (same as the reference scripts — no Related / Predecessor, etc.)
- Job store is in-memory; restarting the runner clears job history (and anything to reattach to after a page refresh)
- Cancel is cooperative: a single long ADO request (e.g. one layout call) finishes before the job stops
- Some inherited layout surfaces can reject control updates; check layout warnings in the event log
- Re-running Process may log `Field 'MSBPC.*' warning: ADO 404` when org-scoped fields already exist (Update API is lock/undelete only); fields remain usable — Layout binds them to WITs
- **Simulate** / **API** modes remain for orchestration stubs and ADO reads; live apply is **Runner** only. Retry count and layout/backlog sheet names are Simulate/API-only and hidden in Runner mode.

---

## 18. Quick reference card

```text
Double-click: Start BPCTool.command  (macOS)
           or Start BPCTool.bat      (Windows)

In the browser:
  1. Connection → Ready (Runner mode); org URL + PAT are session-only
     Confirm Multivalue: installed (required for process/layout/project)
  2. Process + project names (+ optional description)
  3. Workflow: Selected step only / Dependency-aware / From selected step onward / Full
  4. Load runner defaults → Preview plan (check catalog files/rows)
  Preview plan never changes ADO; "Rehearsal only" ticked = Rehearse selected flow
  Rehearsal only UNCHECKED → Run selected flow (live) — red note names the target
  After run: check Run timing (per step + total) in the event log
  After any run: results card → Open report; Download failures / data checks
  Keep ado-id-map.csv — a Catalog re-run resumes from it
```

Developer equivalent: `npm run setup` once, then `npm start` each session.

Defaults:

- Folders: `~/BPC Files/<YYYY-Qn>/` per release (template + catalog workbooks); override root with `BPCTOOL_CATALOG` in `bpctool.env`
- Template: user-provided ADO guideline `.xlsx` in the release folder (not bundled; or `BPCTOOL_TEMPLATE`)
- Catalog folder: newest release folder (BPC + Deliverables + Objectives + SbD)
- Outputs: `<Run output folder>/<org>_<project>/` (default `BPCTOOL_OUTPUT_DIR`, else `runner-out/`) — keep `ado-id-map.csv`
- `Your Project Name Here` in area / iteration paths → the project name (reported in the results)
- Root area path: project name
- Markdown: preserved unless “Convert Markdown…to HTML” is checked
- Empty Description: omitted (no synthetic import placeholder)
- Run mode: Selected step only
- Catalog workers: 4 (try 2–8)
- Catalog parents: Title 1..N outline; resume + parent-link backfill; Multi-select: suggested picklists + **required** DevLabs Multivalue extension
