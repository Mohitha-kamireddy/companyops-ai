"""Tests for MiniERP (erp/): login, bills, JSON API, and the session-expiry failure mode."""
ADMIN = {"username": "admin", "password": "admin123"}

NEW_BILL = {
    "vendor": "Acme Industrial Supplies",
    "invoice_number": "INV-2026-0417",
    "amount": "4825.50",
    "invoice_date": "2026-09-18",
    "description": "Q3 bulk order - hydraulic fittings and safety equipment",
}


def login(client):
    return client.post("/login", data=ADMIN)


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------

def test_login_page_renders(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b'id="login-form"' in response.data


def test_login_success_creates_session(client):
    response = login(client)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
    assert client.get("/dashboard").status_code == 200


def test_login_wrong_password_is_rejected(client):
    response = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert response.status_code == 401
    assert b"Invalid username or password" in response.data
    assert client.get("/dashboard").status_code == 302  # still logged out


def test_pages_require_login(client):
    for path in ("/dashboard", "/bills", "/bills/new"):
        response = client.get(path)
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")


def test_logout_ends_session(logged_in_client):
    assert logged_in_client.get("/logout").status_code == 302
    assert logged_in_client.get("/bills").headers["Location"].endswith("/login")


# --------------------------------------------------------------------------
# Dashboard and bills pages
# --------------------------------------------------------------------------

def test_seed_data_is_shown(logged_in_client):
    assert b"Bluepeak Cloud Hosting" in logged_in_client.get("/dashboard").data  # dashboard shows the 5 newest
    page = logged_in_client.get("/bills").data
    assert b"INV-2026-0388" in page and b"NW-77385" in page


# --------------------------------------------------------------------------
# Creating a bill through the form
# --------------------------------------------------------------------------

def test_create_bill_via_form(logged_in_client):
    response = logged_in_client.post("/bills/new", data=NEW_BILL, follow_redirects=True)
    assert response.status_code == 200
    assert b"created for Acme Industrial Supplies" in response.data
    assert b"INV-2026-0417" in response.data
    assert b"$4,825.50" in response.data


def test_create_bill_with_new_vendor_creates_vendor(logged_in_client):
    data = {**NEW_BILL, "vendor": "Brand New Vendor Ltd", "invoice_number": "BN-1"}
    logged_in_client.post("/bills/new", data=data)
    bills = logged_in_client.get("/api/bills").get_json()["bills"]
    assert any(b["vendor"] == "Brand New Vendor Ltd" for b in bills)


def test_create_bill_invalid_amount_is_rejected(logged_in_client):
    before = len(logged_in_client.get("/api/bills").get_json()["bills"])
    response = logged_in_client.post("/bills/new", data={**NEW_BILL, "amount": "-5"})
    assert response.status_code == 400
    assert b'id="error-amount"' in response.data
    assert b'value="Acme Industrial Supplies"' in response.data  # form keeps what was typed
    assert len(logged_in_client.get("/api/bills").get_json()["bills"]) == before


def test_create_bill_duplicate_invoice_is_rejected(logged_in_client):
    logged_in_client.post("/bills/new", data=NEW_BILL)
    response = logged_in_client.post("/bills/new", data=NEW_BILL)
    assert response.status_code == 409
    assert b"already has a bill" in response.data


# --------------------------------------------------------------------------
# JSON API
# --------------------------------------------------------------------------

def test_api_requires_login(client):
    assert client.get("/api/bills").status_code == 401
    assert client.get("/api/bills/1").status_code == 401
    assert client.post("/api/bills", json=NEW_BILL).status_code == 401


def test_api_list_bills(logged_in_client):
    response = logged_in_client.get("/api/bills")
    assert response.status_code == 200
    bills = response.get_json()["bills"]
    assert len(bills) == 10
    first = bills[0]
    assert set(first) == {
        "id", "vendor", "invoice_number", "amount", "invoice_date",
        "description", "status", "created_at",
    }
    assert isinstance(first["amount"], float)


def test_api_get_bill_and_404(logged_in_client):
    bill = logged_in_client.get("/api/bills/1").get_json()
    assert bill["id"] == 1
    assert logged_in_client.get("/api/bills/9999").status_code == 404


def test_api_create_bill(logged_in_client):
    response = logged_in_client.post("/api/bills", json={**NEW_BILL, "amount": 4825.5})
    assert response.status_code == 201
    created = response.get_json()
    assert created["amount"] == 4825.5
    assert created["status"] == "pending"
    assert response.headers["Location"].endswith(f"/api/bills/{created['id']}")
    assert logged_in_client.get(f"/api/bills/{created['id']}").get_json() == created
    assert len(logged_in_client.get("/api/bills").get_json()["bills"]) == 11


def test_api_create_bill_validation_and_duplicate(logged_in_client):
    bad = logged_in_client.post("/api/bills", json={"vendor": "X"})
    assert bad.status_code == 400
    assert "amount" in bad.get_json()["details"]
    assert logged_in_client.post("/api/bills", data="not json").status_code == 400

    assert logged_in_client.post("/api/bills", json=NEW_BILL).status_code == 201
    assert logged_in_client.post("/api/bills", json=NEW_BILL).status_code == 409


# --------------------------------------------------------------------------
# Deliberate session-expiry failure mode
# --------------------------------------------------------------------------

def test_session_expiry_is_off_by_default(make_app):
    client = make_app().test_client()
    login(client)
    for _ in range(15):
        assert client.get("/dashboard").status_code == 200


def test_session_expires_after_configured_number_of_actions(make_app):
    client = make_app(SESSION_EXPIRY_ACTIONS=2).test_client()
    login(client)
    assert client.get("/dashboard").status_code == 200   # action 1
    assert client.get("/bills").status_code == 200       # action 2

    response = client.get("/bills/new")                  # over the limit
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login?expired=1")

    # The session really is gone, not just redirected once.
    assert client.get("/dashboard").headers["Location"].endswith("/login")
    assert client.get("/api/bills").status_code == 401


def test_expired_login_page_shows_message(make_app):
    client = make_app(SESSION_EXPIRY_ACTIONS=1).test_client()
    login(client)
    client.get("/dashboard")
    page = client.get("/bills", follow_redirects=True)
    assert b'id="session-expired"' in page.data


def test_expiry_loses_the_submission(make_app):
    client = make_app(SESSION_EXPIRY_ACTIONS=2).test_client()
    login(client)
    client.get("/dashboard")                                # action 1
    client.get("/bills/new")                                # action 2
    response = client.post("/bills/new", data=NEW_BILL)     # bounced, not executed
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login?expired=1")

    login(client)
    invoice_numbers = [b["invoice_number"] for b in client.get("/api/bills").get_json()["bills"]]
    assert NEW_BILL["invoice_number"] not in invoice_numbers


def test_logging_in_again_resets_the_counter(make_app):
    client = make_app(SESSION_EXPIRY_ACTIONS=1).test_client()
    login(client)
    client.get("/dashboard")
    assert client.get("/bills").status_code == 302          # expired
    login(client)
    assert client.get("/bills").status_code == 200          # works again


def test_failed_submissions_do_not_count_as_actions(make_app):
    client = make_app(SESSION_EXPIRY_ACTIONS=2).test_client()
    login(client)
    assert client.post("/bills/new", data={**NEW_BILL, "amount": "-5"}).status_code == 400
    assert client.get("/dashboard").status_code == 200      # action 1
    assert client.get("/bills").status_code == 200          # action 2
    assert client.get("/bills/new").status_code == 302      # over the limit


def test_api_calls_do_not_count_toward_expiry(make_app):
    client = make_app(SESSION_EXPIRY_ACTIONS=1).test_client()
    login(client)
    for _ in range(5):
        assert client.get("/api/bills").status_code == 200
    assert client.get("/dashboard").status_code == 200      # action 1
    assert client.get("/bills").status_code == 302          # over the limit


def test_expiry_limit_can_come_from_environment(make_app, monkeypatch):
    monkeypatch.setenv("MINIERP_SESSION_EXPIRY_ACTIONS", "1")
    client = make_app().test_client()
    login(client)
    assert client.get("/dashboard").status_code == 200
    assert client.get("/bills").status_code == 302
