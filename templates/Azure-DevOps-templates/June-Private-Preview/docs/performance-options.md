# Performance options for Business Process Catalog imports

This v2 folder is an experimental copy. The original `bpc-ado-importer` folder should remain the stable importer while this version is tested.

## Current bottlenecks

1. **Work item creation is one REST call per item.** Azure DevOps Work Item Tracking create API creates a single work item per request.
2. **Hierarchy requires parent IDs.** A child cannot be linked to its parent until the parent has been created and its ADO ID is known.
3. **Classification path checks are chatty.** The current importer checks and creates Area Path / Iteration Path nodes before import.
4. **Console output can slow long runs.** Printing every created item adds overhead and makes it hard to see real progress.

## Safe v2 improvement already implemented

v2 no longer prints every created work item by default. It prints timed progress summaries controlled by:

```powershell
--progress-interval-seconds 60
```

Use this for quieter long-running imports:

```powershell
python -m bpc_ado_import.cli import `
  --source "<source folder>" `
  --template "<template workbook>" `
  --project-url "<ADO project URL>" `
  --output .\out-v2 `
  --progress-interval-seconds 60
```

If detailed per-item output is needed:

```powershell
--print-created-items
```

v2 also retries transient API/network failures. The defaults are:

```powershell
--max-retries 3
--retry-delay-seconds 5
--recovery-field MSBPC.microsoftid
```

The recovery field lookup is important for idempotency: if ADO creates the work item but the response is lost due to a connection reset, v2 tries to find the existing work item by Microsoft ID before retrying the create call.

## Multithreading option

v2 now includes parent-aware multithreading:

```powershell
--parallel-workers 4
```

The importer:

1. Import all rows whose parents are already created.
2. Process that ready set with a bounded worker pool.
3. Write each successful ADO ID to a shared ID map using a lock.
4. Repeat until no pending rows remain.
5. Stop on the first failure by default so validation errors are not hidden.

Recommended first worker counts:

| Workers | Risk | Notes |
| --- | --- | --- |
| 2 | Low | Good first test; should reduce API wait time without aggressive throttling |
| 4 | Medium | Likely useful once ADO process validation is stable |
| 8+ | Higher | More likely to hit throttling, transient failures, or noisy logs |

This should be implemented as a single process with internal workers, not as multiple independent `/fleet` workers writing to the same output folder. Multiple processes would race on `ado-id-map.csv` and could duplicate work items unless a shared lock/database is introduced.

## /fleet or agent option

`/fleet` could be useful after the hierarchy is partitioned into independent import ranges. A safe split would be:

1. Create all shared root and L1/L2 parent nodes first.
2. Generate separate partition files by top-level process or deliverable tree.
3. Give each worker a different output folder and a read-only parent ID map.
4. Merge ID maps after all partitions complete.

This is more complex than internal threading and should be treated as a later optimization.

## Skill option

Converting this into a custom skill is useful for repeatability and partner distribution, but it will not make the API calls faster by itself. A skill would package:

- The importer scripts.
- The required folder layout.
- The ADO template validation steps.
- The standard runbook and troubleshooting guidance.

Recommendation: stabilize v2 first, then package it as a skill once the import behavior and ADO process requirements are final.

