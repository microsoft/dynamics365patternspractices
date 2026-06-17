import os
import sys

from ado_setup_config import load_config
from bpc_ado_import.cli import main as importer_main


def _default_catalog_source(excel_file: str) -> str:
    excel_dir = os.path.dirname(os.path.abspath(excel_file))
    if os.path.basename(excel_dir).lower() == "python scripts":
        return os.path.dirname(excel_dir)
    return excel_dir


def main() -> int:
    config = load_config(
        default_log_file="5_BPC_Catalog_Import_Log.txt",
        require_process=True,
        ignore_unknown_args=True,
    )
    source_dir = (
        os.getenv("BPC_ADO_CATALOG_SOURCE_DIR")
        or os.getenv("BPC_ADO_SOURCE_DIR")
        or _default_catalog_source(config.excel_file)
    )
    output_dir = os.getenv("BPC_ADO_IMPORT_OUTPUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    parallel_workers = os.getenv("BPC_ADO_IMPORT_PARALLEL_WORKERS") or "4"
    progress_seconds = os.getenv("BPC_ADO_IMPORT_PROGRESS_SECONDS") or "60"
    max_retries = os.getenv("BPC_ADO_IMPORT_MAX_RETRIES") or "8"
    retry_delay_seconds = os.getenv("BPC_ADO_IMPORT_RETRY_DELAY_SECONDS") or "30"

    os.environ["BPC_ADO_PAT"] = config.pat
    project_url = f"{config.ado_org_url}/{config.ado_project}/"
    argv = [
        "import",
        "--source", source_dir,
        "--template", config.excel_file,
        "--project-url", project_url,
        "--output", output_dir,
        "--pat-env", "BPC_ADO_PAT",
        "--parallel-workers", parallel_workers,
        "--progress-interval-seconds", progress_seconds,
        "--max-retries", max_retries,
        "--retry-delay-seconds", retry_delay_seconds,
    ]
    if os.getenv("BPC_ADO_INCLUDE_DEPRECATED_DELETED", "").strip().lower() in ("1", "true", "yes"):
        argv.append("--include-deprecated-deleted")
    return importer_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())



