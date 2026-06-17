# Azure DevOps template for the Microsoft business process catalog (Preview)

This folder contains Azure DevOps templates and Python automation for configuring an Azure DevOps project for the Microsoft business process catalog.

## Current published preview

The files in this folder root are the currently published preview:

- `1_ADO_Creation_Script (Preview).py`
- `2_ADO_Page_Layout_Script_Threaded (Preview).py`
- `3_ADO_Teams_Areas_Script (Preview).py`
- `4_ADO_Backlog_Config_Script (Preview).py`
- `ADO template guideline (Preview).xlsx`

Use the existing Dynamics 365 Guidance Hub articles for the current published preview:

1. [Automate Azure DevOps project, process, work item types, fields, and picklists from Excel with Python](https://learn.microsoft.com/en-us/dynamics365/guidance/business-processes/about-configure-azure-devops-project-processes)
1. [Automate Azure DevOps page layout creation with Python](https://learn.microsoft.com/en-us/dynamics365/guidance/business-processes/about-configure-azure-devops-page-layout)
1. [Automate the creation of Azure DevOps teams and area paths with Python scripts](https://learn.microsoft.com/en-us/dynamics365/guidance/business-processes/about-configure-azure-devops-teams-area-paths)
1. [Azure DevOps backlog configuration for the Microsoft Business Process Catalog](https://learn.microsoft.com/en-us/dynamics365/guidance/business-processes/about-configure-azure-devops-backlog)
1. [Troubleshooting the Azure DevOps Python Scripts (Preview)](https://learn.microsoft.com/en-us/dynamics365/guidance/business-processes/about-configure-azure-devops-troubleshooting)
1. [Import the catalog into Azure DevOps](https://learn.microsoft.com/en-us/dynamics365/guidance/business-processes/about-import-catalog-devops)

Download the latest version of the business process catalog from [https://aka.ms/businessprocesscatalog](https://aka.ms/businessprocesscatalog).

## June Preview

The June Preview package is staged in:

```text
June-Preview\
```

This package adds:

- a guided six-phase setup wizard,
- a resumable Business Process Catalog importer,
- project-scoped output folders,
- parent-aware parallel import,
- transient retry and ADO throttling handling,
- dynamic work item type reference resolution,
- Test Case state handling,
- deterministic HTML setup/import summary reporting.

Start with:

- [June Preview README](June-Preview/README.md)
- [What's new in June Preview](June-Preview/docs/whats-new-june-preview.md)
- [June Preview user guide](June-Preview/docs/user-guide-june-preview.md)
- [June Preview FAQ](June-Preview/docs/faq-june-preview.md)

The June Preview template workbook is:

```text
June-Preview\ADO template guideline (June Preview).xlsx
```

For long catalog imports, use a dev box or other stable Windows environment and start with 2-8 parallel workers before increasing the worker count.

