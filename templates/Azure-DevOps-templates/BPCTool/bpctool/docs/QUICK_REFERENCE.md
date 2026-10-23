# BPCTool quick reference

One page for day-to-day use. Details: [User Guide](../USER_GUIDE.md).

## Start and stop

| | |
|---|---|
| **Start** | Double-click `Start BPCTool.command` (macOS) or `Start BPCTool.bat` (Windows). The browser opens when the runner is ready (first launch installs dependencies, about a minute) |
| **Stop** | Close the Start BPCTool window |
| **From a terminal** | `cd bpctool` → `npm run setup` once → `npm start` |
| **Needs** | Node.js 20.19+ or 22.12+, Python 3.11+, the release's template and catalog `.xlsx` files (not bundled) |

## Before a run

- **PAT** — create one with *Custom defined* scopes for what you'll run:

  | Run | Work Items | Project and Team | Extensions |
  |-----|------------|------------------|------------|
  | Rehearsal only | Read | Read | Read |
  | Catalog Import into an existing project | Read & write | Read | — |
  | Full setup | Read, write, & manage | Read, write, & manage | Read |
  | Install Multivalue from the app | — | — | Read & manage |

  The PAT is kept in the browser tab's session storage until the tab closes. Use a short-lived one.
- **Multivalue extension** — Connection must show **Multivalue: installed** before Process, Page Layout or Project runs.
- **Folders** — one folder per quarterly release, template and catalog workbooks together (`~/BPC Files/2026-Q4/`). Close the workbooks in Excel.

## The run, in order

1. **Connection** — org URL (`https://dev.azure.com/contoso`, `contoso.visualstudio.com` or `contoso`) + PAT; wait for **Ready**.
2. **Process & project names** — plus optional project description and the update policy.
3. **Workflow selection** — run mode + the card to start from.
4. **Run configuration** — check the pre-filled template, catalog folder and workbook version (**Load runner defaults** refills them); optional Run output folder.
5. **Preview plan** — fix any errors; review the Catalog data checks.
6. Optional: tick **Rehearsal only** → **Rehearse selected flow**.
7. Untick **Rehearsal only** → **Run selected flow (live)**. The red note names the org, process and project that will change.
8. Read the **results card**: headline, *What needs attention*, report and CSV buttons.

## Which button changes what

| | Azure DevOps | Writes files | Marks cards complete |
|---|---|---|---|
| **Preview plan** | Not contacted | No | No |
| **Rehearse selected flow** (*Rehearsal only* ticked) | Read only (Catalog Import step) | Yes — `rehearsal-summary.html`, previews, change report | No |
| **Run selected flow (live)** | Created / updated | Yes — all reports and `ado-id-map.csv` | Yes |

## Run modes

| Mode | Runs |
|------|------|
| **Selected step only** (default) | Just the selected card, even if completed |
| **Dependency-aware** | The selected card plus incomplete steps before it |
| **Run from selected step onward** | The selected card and every later card, including completed ones — use after a template change |
| **Full** | All incomplete steps in order |

Steps: **1** Process Template → **2** Page Layout Setup → **3** Project Creation → **4** Teams & Areas Setup → **5** Backlog Configuration → **6** Catalog Import → **7** HTML/JSON Report. Project and later steps need Process Template and Page Layout done first (except in Selected step only).

## Update policy (existing process or project)

| Policy | When the target exists |
|--------|------------------------|
| Require confirmation before update | Tick **Confirm process / project update** to continue |
| Always update existing targets | Updates / reuses it |
| Skip steps for existing targets | Skips its steps |
| Create only (fail if exists) | Stops |

## Results folder

`<Run output folder>/<org>_<project>/` — default `BPCTOOL_OUTPUT_DIR`, else `bpctool/runner-out/`. Keep it between runs and releases.

| File | Use it for |
|------|------------|
| `bpc-ado-setup-summary.html` / `rehearsal-summary.html` | The run report |
| `import-failures.csv` | Rows that failed — **Fix this row** vs **Blocked by parent**, with how to fix |
| `import-prevalidate.csv` | Values changed or removed before import |
| `import-changes.csv` | Rehearsal: what differs between the workbook and the existing project |
| `ado-id-map.csv` | **Keep.** Lets a re-run skip items already created — losing it means duplicates |
| `bpctool-target.json` | Which org + project the folder belongs to |

- Another project whose name gives the same folder name gets `<org>_<project>-<code>`.
- Before any step, a run checks that `ado-id-map.csv` lists this project's work items. A run with Catalog Import stops if they belong to another project or no longer exist (project deleted and recreated) — move the file aside or pick another folder.
- Reports contain catalog content: don't post them publicly; delete folders you no longer need (but keep `ado-id-map.csv` while the project may be re-imported).

## Common problems

| Symptom | Fix |
|---------|-----|
| *Can't reach the local runner* | Wait for `[bpc-runner] Ready.` in the Start window; otherwise relaunch. Python missing → install 3.11+, `npm run setup` |
| *Port 8787 is in use by another program* | Close that program, then relaunch |
| 401 / 403 / *sign-in page (HTTP 203)* | PAT expired, wrong org, or missing scopes (table above) |
| *Process step: … could not be created* | Usually PAT scopes or process permissions; fix, then re-run Process Template |
| *Confirm update* / *Plan blocked* | **Fetch existing processes / projects**, tick the confirm boxes, or change the policy |
| *A run is already in progress* | Another tab is running the same project (or one with the same results folder name) — wait or cancel it |
| *ado-id-map.csv … lists work items from project …* / *… exist in Azure DevOps any more* | Move `ado-id-map.csv` out of the results folder (keep a copy) or choose another Run output folder |
| Catalog folder: 0 rows | Point at the release folder (e.g. `2026-Q4`), not the `BPC Files` root; use absolute paths |
| Multi-select values fail | Install Multivalue, re-run Process Template then Page Layout, then Catalog Import |
| Items without parents | `import-failures.csv` (*Blocked by parent*), `backfill-links-report.csv`; re-run Catalog Import to resume |
| 429 / 503 throttling | Lower **Catalog workers** and re-run Catalog Import — it resumes |
| Completion marks look wrong | **Clear completion cache** |
| Path picker returned only a name | Use **Browse…** or paste a full absolute path |

## Developer commands

Same in Terminal, PowerShell and Command Prompt (run in `bpctool/`):

| Command | Does |
|---------|------|
| `npm start` | UI + runner, opens the browser |
| `npm run dev` | Same, runner reloads on code changes |
| `npm run runner` | Runner API only (`127.0.0.1:8787`) |
| `npm test` | UI tests |
| `npm run runner:install-dev` → `npm run runner:test` | Install pytest once, then run the runner tests |
| `npm run lint` / `npm run build` | Lint / production build |

Folder settings: copy `bpctool.env.example` to `bpctool.env` and set `BPCTOOL_CATALOG`, `BPCTOOL_TEMPLATE` or `BPCTOOL_OUTPUT_DIR`; restart.
