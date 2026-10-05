"""MiniERP: a deliberately small mock ERP used as a test environment for the agent."""
import os
from functools import wraps

from flask import (
    Flask,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from erp import bills as bill_store
from erp import db


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("MINIERP_SECRET_KEY", "minierp-dev-secret-not-for-real-use"),
        DATABASE=os.environ.get("MINIERP_DB_PATH", str(db.DEFAULT_DB_PATH)),
        # Session-expiry failure mode. 0 = disabled. N > 0 = after N successful browser
        # actions the session is invalidated and the next browser request is sent to /login.
        SESSION_EXPIRY_ACTIONS=int(os.environ.get("MINIERP_SESSION_EXPIRY_ACTIONS", "0")),
        # Browsers share cookies across ports on localhost, so use a distinctive name.
        SESSION_COOKIE_NAME="minierp_session",
    )
    if test_config:
        app.config.update(test_config)

    db.init_db(app.config["DATABASE"])
    app.teardown_appcontext(db.close_db)

    @app.template_filter("money")
    def money(cents: int) -> str:
        return f"${cents / 100:,.2f}"

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def browser_login_required(view):
        """Protect an HTML page. Also implements the deliberate session-expiry failure.

        The session carries an `actions` counter. Each browser request that succeeds
        (status < 400, redirects included) increments it. Once the counter reaches
        SESSION_EXPIRY_ACTIONS, the NEXT protected browser request is NOT executed:
        the session is cleared and the browser is redirected to /login?expired=1.
        If that request was a form submission, the submission is lost.
        """

        @wraps(view)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))

            limit = current_app.config["SESSION_EXPIRY_ACTIONS"]
            if limit > 0 and session.get("actions", 0) >= limit:
                session.clear()
                return redirect(url_for("login", expired=1))

            response = make_response(view(*args, **kwargs))
            if response.status_code < 400:
                session["actions"] = session.get("actions", 0) + 1
            return response

        return wrapper

    def api_login_required(view):
        """Protect a JSON endpoint. Same session cookie as the browser.

        API calls neither count toward nor trigger session expiry; they only
        fail with 401 if the session is already gone.
        """

        @wraps(view)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return jsonify(error="authentication required"), 401
            return view(*args, **kwargs)

        return wrapper

    # ------------------------------------------------------------------
    # Auth routes
    # ------------------------------------------------------------------

    @app.get("/")
    def index():
        return redirect(url_for("dashboard"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = db.get_user_by_username(request.form.get("username", "").strip())
            if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
                session.clear()
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session["actions"] = 0
                return redirect(url_for("dashboard"))
            return render_template("login.html", error="Invalid username or password."), 401
        return render_template("login.html", expired=request.args.get("expired") == "1")

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ------------------------------------------------------------------
    # Browser pages
    # ------------------------------------------------------------------

    @app.get("/dashboard")
    @browser_login_required
    def dashboard():
        return render_template(
            "dashboard.html",
            stats=bill_store.dashboard_stats(),
            recent=bill_store.list_bills()[:5],
        )

    @app.get("/bills")
    @browser_login_required
    def bills_page():
        return render_template("bills.html", bills=bill_store.list_bills())

    @app.route("/bills/new", methods=["GET", "POST"])
    @browser_login_required
    def new_bill():
        vendors = bill_store.list_vendor_names()
        if request.method == "GET":
            return render_template("bill_new.html", errors={}, form={}, vendors=vendors)

        clean, errors = bill_store.validate_bill(request.form)
        status = 400
        if not errors:
            try:
                bill_id = bill_store.create_bill(clean)
            except bill_store.DuplicateBill:
                errors["invoice_number"] = "This vendor already has a bill with that invoice number."
                status = 409
            else:
                flash(f"Bill #{bill_id} created for {clean['vendor']}.", "success")
                return redirect(url_for("bills_page"))
        return render_template("bill_new.html", errors=errors, form=request.form, vendors=vendors), status

    # ------------------------------------------------------------------
    # JSON API
    # ------------------------------------------------------------------

    @app.get("/api/bills")
    @api_login_required
    def api_list_bills():
        return jsonify(bills=[bill_store.to_dict(row) for row in bill_store.list_bills()])

    @app.get("/api/bills/<int:bill_id>")
    @api_login_required
    def api_get_bill(bill_id: int):
        row = bill_store.get_bill(bill_id)
        if row is None:
            return jsonify(error=f"bill {bill_id} not found"), 404
        return jsonify(bill_store.to_dict(row))

    @app.post("/api/bills")
    @api_login_required
    def api_create_bill():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="request body must be a JSON object"), 400

        clean, errors = bill_store.validate_bill(data)
        if errors:
            return jsonify(error="validation failed", details=errors), 400
        try:
            bill_id = bill_store.create_bill(clean)
        except bill_store.DuplicateBill:
            return jsonify(
                error="duplicate bill",
                details={"invoice_number": "This vendor already has a bill with that invoice number."},
            ), 409
        bill = bill_store.to_dict(bill_store.get_bill(bill_id))
        return jsonify(bill), 201, {"Location": url_for("api_get_bill", bill_id=bill_id)}

    return app
