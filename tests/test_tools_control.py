"""ask_human and finish, plus the default dispatcher wiring."""
from backend.app.tools import ToolDispatcher, build_default_dispatcher
from backend.app.tools.control_tools import AskHumanTool, FinishTool
from backend.app.tools.registry import DEFAULT_DATA_DIR


def ask(answer, question="Delete everything?"):
    asked = []

    def fake_prompt(text):
        asked.append(text)
        return answer

    result = ToolDispatcher([AskHumanTool(fake_prompt)]).dispatch("ask_human", {"question": question})
    return result, asked


# --------------------------------------------------------------------------
# ask_human
# --------------------------------------------------------------------------

def test_ask_human_approved():
    for answer in ("y", "Y", "yes", "YES", "  yes  ", "approve"):
        result, _ = ask(answer)
        assert result.success is True
        assert result.output["decision"] == "approved", answer


def test_ask_human_rejected():
    for answer in ("n", "no", "", "maybe", "yes please do it", "ok", "   "):
        result, _ = ask(answer)
        assert result.success is True
        assert result.output["decision"] == "rejected", answer  # only an explicit yes approves


def test_ask_human_shows_the_question_to_the_human():
    _, asked = ask("y", question="Create bill INV-2026-0417 for $4,825.50?")
    assert len(asked) == 1
    assert "Create bill INV-2026-0417 for $4,825.50?" in asked[0]
    assert "HUMAN APPROVAL REQUIRED" in asked[0]


def test_ask_human_fails_closed_without_a_terminal():
    def no_terminal(_prompt):
        raise EOFError

    result = ToolDispatcher([AskHumanTool(no_terminal)]).dispatch("ask_human", {"question": "ok?"})
    assert result.success is False
    assert result.metadata["error_type"] == "human_unavailable"
    assert result.output is None  # no approval can be inferred from a failure


def test_ask_human_uses_terminal_input_by_default(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    result = ToolDispatcher([AskHumanTool()]).dispatch("ask_human", {"question": "ok?"})
    assert result.output["decision"] == "approved"


def test_ask_human_validates_arguments():
    dispatcher = ToolDispatcher([AskHumanTool(lambda _p: "y")])
    for arguments in ({}, {"question": ""}, {"question": 5}, {"question": "ok?", "default": "yes"}):
        result = dispatcher.dispatch("ask_human", arguments)
        assert result.success is False
        assert result.metadata["error_type"] == "invalid_arguments"


# --------------------------------------------------------------------------
# finish
# --------------------------------------------------------------------------

def test_finish_records_a_request_not_a_completion():
    result = ToolDispatcher([FinishTool()]).dispatch("finish", {"summary": "Entered the Acme bill."})
    assert result.success is True
    assert result.output == {
        "finish_requested": True,
        "claimed_outcome": "success",
        "summary": "Entered the Acme bill.",
        "completion_verified": False,
    }


def test_finish_claim_is_never_marked_verified():
    dispatcher = ToolDispatcher([FinishTool()])
    for outcome in ("success", "failure"):
        output = dispatcher.dispatch("finish", {"summary": "done", "outcome": outcome}).output
        assert output["claimed_outcome"] == outcome
        assert output["completion_verified"] is False


def test_finish_validates_arguments():
    dispatcher = ToolDispatcher([FinishTool()])
    for arguments in ({}, {"summary": ""}, {"summary": "x", "outcome": "great"}, {"summary": "x", "verified": True}):
        result = dispatcher.dispatch("finish", arguments)
        assert result.success is False
        assert result.metadata["error_type"] == "invalid_arguments"


def test_finish_does_not_depend_on_the_erp(dead_erp_url):
    dispatcher = build_default_dispatcher(erp_base_url=dead_erp_url)
    result = dispatcher.dispatch("finish", {"summary": "all done"})
    assert result.success is True
    assert result.output["completion_verified"] is False


# --------------------------------------------------------------------------
# Default wiring
# --------------------------------------------------------------------------

def test_default_dispatcher_reads_the_real_invoice_file():
    dispatcher = build_default_dispatcher()
    listed = [f["path"] for f in dispatcher.dispatch("list_files").output["files"]]
    assert "invoice_acme.txt" in listed
    assert not any(path.endswith(".db") for path in listed)
    content = dispatcher.dispatch("read_file", {"path": "invoice_acme.txt"}).output["content"]
    assert "INV-2026-0417" in content and "4825.50" in content
    assert DEFAULT_DATA_DIR.name == "data"


def test_default_dispatcher_takes_erp_settings_from_the_environment(erp_url, monkeypatch):
    monkeypatch.setenv("ERP_BASE_URL", erp_url)
    result = build_default_dispatcher().dispatch("get_bills")
    assert result.success is True
    assert result.output["count"] == 10
