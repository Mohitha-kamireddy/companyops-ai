"""Builds the default ToolDispatcher with every tool wired to its dependencies."""
import os
from collections.abc import Callable
from pathlib import Path

from backend.app.tools.control_tools import AskHumanTool, FinishTool
from backend.app.tools.dispatcher import ToolDispatcher
from backend.app.tools.erp_client import ERPClient
from backend.app.tools.erp_tools import GetBillsTool, VerifyBillTool
from backend.app.tools.file_tools import ListFilesTool, ReadFileTool

# backend/app/tools/registry.py -> repository root is three levels up from this folder
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def build_default_dispatcher(
    *,
    data_dir: Path | str | None = None,
    erp_base_url: str | None = None,
    erp_username: str | None = None,
    erp_password: str | None = None,
    prompt_fn: Callable[[str], str] | None = None,
) -> ToolDispatcher:
    """Create a dispatcher with all six tools.

    Anything not passed falls back to the environment (ERP_BASE_URL, ERP_USERNAME,
    ERP_PASSWORD) and then to MiniERP's local defaults.
    """
    client = ERPClient(
        base_url=erp_base_url or os.environ.get("ERP_BASE_URL", "http://127.0.0.1:8001"),
        username=erp_username or os.environ.get("ERP_USERNAME", "admin"),
        password=erp_password or os.environ.get("ERP_PASSWORD", "admin123"),
    )
    data_path = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    return ToolDispatcher(
        [
            ReadFileTool(data_path),
            ListFilesTool(data_path),
            GetBillsTool(client),
            VerifyBillTool(client),
            AskHumanTool(prompt_fn),
            FinishTool(),
        ]
    )
