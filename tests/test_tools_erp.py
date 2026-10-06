"""get_bills and verify_bill against a real MiniERP server (see erp_url in conftest.py)."""
import urllib.request

import pytest

from backend.app.tools import ToolDispatcher
from backend.app.tools.erp_client import ERPClient
from backend.app.tools.erp_tools import GetBillsTool, VerifyBillTool

# Seeded bill #1 in MiniERP, exactly as stored.
SEEDED = {
    "vendor": "Acme Industrial Supplies",
    "invoice_number": "INV-2026-0388",
    "amount": 3120.75,
    "invoice_date": "2026-08-14",
    "description": "Q2 replenishment: steel brackets and fasteners",
}

# The invoice in data/invoice_acme.txt (not in the seed data).
ACME_INVOICE = {
    "vendor": "Acme Industrial Supplies",
    "invoice_number": "INV-2026-0417",
    "amount": 4825.50,
    "invoice_date": "2026-09-18",
    "description": "Q3 bulk order - hydraulic fittings and safety equipment",
}


def make_dispatcher(url, password="admin123"):
    client = ERPClient(url, "admin", password)
    return ToolDispatcher([GetBillsTool(client), VerifyBillTool(client)])


def create_in_erp(erp_app, bill):
    """Enter a bill into MiniERP the way an agent eventually would (through its API)."""
    http = erp_app.test_client()
    http.post("/login", data={"username": "admin", "password": "admin123"})
    response = http.post("/api/bills", json=bill)
    assert response.status_code == 201
    return response.get_json()


# --------------------------------------------------------------------------
# get_bills
# --------------------------------------------------------------------------

def test_get_bills_returns_structured_json(erp_url):
    result = make_dispatcher(erp_url).dispatch("get_bills")
    assert result.success is True
    assert result.output["count"] == 10
    assert len(result.output["bills"]) == 10
    assert set(result.output["bills"][0]) == {
        "id", "vendor", "invoice_number", "amount", "invoice_date", "description", "status", "created_at",
    }


def test_get_bills_sees_new_bills(erp_url, erp_app):
    dispatcher = make_dispatcher(erp_url)
    create_in_erp(erp_app, ACME_INVOICE)
    result = dispatcher.dispatch("get_bills")
    assert result.output["count"] == 11
    assert result.output["bills"][0]["invoice_number"] == "INV-2026-0417"


def test_get_bills_when_erp_is_unavailable(dead_erp_url):
    result = make_dispatcher(dead_erp_url).dispatch("get_bills")
    assert result.success is False
    assert result.metadata["error_type"] == "erp_unavailable"
    assert result.metadata["retryable"] is True
    assert "could not reach the ERP" in result.error


def test_get_bills_with_wrong_credentials(erp_url):
    result = make_dispatcher(erp_url, password="wrong").dispatch("get_bills")
    assert result.success is False
    assert result.metadata["error_type"] == "erp_auth_failed"


def test_get_bills_takes_no_arguments(erp_url):
    result = make_dispatcher(erp_url).dispatch("get_bills", {"vendor": "Acme"})
    assert result.metadata["error_type"] == "invalid_arguments"


# --------------------------------------------------------------------------
# ERPClient
# --------------------------------------------------------------------------

def test_client_logs_in_again_if_the_session_disappears(erp_url):
    client = ERPClient(erp_url, "admin", "admin123")
    assert "bills" in client.get_json("/api/bills")
    for handler in client._opener.handlers:  # simulate the ERP forgetting our session
        if isinstance(handler, urllib.request.HTTPCookieProcessor):
            handler.cookiejar.clear()
    assert "bills" in client.get_json("/api/bills")


def test_client_only_accepts_http_urls():
    for url in ("file:///etc/passwd", "ftp://example.com", "127.0.0.1:8001"):
        with pytest.raises(ValueError):
            ERPClient(url, "admin", "admin123")


def test_client_login_does_not_use_up_browser_actions(make_app):
    """Logging in must not follow the redirect to /dashboard: MiniERP counts that as a browser action."""
    from werkzeug.serving import make_server
    import threading

    server = make_server("127.0.0.1", 0, make_app(SESSION_EXPIRY_ACTIONS=1), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = ERPClient(f"http://127.0.0.1:{server.server_port}", "admin", "admin123")
        client.get_json("/api/bills")  # logs in
        # With a limit of 1, the first page view on this session must still be allowed.
        # (Had login followed the redirect, that page view would already have been spent.)
        status, _ = client._send("GET", "/dashboard")
        assert status == 200
    finally:
        server.shutdown()


# --------------------------------------------------------------------------
# verify_bill: successful verification
# --------------------------------------------------------------------------

def test_verify_bill_succeeds_for_matching_record(erp_url):
    result = make_dispatcher(erp_url).dispatch("verify_bill", SEEDED)
    assert result.success is True
    assert result.output["verified"] is True
    assert result.output["bill_found"] is True
    assert result.output["bill_id"] == 1
    assert result.output["mismatches"] == []
    assert all(check["match"] for check in result.output["checks"].values())
    assert set(result.output["checks"]) == {"vendor", "invoice_number", "amount", "invoice_date", "description"}


def test_verify_bill_ignores_case_and_whitespace_layout(erp_url):
    expected = {**SEEDED, "vendor": "  ACME industrial   supplies ", "description": "Q2 replenishment:  steel brackets and fasteners "}
    assert make_dispatcher(erp_url).dispatch("verify_bill", expected).output["verified"] is True


def test_verify_bill_confirms_a_bill_entered_after_the_fact(erp_url, erp_app):
    dispatcher = make_dispatcher(erp_url)
    assert dispatcher.dispatch("verify_bill", ACME_INVOICE).output["verified"] is False  # not entered yet
    create_in_erp(erp_app, ACME_INVOICE)
    result = dispatcher.dispatch("verify_bill", ACME_INVOICE)
    assert result.output["verified"] is True
    assert result.output["bill_id"] == 11


# --------------------------------------------------------------------------
# verify_bill: failed verification
# --------------------------------------------------------------------------

def test_verify_bill_reports_every_mismatching_field(erp_url):
    expected = {**SEEDED, "amount": 3120.76, "description": "Something else", "invoice_date": "2026-08-15"}
    result = make_dispatcher(erp_url).dispatch("verify_bill", expected)
    assert result.success is True            # the tool worked...
    assert result.output["verified"] is False  # ...and the verification failed
    assert result.output["bill_found"] is True
    assert result.output["mismatches"] == ["amount", "invoice_date", "description"]
    assert result.output["checks"]["amount"] == {"expected": 3120.76, "actual": 3120.75, "match": False}
    assert result.output["checks"]["vendor"]["match"] is True
    assert "amount, invoice_date, description" in result.output["message"]


def test_verify_bill_fails_when_bill_does_not_exist(erp_url):
    result = make_dispatcher(erp_url).dispatch("verify_bill", ACME_INVOICE)
    assert result.success is True
    assert result.output["verified"] is False
    assert result.output["bill_found"] is False
    assert result.output["bill_id"] is None
    assert "INV-2026-0417" in result.output["message"]


def test_verify_bill_fails_when_entered_under_the_wrong_vendor(erp_url, erp_app):
    create_in_erp(erp_app, {**ACME_INVOICE, "vendor": "Acme Corp"})
    result = make_dispatcher(erp_url).dispatch("verify_bill", ACME_INVOICE)
    assert result.output["verified"] is False
    assert result.output["bill_found"] is True
    assert result.output["mismatches"] == ["vendor"]


def test_verify_bill_does_not_trust_a_near_amount(erp_url):
    for amount in (3120.7, 3120.751, 31207.5, 0):
        result = make_dispatcher(erp_url).dispatch("verify_bill", {**SEEDED, "amount": amount})
        assert result.output["verified"] is False, amount


# --------------------------------------------------------------------------
# verify_bill: bad input and ERP down
# --------------------------------------------------------------------------

def test_verify_bill_validates_arguments(erp_url):
    dispatcher = make_dispatcher(erp_url)
    bad_inputs = [
        {k: v for k, v in SEEDED.items() if k != "amount"},        # missing field
        {**SEEDED, "amount": "3120.75"},                           # amount must be a number
        {**SEEDED, "invoice_date": "14/08/2026"},                  # wrong date format
        {**SEEDED, "vendor": ""},                                  # empty vendor
        {**SEEDED, "status": "paid"},                              # unknown field
    ]
    for arguments in bad_inputs:
        result = dispatcher.dispatch("verify_bill", arguments)
        assert result.success is False
        assert result.metadata["error_type"] == "invalid_arguments", arguments


def test_verify_bill_when_erp_is_unavailable(dead_erp_url):
    result = make_dispatcher(dead_erp_url).dispatch("verify_bill", SEEDED)
    assert result.success is False  # could not verify at all: this is not "verified=False"
    assert result.metadata["error_type"] == "erp_unavailable"
    assert result.output is None
