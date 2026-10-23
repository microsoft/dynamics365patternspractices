# Azure DevOps template for the Microsoft business process catalog

This folder contains the current Azure DevOps template and archived templates and Python automation for configuring an Azure DevOps project for the Microsoft business process catalog. Learn about the templates at [Set up Azure DevOps with the Business Process Catalog](https://learn.microsoft.com/en-us/dynamics365/guidance/business-processes/about-configure-azure-devops-july) on the Microsoft Learn website.

Download the latest version of the business process catalog from [https://aka.ms/businessprocesscatalog](https://aka.ms/businessprocesscatalog).

## Current template - October 2026

Download [ADO template guidelines - OCT 2026.xlsx](<ADO template guidelines - OCT 2026.xlsx>), the single final October 2026 template. This is the exact repaired October workbook supplied for this release, without regeneration or changes to its cells, formatting, or package contents.

There is no separate current Preview workbook or unversioned workbook. The original first-release Python scripts are historical and are archived with their original workbooks, not published as current October automation. Existing bookmarks and locally configured workbook paths using either older root filename must be updated to the October filename.

The SHA-256 of the final October workbook is:

```text
f7aaa138df1462f4625a1606c7338bc5f547fbb7fc603500d76688db3ded64c2
```

This release was checked for ZIP integrity, XML and relationship integrity, table column counts, expected worksheets and headers, and formula/error cells using openpyxl. A byte-identical short-path copy also opened read-only in installed Microsoft Excel 16.0 with the normal object-model load, macros and external-link updates disabled, and no recovery or save. Source and test-copy hashes remained unchanged. These are workbook checks, not validation of a live Azure DevOps setup or import; no Azure DevOps deployment was performed.

## Historical versions

The superseded root workbooks are retained unchanged for historical reference only:

| Archived workbook | SHA-256 |
| --- | --- |
| [Pre-October default](<Archive/pre-OCT-2026/ADO template guideline.xlsx>) | `08c25cbf2614c766ebfc27c62d0c2d20fd2b656cc89b274e0d2102532eba9d3d` |
| [Pre-October Preview](<Archive/pre-OCT-2026/ADO template guideline (Preview).xlsx>) | `62b1cd64f97992b73b3ef56088004aab89961974285923fe05cb23a693a31af2` |

The four original first-release scripts are preserved under `Archive/pre-OCT-2026/` alongside those workbooks:

- [1 - Creation](<Archive/pre-OCT-2026/1_ADO_Creation_Script (Preview).py>)
- [2 - Page layout](<Archive/pre-OCT-2026/2_ADO_Page_Layout_Script_Threaded (Preview).py>)
- [3 - Teams and areas](<Archive/pre-OCT-2026/3_ADO_Teams_Areas_Script (Preview).py>)
- [4 - Backlog configuration](<Archive/pre-OCT-2026/4_ADO_Backlog_Config_Script (Preview).py>)

Their original relative workbook setting, `ADO template guideline (Preview).xlsx`, resolves to the archived Preview workbook in the same folder. These scripts and workbooks are historical reference material, not the current October release.

The complete [July package](Archive/July/README.md), including its [July workbook](<Archive/July/ADO template guideline (July).xlsx>), scripts, and supporting files, is archived under `Archive/July/` with file contents unchanged. Use the root October workbook for the current template; do not substitute archived workbooks into a current setup.
