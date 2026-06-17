# Business Process Catalog Azure DevOps setup FAQ - June Preview

## Does Phase 2 install the DevLabs multivalue control extension?

Phase 2 attempts to install or confirm the DevLabs multivalue control extension for the Azure DevOps organization. It calls the Azure DevOps extension management API for:

```text
ms-devlabs.vsts-extensions-multivalue-control
```

If the extension is already installed, Phase 2 continues and adds multivalue controls for fields marked as multiselect in the template workbook.

If the extension is not installed and the PAT/account cannot install extensions, Phase 2 logs a warning and skips multivalue controls. Install the extension manually from Azure DevOps Marketplace or rerun Phase 2 with an account and PAT that can manage extensions.

## What PAT scopes are recommended?

Use an account that is an Azure DevOps organization owner or Project Collection Administrator. Select these PAT scopes:

- **Organization:** Read & manage
- **Project and Team:** Read & manage
- **Work Items:** Read & write
- **Process and Work Item Types:** Read & manage
- **Extensions:** Read
- **Marketplace:** Read

If your organization restricts extension installation, the account may also need organization-owner or administrator rights beyond the PAT scopes.

## Does the June Preview still require manual HTML control setup?

In most cases, no. Phase 2 now adds supported HTML fields to work item layouts by using Azure DevOps `HtmlFieldControl` payloads.

If Azure DevOps rejects a specific control or if an inherited/system work item type layout is locked, the script logs the response. Review the Phase 2 log and rerun after fixing the process or permissions issue.

## Does the June Preview still require manual multivalue control setup?

Usually no. Phase 2 adds multivalue controls when:

1. the template marks the field as multiselect,
2. `BPC_ADO_ADD_MULTIVALUE_CONTROLS` is not disabled,
3. the DevLabs multivalue control extension is installed or can be installed by the script.

If the extension is unavailable, the script skips multivalue controls and logs the reason.

## Should the old Learn articles be retired?

Not immediately. Keep the existing per-script Learn articles while the current published preview remains available. Add a note to those articles that they apply to the current published preview scripts and link to the new June Preview article.

When June Preview becomes the default package, retire or redirect the older per-script articles to the consolidated June Preview article. Keep and update the troubleshooting article so it covers Phase 5 import, Phase 6 reporting, PAT scopes, ADO throttling, HTML control automation, and multivalue control extension behavior.

## What should I do if ADO returns HTTP 429 or ATCPU throttling?

Rerun Phase 5 with fewer workers. The importer records successful imports in `ado-id-map.csv`, so reruns skip work items that were already imported.

Start with 2-8 workers. Use 1 worker when diagnosing repeated throttling or validation errors.

## Why does the HTML report show resolved prior failures?

`import-failures.json` can contain a failure from an earlier run. If a later rerun imports that same key successfully, the key appears in `ado-id-map.csv`.

Phase 6 reconciles failures against `ado-id-map.csv`. If the failed key is now present in the ID map, the report lists it as a resolved prior failure and does not mark the run failed.
