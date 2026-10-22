# Azure DevOps template for the Microsoft business process catalog

This folder contains Azure DevOps templates and Python automation for configuring an Azure DevOps project for the Microsoft business process catalog. Learn about the templates at [Set up Azure DevOps with the Business Process Catalog](https://learn.microsoft.com/en-us/dynamics365/guidance/business-processes/about-configure-azure-devops-july) on the Microsoft Learn website.

Download the latest version of the business process catalog from [https://aka.ms/businessprocesscatalog](https://aka.ms/businessprocesscatalog).

## Current template - October 2026

Download [ADO template guideline.xlsx](<ADO template guideline.xlsx>) for the current October 2026 template. This is the exact repaired October workbook supplied for this release, without regeneration or changes to its cells, formatting, or package contents.

[ADO template guideline (Preview).xlsx](<ADO template guideline (Preview).xlsx>) is a byte-identical compatibility copy of the current October workbook, not a separate or older preview. The existing root Python scripts still reference this filename, so their configured file paths and existing download links remain valid. When updating the template, keep both root workbooks byte-identical.

The SHA-256 of both current root workbooks is:

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

The [July package](July/README.md), including its [July workbook](<July/ADO template guideline (July).xlsx>), is preserved as an independent historical bundle. Use the root October workbook for the current template; do not substitute archived workbooks into a current setup.
