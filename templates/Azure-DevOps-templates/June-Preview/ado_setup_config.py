import argparse
import getpass
import os
import sys
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class AdoSetupConfig:
    ado_org_url: str
    ado_project: str
    process_name: str
    pat: str
    excel_file: str
    log_file: str


def _first_value(*values: Optional[str]) -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""


def _prompt(label: str, current_value: str, *, secret: bool = False, required: bool = True) -> str:
    if current_value:
        return current_value

    if secret:
        prompt = f"{label} (hidden; paste or type the value, then press Enter): "
        value = getpass.getpass(prompt)
    else:
        prompt = f"{label}: "
        value = input(prompt)
    value = value.strip()
    if required and not value:
        raise ValueError(f"{label} is required.")
    return value


def _normalize_org_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return value
    if value.startswith("https://dev.azure.com/"):
        return value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"https://dev.azure.com/{value}"


def _resolve_path(value: str, script_dir: str) -> str:
    value = value.strip().strip('"').strip("'")
    if not value:
        return value
    return value if os.path.isabs(value) else os.path.join(script_dir, value)


def _build_parser(default_log_file: str, require_process: bool) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a Microsoft Business Process Catalog Azure DevOps setup script."
    )
    parser.add_argument("--ado-org-url", help="Azure DevOps organization URL, such as https://dev.azure.com/contoso.")
    parser.add_argument("--ado-project", help="Azure DevOps project name.")
    parser.add_argument(
        "--process-name",
        help="Azure DevOps process/template name. You can usually use the same value as the project name.",
    )
    parser.add_argument("--excel-file", help="Path to the Azure DevOps template Excel file.")
    parser.add_argument("--log-file", default=None, help=f"Path to the log file. Default: {default_log_file}")
    parser.add_argument(
        "--pat",
        help=(
            "Azure DevOps personal access token. For safety, prefer the BPC_ADO_PAT "
            "environment variable or the secure prompt instead of this argument."
        ),
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail instead of prompting when required values are missing.",
    )
    if not require_process:
        parser.set_defaults(process_name="")
    return parser


def load_config(
    default_log_file: str,
    *,
    require_process: bool = True,
    argv: Optional[List[str]] = None,
    ignore_unknown_args: bool = False,
) -> AdoSetupConfig:
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    parser = _build_parser(default_log_file, require_process)
    if ignore_unknown_args:
        args, _ = parser.parse_known_args(argv)
    else:
        args = parser.parse_args(argv)

    ado_org_url = _first_value(
        args.ado_org_url,
        os.getenv("BPC_ADO_ORG_URL"),
        os.getenv("ADO_ORG_URL"),
        os.getenv("AZURE_DEVOPS_ORG_URL"),
    )
    ado_project = _first_value(args.ado_project, os.getenv("BPC_ADO_PROJECT"), os.getenv("ADO_PROJECT"))
    process_name = _first_value(
        args.process_name,
        os.getenv("BPC_ADO_PROCESS_NAME"),
        os.getenv("ADO_PROCESS_NAME"),
        os.getenv("PROCESS_NAME"),
    )
    pat = _first_value(args.pat, os.getenv("BPC_ADO_PAT"), os.getenv("AZURE_DEVOPS_EXT_PAT"), os.getenv("ADO_PAT"))
    excel_file = _first_value(args.excel_file, os.getenv("BPC_ADO_EXCEL_FILE"), os.getenv("ADO_EXCEL_FILE"))
    log_file = _first_value(args.log_file, os.getenv("BPC_ADO_LOG_FILE"), os.getenv("ADO_LOG_FILE"), default_log_file)

    if args.non_interactive:
        missing = []
        if not ado_org_url:
            missing.append("--ado-org-url or BPC_ADO_ORG_URL")
        if not ado_project:
            missing.append("--ado-project or BPC_ADO_PROJECT")
        if require_process and not process_name:
            missing.append("--process-name or BPC_ADO_PROCESS_NAME")
        if not pat:
            missing.append("BPC_ADO_PAT or --pat")
        if not excel_file:
            missing.append("--excel-file or BPC_ADO_EXCEL_FILE")
        if missing:
            raise ValueError("Missing required configuration: " + ", ".join(missing))
    else:
        print("Enter Azure DevOps setup values.")
        print("PAT input is hidden and is not saved. When entering the PAT, no characters will appear.")
        ado_org_url = _prompt("Azure DevOps organization URL or organization name", ado_org_url)
        ado_project = _prompt("Azure DevOps project name", ado_project)
        if require_process:
            process_name = _prompt("Azure DevOps process/template name", process_name)
        pat = _prompt("Azure DevOps PAT", pat, secret=True)
        excel_file = _prompt("Path to Azure DevOps template Excel file", excel_file)

    if not require_process and not process_name:
        process_name = ado_project

    return AdoSetupConfig(
        ado_org_url=_normalize_org_url(ado_org_url),
        ado_project=ado_project,
        process_name=process_name,
        pat=pat,
        excel_file=_resolve_path(excel_file, script_dir),
        log_file=_resolve_path(log_file, script_dir),
    )



