"""Bill validation and queries. Used by both the HTML form and the JSON API."""
import re
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from erp.db import get_db

MAX_AMOUNT = Decimal("10000000")  # 10 million: a sanity limit
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_BILL_SELECT = """
    SELECT b.id, v.name AS vendor, b.invoice_number, b.amount_cents,
           b.invoice_date, b.description, b.status, b.created_at
    FROM bills b JOIN vendors v ON v.id = b.vendor_id
"""


class DuplicateBill(Exception):
    """The vendor already has a bill with this invoice number."""


def validate_bill(data) -> tuple[dict, dict]:
    """Validate raw input (form or JSON). Returns (clean_values, errors)."""

    def text(field: str) -> str:
        value = data.get(field)
        return "" if value is None else str(value).strip()

    errors: dict[str, str] = {}

    vendor = text("vendor")
    if not vendor:
        errors["vendor"] = "Vendor is required."
    elif len(vendor) > 100:
        errors["vendor"] = "Vendor must be 100 characters or fewer."

    invoice_number = text("invoice_number")
    if not invoice_number:
        errors["invoice_number"] = "Invoice number is required."
    elif len(invoice_number) > 50:
        errors["invoice_number"] = "Invoice number must be 50 characters or fewer."

    amount_cents = None
    raw_amount = text("amount")
    if not raw_amount:
        errors["amount"] = "Amount is required."
    else:
        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            errors["amount"] = "Amount must be a number."
        else:
            if not amount.is_finite() or amount <= 0 or amount > MAX_AMOUNT:
                errors["amount"] = f"Amount must be greater than 0 and at most {MAX_AMOUNT:,}."
            elif amount != amount.quantize(Decimal("0.01")):
                errors["amount"] = "Amount can have at most 2 decimal places."
            else:
                amount_cents = int(amount * 100)

    invoice_date = text("invoice_date")
    if not invoice_date:
        errors["invoice_date"] = "Invoice date is required."
    else:
        try:
            if not _DATE_RE.match(invoice_date):
                raise ValueError
            date.fromisoformat(invoice_date)
        except ValueError:
            errors["invoice_date"] = "Invoice date must be a real date in YYYY-MM-DD format."

    description = text("description")
    if len(description) > 500:
        errors["description"] = "Description must be 500 characters or fewer."

    clean = {
        "vendor": vendor,
        "invoice_number": invoice_number,
        "amount_cents": amount_cents,
        "invoice_date": invoice_date,
        "description": description,
    }
    return clean, errors


def create_bill(clean: dict) -> int:
    """Insert a validated bill (creating the vendor if new). Returns the new bill id."""
    db = get_db()
    db.execute("INSERT OR IGNORE INTO vendors (name) VALUES (?)", (clean["vendor"],))
    vendor_id = db.execute("SELECT id FROM vendors WHERE name = ?", (clean["vendor"],)).fetchone()["id"]
    try:
        cursor = db.execute(
            "INSERT INTO bills (vendor_id, invoice_number, amount_cents, invoice_date,"
            " description, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (
                vendor_id,
                clean["invoice_number"],
                clean["amount_cents"],
                clean["invoice_date"],
                clean["description"],
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
    except sqlite3.IntegrityError:
        db.rollback()
        raise DuplicateBill from None
    db.commit()
    return cursor.lastrowid


def list_bills():
    return get_db().execute(_BILL_SELECT + " ORDER BY b.id DESC").fetchall()


def get_bill(bill_id: int):
    return get_db().execute(_BILL_SELECT + " WHERE b.id = ?", (bill_id,)).fetchone()


def list_vendor_names() -> list[str]:
    rows = get_db().execute("SELECT name FROM vendors ORDER BY name").fetchall()
    return [row["name"] for row in rows]


def dashboard_stats() -> dict:
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS bill_count,"
        " COALESCE(SUM(amount_cents), 0) AS total_cents,"
        " COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 END), 0) AS pending_count,"
        " COALESCE(SUM(CASE WHEN status = 'pending' THEN amount_cents END), 0) AS pending_cents"
        " FROM bills"
    ).fetchone()
    stats = dict(row)
    stats["vendor_count"] = db.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
    return stats


def to_dict(row) -> dict:
    """A bill row as JSON-friendly data."""
    return {
        "id": row["id"],
        "vendor": row["vendor"],
        "invoice_number": row["invoice_number"],
        "amount": row["amount_cents"] / 100,
        "invoice_date": row["invoice_date"],
        "description": row["description"],
        "status": row["status"],
        "created_at": row["created_at"],
    }
