# Business Process Catalog Azure DevOps setup package - June Preview

This June Preview package combines the Azure DevOps setup scripts, the resumable Business Process Catalog work item importer, and a deterministic HTML run summary report.

Use this package to create or update the Azure DevOps process/project configuration and import the Business Process Catalog source workbooks into Azure DevOps Boards.

## Phases

| Phase | Purpose | Script |
| ---: | --- | --- |
| 1 | Create process, project, work item types, fields, picklists, and Test Case `New` state | `1_ADO_Creation_Script (Preview).py` |
| 2 | Configure work item page layouts and DevLabs Multivalue controls | `2_ADO_Page_Layout_Script_Threaded (Preview).py` |
| 3 | Create teams, area paths, and team area assignments | `3_ADO_Teams_Areas_Script (Preview).py` |
| 4 | Configure backlog levels, iterations, and team settings | `4_ADO_Backlog_Config_Script (Preview).py` |
| 5 | Import Business Process Catalog work items | `5_BPC_Catalog_Import.py` |
| 6 | Generate deterministic HTML setup/import summary report | `6_Generate_HTML_Report.py` |

## Install dependencies

Python 3.12 or later is recommended.

```powershell
python -m pip install -r requirements.txt
```

> [!TIP]
> A Python virtual environment is optional. Use one if you want to isolate this package's dependencies from other Python tools on the machine. For Windows guidance, see [Creation of virtual environments](https://docs.python.org/3/library/venv.html#creating-virtual-environments). After creating and activating a virtual environment, use the same commands shown in this README.

## Run all phases

```powershell
python setup_wizard.py `
  --ado-org-url "https://dev.azure.com/<organization>" `
  --ado-project "<project name>" `
  --process-name "<process name>" `
  --excel-file "<path to ADO template guideline workbook>" `
  --catalog-source-dir "<folder containing the four catalog source files>" `
  --catalog-output ".\out" `
  --catalog-parallel-workers 4
```

The wizard prompts for the PAT if `BPC_ADO_PAT` is not already set. The PAT is kept in memory for the run and is not written to script files.

For large imports, start with 2-8 parallel workers. Higher worker counts may trigger Azure DevOps ATCPU throttling. The importer retries transient HTTP 408, 429, and 5xx responses.

## Run selected phases

Rerun only phases 1 and 2:

```powershell
python setup_wizard.py --start-at 1 --stop-after 2
```

Run only phase 5 import:

```powershell
python setup_wizard.py --start-at 5 --stop-after 5
```

Regenerate only the HTML summary report:

```powershell
python setup_wizard.py --start-at 6 --stop-after 6
```

## Phase 5 import behavior

Phase 5 uses the same Azure DevOps organization, project, PAT, and template workbook from the wizard. It calls the June Preview importer with:

- parent-aware parallel creation,
- project-scoped output folders,
- retry handling for transient connection failures,
- idempotent resume through `ado-id-map.csv`,
- dynamic work item type reference resolution,
- Test Case create fallback when Azure DevOps rejects custom state values at create time,
- deprecated/deleted source rows skipped by default.

If the template workbook is in a folder named `Python Scripts`, the catalog source folder defaults to that folder's parent. Otherwise pass `--catalog-source-dir`.

### Output files

Phase 5 writes project-scoped output under:

```text
out\<organization>_<project>\
```

Key output files:

- `ado-id-map.csv` - successful imported or recovered work item IDs. Reruns skip these keys.
- `import-plan.json` - deterministic import plan and field payloads.
- `import-preview.csv` - human-readable preview of planned work items.
- `import-failures.json` - unresolved failure details from the latest failed run. The Phase 6 report reconciles this with `ado-id-map.csv` so resolved prior failures do not keep the report in a failed state.
- `skipped-deprecated-deleted.csv` - source rows skipped by create/import mode.
- `bpc-ado-setup-summary.html` - Phase 6 HTML summary report.

## Test Case New state

Phase 1 ensures Test Case work item type references have a `New` state in the `Proposed` state category. This supports source files that use `State = New` for standard Test Case work items.

Phase 5 also resolves work item type display names to the current project's Azure DevOps work item type reference names. This avoids hard-coded process/project prefixes and supports projects where the process-specific Test Case reference differs.

## DevLabs multivalue control extension

Phase 2 attempts to install or confirm the DevLabs multivalue control extension for the Azure DevOps organization. If the extension is already installed, the script continues. If the PAT or organization policy doesn't allow extension installation, Phase 2 logs a warning and skips multivalue controls until the extension is installed manually or the script is rerun with an account/PAT that can manage extensions.

## Phase 6 HTML summary report

Phase 6 creates a self-contained HTML report in the project output folder. The report includes:

- planned, imported, skipped, unresolved failure, and resolved prior failure counts,
- worker/thread count, retry settings, and tracked elapsed time when available,
- quick links to the Azure DevOps project, Boards, Work Items, process settings, output folder, import files, and latest phase logs,
- latest phase log API status counts and expandable historical log findings,
- failure reconciliation against `ado-id-map.csv` so stale failure files do not incorrectly show the import as failed after a successful rerun.

## More guidance

- [Set up Azure DevOps with the Business Process Catalog June Preview](https://learn.microsoft.com/dynamics365/guidance/business-processes/about-configure-azure-devops-june-preview)
- [What's new in the Business Process Catalog Azure DevOps setup June Preview](https://learn.microsoft.com/dynamics365/guidance/business-processes/about-configure-azure-devops-june-preview-whats-new)
- [Business Process Catalog Azure DevOps setup FAQ - June Preview](https://learn.microsoft.com/dynamics365/guidance/business-processes/about-configure-azure-devops-june-preview-faq)
- [What's new in June Preview](docs/whats-new-june-preview.md)
- [June Preview user guide](docs/user-guide-june-preview.md)
- [June Preview FAQ](docs/faq-june-preview.md)
