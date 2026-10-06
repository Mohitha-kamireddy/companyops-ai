"""read_file and list_files: sandboxed access to the data/ directory.

Safety rules, all enforced in DataDirectory:
  * Paths are relative to the data directory.
  * The fully resolved path (symlinks followed, ".." collapsed) must stay inside it.
  * Only plain-text document types are allowed. data/ also holds the SQLite database
    (which contains a password hash), so .db and every other extension is off limits.
  * Files over MAX_READ_BYTES are refused rather than silently truncated.
"""
from pathlib import Path
from typing import Any

from backend.app.tools.base import Tool, ToolError

ALLOWED_EXTENSIONS = frozenset({".txt", ".md", ".csv", ".json"})
MAX_READ_BYTES = 200_000


class DataDirectory:
    """Resolves and checks paths against one root directory."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()

    def is_allowed_type(self, path: Path) -> bool:
        return path.suffix.lower() in ALLOWED_EXTENSIONS

    def resolve_file(self, relative_path: str) -> Path:
        """Return the real path of an allowed, existing file or raise ToolError."""
        try:
            resolved = (self.root / relative_path).resolve()
        except (ValueError, OSError) as exc:
            raise ToolError(f"invalid path: {exc}", error_type="invalid_path") from None

        # Checked first, so we never reveal whether files outside data/ exist.
        if not resolved.is_relative_to(self.root):
            raise ToolError("access denied: path is outside the data directory", error_type="access_denied")
        if not self.is_allowed_type(resolved):
            raise ToolError(
                f"access denied: only {sorted(ALLOWED_EXTENSIONS)} files can be read",
                error_type="access_denied",
            )
        if not resolved.is_file():
            raise ToolError(
                f"file not found: '{relative_path}'. Paths are relative to the data directory; "
                "use list_files to see what exists.",
                error_type="file_not_found",
            )
        return resolved


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read a local text file from the data directory and return its content. "
        "The path is relative to the data directory (use list_files to see what exists). "
        "Only .txt, .md, .csv and .json files can be read."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "minLength": 1,
                "description": "File path relative to the data directory, e.g. 'invoice_acme.txt'.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, data_dir: Path | str):
        self._data = DataDirectory(data_dir)

    def execute(self, path: str) -> dict[str, Any]:
        resolved = self._data.resolve_file(path)
        size = resolved.stat().st_size
        if size > MAX_READ_BYTES:
            raise ToolError(
                f"file is too large to read ({size} bytes; limit is {MAX_READ_BYTES})",
                error_type="file_too_large",
            )
        try:
            content = resolved.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise ToolError("file is not valid UTF-8 text", error_type="not_text") from None
        except OSError as exc:
            raise ToolError(f"could not read file: {exc}", error_type="read_error") from None
        return {
            "path": resolved.relative_to(self._data.root).as_posix(),
            "content": content,
            "size_bytes": size,
        }


class ListFilesTool(Tool):
    name = "list_files"
    description = (
        "List the files in the data directory that read_file is allowed to open "
        "(.txt, .md, .csv, .json), including subdirectories. Paths are relative to the data directory."
    )
    input_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    def __init__(self, data_dir: Path | str):
        self._data = DataDirectory(data_dir)

    def execute(self) -> dict[str, Any]:
        root = self._data.root
        if not root.is_dir():
            raise ToolError("data directory does not exist", error_type="data_dir_missing")
        files = []
        for path in sorted(root.rglob("*")):
            if not self._data.is_allowed_type(path):
                continue
            real = path.resolve()
            # Skip anything that is not a regular file, or is a symlink pointing outside data/.
            if real.is_file() and real.is_relative_to(root):
                files.append({"path": path.relative_to(root).as_posix(), "size_bytes": real.stat().st_size})
        return {"count": len(files), "files": files}
