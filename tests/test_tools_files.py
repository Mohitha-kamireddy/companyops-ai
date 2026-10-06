"""read_file and list_files: behaviour and the data/ sandbox."""
import os

import pytest

from backend.app.tools import ToolDispatcher, ToolError
from backend.app.tools.file_tools import MAX_READ_BYTES, ListFilesTool, ReadFileTool


@pytest.fixture
def data_dir(tmp_path):
    root = tmp_path / "data"
    (root / "sub").mkdir(parents=True)
    (root / "invoice.txt").write_text("Vendor: Acme\nAmount: 10.00\n", encoding="utf-8")
    (root / "notes.md").write_text("# notes\n", encoding="utf-8")
    (root / "sub" / "rates.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (root / "minierp.db").write_bytes(b"SQLite format 3\x00 pretend password hashes live here")
    (root / ".gitkeep").write_text("")
    (root / "binary.txt").write_bytes(b"\xff\xfe\x00bad bytes")
    (root / "big.txt").write_bytes(b"x" * (MAX_READ_BYTES + 1))
    # Things outside the data directory that must stay unreachable:
    (tmp_path / "outside.txt").write_text("TOP SECRET", encoding="utf-8")
    sibling = tmp_path / "data_evil"          # shares the "data" name prefix
    sibling.mkdir()
    (sibling / "x.txt").write_text("TOP SECRET", encoding="utf-8")
    os.symlink(tmp_path / "outside.txt", root / "link.txt")
    return root


@pytest.fixture
def dispatcher(data_dir):
    return ToolDispatcher([ReadFileTool(data_dir), ListFilesTool(data_dir)])


def error_type(result):
    assert result.success is False
    return result.metadata["error_type"]


# --------------------------------------------------------------------------
# read_file
# --------------------------------------------------------------------------

def test_read_file_returns_content(data_dir):
    output = ReadFileTool(data_dir).execute(path="invoice.txt")
    assert output == {"path": "invoice.txt", "content": "Vendor: Acme\nAmount: 10.00\n", "size_bytes": 27}


def test_read_file_in_subdirectory_via_dispatcher(dispatcher):
    result = dispatcher.dispatch("read_file", {"path": "sub/rates.csv"})
    assert result.success is True
    assert result.output["content"] == "a,b\n1,2\n"
    assert result.output["path"] == "sub/rates.csv"


def test_read_file_missing_file(dispatcher):
    result = dispatcher.dispatch("read_file", {"path": "nope.txt"})
    assert error_type(result) == "file_not_found"
    assert "list_files" in result.error  # tells the agent how to recover


def test_read_file_missing_file_unit(data_dir):
    with pytest.raises(ToolError) as caught:
        ReadFileTool(data_dir).execute(path="nope.txt")
    assert caught.value.error_type == "file_not_found"


def test_read_file_blocks_parent_directory_traversal(dispatcher):
    for path in ("../outside.txt", "sub/../../outside.txt", "../data_evil/x.txt"):
        result = dispatcher.dispatch("read_file", {"path": path})
        assert error_type(result) == "access_denied", path
        assert "TOP SECRET" not in str(result.to_dict())


def test_read_file_blocks_absolute_paths_outside(dispatcher, tmp_path):
    for path in (str(tmp_path / "outside.txt"), "/etc/passwd"):
        assert error_type(dispatcher.dispatch("read_file", {"path": path})) == "access_denied"


def test_read_file_blocks_symlink_escaping_the_data_dir(dispatcher):
    result = dispatcher.dispatch("read_file", {"path": "link.txt"})
    assert error_type(result) == "access_denied"
    assert "TOP SECRET" not in str(result.to_dict())


def test_read_file_blocks_database_and_other_file_types(dispatcher):
    # Existing and non-existing alike: the answer must not reveal which files exist.
    for path in ("minierp.db", "nothing.db", ".gitkeep", "sub", "script.py"):
        assert error_type(dispatcher.dispatch("read_file", {"path": path})) == "access_denied", path


def test_read_file_rejects_null_byte_path(dispatcher):
    assert error_type(dispatcher.dispatch("read_file", {"path": "a\x00.txt"})) == "invalid_path"


def test_read_file_refuses_oversized_file(dispatcher):
    assert error_type(dispatcher.dispatch("read_file", {"path": "big.txt"})) == "file_too_large"


def test_read_file_refuses_non_text_content(dispatcher):
    assert error_type(dispatcher.dispatch("read_file", {"path": "binary.txt"})) == "not_text"


def test_read_file_validates_arguments(dispatcher):
    for arguments in ({}, {"path": ""}, {"path": 5}, {"path": "invoice.txt", "mode": "w"}):
        assert error_type(dispatcher.dispatch("read_file", arguments)) == "invalid_arguments"


# --------------------------------------------------------------------------
# list_files
# --------------------------------------------------------------------------

def test_list_files_returns_only_allowed_files(data_dir):
    output = ListFilesTool(data_dir).execute()
    paths = [f["path"] for f in output["files"]]
    assert paths == sorted(paths)  # stable, predictable order
    assert set(paths) == {"invoice.txt", "notes.md", "sub/rates.csv", "binary.txt", "big.txt"}
    assert output["count"] == len(paths)
    assert all(f["size_bytes"] >= 0 for f in output["files"])


def test_list_files_hides_database_gitkeep_and_escaping_symlinks(dispatcher):
    paths = [f["path"] for f in dispatcher.dispatch("list_files").output["files"]]
    assert "minierp.db" not in paths
    assert ".gitkeep" not in paths
    assert "link.txt" not in paths


def test_list_files_paths_can_be_read_back(dispatcher):
    for entry in dispatcher.dispatch("list_files").output["files"]:
        if entry["path"] in ("binary.txt", "big.txt"):
            continue  # listed because the type is allowed; reading them is refused for other reasons
        assert dispatcher.dispatch("read_file", {"path": entry["path"]}).success is True


def test_list_files_empty_directory(tmp_path):
    (tmp_path / "empty").mkdir()
    assert ListFilesTool(tmp_path / "empty").execute() == {"count": 0, "files": []}


def test_list_files_missing_data_directory(tmp_path):
    result = ToolDispatcher([ListFilesTool(tmp_path / "missing")]).dispatch("list_files")
    assert error_type(result) == "data_dir_missing"


def test_list_files_takes_no_arguments(dispatcher):
    assert error_type(dispatcher.dispatch("list_files", {"path": "."})) == "invalid_arguments"
