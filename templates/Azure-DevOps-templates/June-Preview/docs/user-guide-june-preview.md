# Business Process Catalog Azure DevOps setup user guide - June Preview

This guide explains how to run the June Preview setup package.

## Prerequisites

- Windows dev box or local Windows machine with access to Azure DevOps.
- Python 3.12 or later.
- Azure DevOps personal access token (PAT) with enough permissions to create/update processes, projects, teams, areas, iterations, backlogs, work items, and work item form layouts.
- The ADO template guideline workbook.
- The Business Process Catalog source folder.

For long imports, run from a dev-box-local folder such as `C:\BPCADO`. Avoid running scripts directly from redirected paths such as `\\tsclient\...`.

## Prepare the package

```powershell
Set-Location "C:\BPCADO\bpc-ado-publish-package"

python -m pip install -r requirements.txt
```

> [!TIP]
> A Python virtual environment is optional. Use one if you want to isolate this package's dependencies from other Python tools on the machine. For Windows guidance, see [Creation of virtual environments](https://docs.python.org/3/library/venv.html#creating-virtual-environments). After creating and activating a virtual environment, use the same commands shown in this guide.

## Create the Azure DevOps PAT

Create a PAT for the account that will run the setup. The account should be an Azure DevOps organization owner or Project Collection Administrator for the target organization.

The June Preview needs broader permissions than the earlier manual-script preview because it creates or updates the project/process, materializes inherited/system work item types, updates layouts, configures teams/areas/backlogs, checks the DevLabs multivalue control extension, and imports work items.

Select these PAT scopes:

- **Organization:** Read & manage
- **Project and Team:** Read & manage
- **Work Items:** Read & write
- **Process and Work Item Types:** Read & manage
- **Extensions:** Read
- **Marketplace:** Read

If your organization limits PAT scopes by policy, work with your Azure DevOps administrator to grant equivalent permissions or run the setup with an account that already has those capabilities.

Phase 2 attempts to install or confirm the DevLabs multivalue control extension by using Azure DevOps extension management APIs. If the extension is already installed, the check succeeds. If the extension isn't installed and the PAT/account can't install extensions, Phase 2 logs a warning and skips multivalue controls. In that case, install the extension manually from Azure DevOps Marketplace or rerun Phase 2 with an account and PAT that can manage extensions.

Do not paste the PAT into the scripts or commit it to source control. Let the wizard prompt for it, or set it only for the current PowerShell session:

```powershell
$env:BPC_ADO_PAT = "<paste PAT here>"
```

## Run the full setup

```powershell
python setup_wizard.py `
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
python setup_wizard.py --start-at 1 --stop-after 4
```

Run only catalog import:

```powershell
python setup_wizard.py --start-at 5 --stop-after 5
```

Generate only the HTML report:

```powershell
python setup_wizard.py --start-at 6 --stop-after 6
```

## Choose a worker count

| Worker count | Recommended use |
| ---: | --- |
| 1 | Safest option after throttling or when diagnosing failures. |
| 2-4 | Good first preview validation. |
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
| Layout or multivalue controls are not added | PAT is missing extension/marketplace access, organization policy blocks extension installation, or the DevLabs multivalue control extension is not installed. | Confirm PAT scopes, install/enable the extension manually if needed, then rerun Phase 2. |

## Security notes

- Do not place PAT values in scripts or source control.
- Prefer the secure prompt or `BPC_ADO_PAT` environment variable.
- Review generated output before sharing externally.



