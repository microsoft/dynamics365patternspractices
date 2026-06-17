# Publish instructions for Business Process Catalog ADO setup - June Preview

Use this article as the preview publishing runbook.

## Package label

Use the suffix:

```text
June Preview
```

Recommended package folder/file label:

```text
Business Process Catalog ADO setup package - June Preview
```

## Publishable files

Include:

- `1_ADO_Creation_Script (Preview).py`
- `2_ADO_Page_Layout_Script_Threaded (Preview).py`
- `3_ADO_Teams_Areas_Script (Preview).py`
- `4_ADO_Backlog_Config_Script (Preview).py`
- `5_BPC_Catalog_Import.py`
- `6_Generate_HTML_Report.py`
- `ado_setup_config.py`
- `ado_setup_validation.py`
- `setup_wizard.py`
- `requirements.txt`
- `README.md`
- `bpc_ado_import\*.py`
- `docs\*.md`
- the June Preview ADO template workbook, if the publishing location is intended to include the template.

Exclude:

- `.venv`
- `__pycache__`
- `*.pyc`
- run logs such as `*_Log_*.txt`
- local output folders such as `out`
- PATs, credentials, or environment-specific files.

## Suggested branch

```text
preview/june-bpc-ado-setup
```

## Suggested commit title

```text
Add Business Process Catalog ADO setup June Preview
```

## Pull request summary

Use this draft:

```markdown
## Summary

Adds the June Preview package for Business Process Catalog Azure DevOps setup and import.

## Changes

- Adds guided six-phase setup wizard.
- Adds resumable Business Process Catalog importer.
- Adds deterministic HTML setup/import summary report.
- Adds project-scoped import output and idempotent rerun behavior through `ado-id-map.csv`.
- Adds retry and recovery behavior for transient ADO failures and throttling.
- Adds Test Case state handling and dynamic work item type reference resolution.
- Updates README, user guide, and What's New documentation for preview.

## Validation

- Ran setup/import against preview ADO projects.
- Verified rerun behavior skips existing imported keys.
- Verified HTML report reconciles stale failure records with `ado-id-map.csv`.
```

## Validation checklist

- [ ] Package contains no `.venv`, `__pycache__`, logs, or output files.
- [ ] README title includes `June Preview`.
- [ ] What's New article compares current published preview and June Preview.
- [ ] User guide includes setup, run, rerun, and troubleshooting guidance.
- [ ] HTML report can be generated with Phase 6.
- [ ] Import output is project-scoped.
- [ ] PAT values are not committed.

## After publishing

1. Share the README and user guide with preview participants.
2. Ask participants to start with 2-4 workers.
3. Ask participants to send `bpc-ado-setup-summary.html` and `import-failures.json` when reporting issues.
4. Capture source/template corrections for the next catalog release.



