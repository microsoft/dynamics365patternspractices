# Business Process Catalog Azure DevOps setup user guide - June Private Preview

This guide explains how to run the June Private Preview setup package.

## Prerequisites

- Windows dev box or local Windows machine with access to Azure DevOps.
- Python 3.12 or later.
- Azure DevOps personal access token with Work Items read/write permissions and enough permissions to create/update processes, projects, teams, areas, iterations, and backlog settings.
- The ADO template guideline workbook.
- The Business Process Catalog source folder.

For long imports, run from a dev-box-local folder such as `C:\BPCADO`. Avoid running scripts directly from redirected paths such as `\\tsclient\...`.

## Prepare the package

```powershell
Set-Location "C:\BPCADO\bpc-ado-publish-package"

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run the full setup

```powershell
.\.venv\Scripts\python.exe setup_wizard.py `
  --ado-org-url "https://dev.azure.com/<organization>" `
  --ado-project "<project name>" `
  --process-name "<process name>" `
  --excel-file "<path to ADO template guideline workbook>" `
  --catalog-source-dir "<path to Business Process Catalog source folder>" `
  --catalog-output "C:\BPCADO\out" `
  --catalog-parallel-workers 4
```

The wizard prompts for the Azure DevOps PAT if `BPC_ADO_PAT` is not already set.

## Run selected phases

Run only process/project setup:

```powershell
.\.venv\Scripts\python.exe setup_wizard.py --start-at 1 --stop-after 4
```

Run only catalog import:

```powershell
.\.venv\Scripts\python.exe setup_wizard.py --start-at 5 --stop-after 5
```

Generate only the HTML report:

```powershell
.\.venv\Scripts\python.exe setup_wizard.py --start-at 6 --stop-after 6
```

## Choose a worker count

| Worker count | Recommended use |
| ---: | --- |
| 1 | Safest option after throttling or when diagnosing failures. |
| 2-4 | Good first private preview validation. |
| 8 | Reasonable after the target process is stable. |
| 16+ | Use only when you accept higher ADO throttling risk. |

If Azure DevOps returns ATCPU or HTTP 429 throttling, rerun Phase 5 with fewer workers. The importer skips keys already recorded in `ado-id-map.csv`.

## Review output

Open:

```text
<catalog-output>\<organization>_<project>\bpc-ado-setup-summary.html
```

Use the report to review:

- setup/import status,
- planned, imported, skipped, and failure counts,
- resolved prior failures,
- elapsed time and worker count,
- quick links to ADO and output files,
- phase log details.

## Rerun behavior

Phase 5 is resumable. Successful imports are recorded in:

```text
ado-id-map.csv
```

When rerun, the importer skips keys already in that file and continues from remaining work items.

## Common troubleshooting

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Excel template not found | File path is not local to the dev box. | Copy the source folder locally and update paths. |
| Log write warnings | Running from a redirected path such as `\\tsclient`. | Copy package/source to dev-box-local disk. |
| HTTP 429 or ATCPU failure | Too many parallel ADO requests. | Rerun Phase 5 with fewer workers. |
| Required field failure | Source data or template applicability mismatch. | Fix source/template or adjust the ADO process requirement, then rerun Phase 5. |
| Stale failure still appears | Earlier `import-failures.json` entry was later imported. | Regenerate Phase 6 report; it reconciles failures against `ado-id-map.csv`. |

## Security notes

- Do not place PAT values in scripts or source control.
- Prefer the secure prompt or `BPC_ADO_PAT` environment variable.
- Review generated output before sharing externally.
