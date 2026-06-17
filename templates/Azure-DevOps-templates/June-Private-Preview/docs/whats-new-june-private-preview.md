# What's new in Business Process Catalog Azure DevOps setup - June Private Preview

This article summarizes the June Private Preview update for the Business Process Catalog Azure DevOps setup package.

## Summary

The June Private Preview expands the package from a set of discrete Azure DevOps setup scripts into an end-to-end guided setup and import workflow. It adds a resumable catalog importer, stronger validation and retry behavior, project-scoped outputs, and a deterministic HTML summary report.

## Comparison with the currently published GitHub preview

| Area | Currently published preview | June Private Preview |
| --- | --- | --- |
| Execution model | Individual scripts run manually in sequence. | `setup_wizard.py` orchestrates phases 1-6 with `--start-at` and `--stop-after` rerun support. |
| Dependency setup | User installs Python dependencies manually. | Package README recommends a Python virtual environment and retains `requirements.txt`. |
| Azure DevOps configuration | Process, project, work item types, fields, layouts, teams, areas, and backlogs are configured by separate scripts. | Same setup phases are retained and wrapped by the wizard with early Excel and ADO access validation. |
| Catalog import | Not included or handled separately. | Phase 5 imports catalog source files into ADO using a parent-aware, resumable importer. |
| Import resume | Manual reruns can duplicate work unless handled outside the scripts. | `ado-id-map.csv` records successful work item IDs and reruns skip imported keys. |
| Output organization | Logs and outputs are script-local. | Import output is scoped by organization/project under `out\<organization>_<project>\`. |
| Parallelism | Page layout script includes threading; catalog import not part of the package. | Catalog import supports parent-aware parallel workers with retry/backoff controls. |
| Throttling resiliency | Limited transient handling. | Retries HTTP 408, 429, and 5xx responses and supports configurable retry count/delay. |
| Work item type resolution | Scripts rely on source/template work item names. | Importer resolves ADO work item type display names to current project reference names dynamically. |
| Test Case state handling | Test Case `New` state support is not consistently handled. | Phase 1 confirms Test Case `New` state; Phase 5 handles create-time state validation fallback. |
| Multi-select picklists | Source duplicate picklist values can block setup. | Phase 1 de-duplicates picklist values before ADO updates; source template should still be kept clean. |
| Summary reporting | Users review console output/log files manually. | Phase 6 generates a deterministic HTML report with metrics, failure reconciliation, quick links, and latest log details. |

## New setup wizard

The wizard runs the setup in six phases:

1. Create process, project, work item types, fields, picklists, and Test Case state.
2. Configure work item page layouts and controls.
3. Create teams, area paths, and team assignments.
4. Configure backlog levels, iterations, and team settings.
5. Import Business Process Catalog work items.
6. Generate the HTML setup/import summary report.

Use `--start-at` and `--stop-after` to resume or rerun selected phases without repeating the full setup.

## New catalog importer

Phase 5 imports `.xlsx`, `.xlsm`, `.csv`, and `.tsv` source files. The importer:

- builds a deterministic parent-first import plan,
- normalizes placeholder area and iteration paths to the target project name,
- creates parent work items before children,
- writes `import-plan.json` and `import-preview.csv`,
- records successful IDs in `ado-id-map.csv`,
- skips keys already present in `ado-id-map.csv` on rerun,
- skips `Deprecated` and `Deleted` catalog rows by default,
- writes detailed failures to `import-failures.json`.

## Improved resiliency

The June Private Preview includes:

- transient retry handling for connection failures, timeouts, HTTP 408, HTTP 429, and HTTP 5xx,
- recovery lookup by `MSBPC.microsoftid` after ambiguous transient failures,
- configurable parallel workers, retry count, and retry delay,
- safer handling of Test Case state values when ADO rejects a custom state during create,
- dynamic work item type reference resolution instead of hard-coded process/project prefixes.

## HTML summary report

Phase 6 writes `bpc-ado-setup-summary.html` to the project output folder. The report includes:

- run status,
- planned/imported/skipped counts,
- unresolved and resolved prior failures,
- worker/thread count,
- retry settings,
- tracked elapsed time when a tracker file is present,
- quick links to the ADO project, Boards, Work Items, process settings, output files, and latest phase logs,
- historical log findings with expandable details.

The report reconciles `import-failures.json` with `ado-id-map.csv`. If a failure from an earlier run was imported successfully in a later run, the report shows it as a resolved prior failure instead of marking the run failed.

## Template updates

The June Private Preview template cleanup includes:

- duplicate picklist value cleanup in the `Products` picklist,
- `Data type` no longer marked applicable to `Job` work item types in the `Work item types` sheet.

## Known limitations

- Phase 5 create/import mode does not update existing work items other than recovery from ambiguous transient failures.
- `Deprecated` and `Deleted` rows are skipped in create/import mode.
- Very high parallel worker counts can trigger ADO ATCPU throttling. Start with 2-8 workers and increase only after validating process stability.
- The HTML report is deterministic and local; it does not query Azure DevOps to verify every work item after import.

## Recommended private preview validation

Before publishing broadly:

1. Run phases 1-4 against a test project.
2. Run Phase 5 with 2-8 workers first.
3. Review `bpc-ado-setup-summary.html`.
4. Confirm unresolved failures are zero.
5. Spot-check ADO work item hierarchy, area paths, teams, Test Cases, and report links.
