"""SQLite access for MiniERP: connection handling, schema, and seed data."""
import sqlite3
from pathlib import Path

from flask import current_app, g
from werkzeug.security import generate_password_hash

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "minierp.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vendors (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS bills (
    id             INTEGER PRIMARY KEY,
    vendor_id      INTEGER NOT NULL REFERENCES vendors(id),
    invoice_number TEXT NOT NULL,
    amount_cents   INTEGER NOT NULL CHECK (amount_cents > 0),
    invoice_date   TEXT NOT NULL,          -- ISO date, YYYY-MM-DD
    description    TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'pending',
    created_at     TEXT NOT NULL,
    UNIQUE (vendor_id, invoice_number)     -- the same vendor can't bill the same number twice
);
"""

# Test-environment credentials. This is a mock ERP, not a real system.
SEED_USER = ("admin", "admin123")

SEED_VENDORS = [
    "Acme Industrial Supplies",
    "Northwind Logistics",
    "Globex Office Solutions",
    "Initech Software Licensing",
    "Summit Facility Services",
    "Bluepeak Cloud Hosting",
]

# (vendor, invoice_number, amount_cents, invoice_date, description, status)
SEED_BILLS = [
    ("Acme Industrial Supplies", "INV-2026-0388", 312075, "2026-08-14", "Q2 replenishment: steel brackets and fasteners", "paid"),
    ("Acme Industrial Supplies", "INV-2026-0402", 87550, "2026-09-03", "Workshop consumables: gloves, solvents, tape", "approved"),
    ("Northwind Logistics", "NW-77120", 154200, "2026-08-29", "Freight: Hyderabad to Pune, 12 pallets", "paid"),
    ("Northwind Logistics", "NW-77385", 98000, "2026-09-12", "Freight: warehouse transfer, September", "pending"),
    ("Globex Office Solutions", "GX-20418", 45990, "2026-09-05", "Office furniture: 6 ergonomic chairs", "approved"),
    ("Globex Office Solutions", "GX-20533", 12480, "2026-09-21", "Printer paper and toner, bulk order", "pending"),
    ("Initech Software Licensing", "INIT-9021", 720000, "2026-07-31", "Annual licence renewal: 40 seats", "paid"),
    ("Summit Facility Services", "SFS-5543", 64500, "2026-09-15", "Facility cleaning and maintenance, September", "pending"),
    ("Bluepeak Cloud Hosting", "BP-2026-09", 238615, "2026-09-30", "Cloud hosting usage, September", "pending"),
    ("Bluepeak Cloud Hosting", "BP-2026-08", 221040, "2026-08-31", "Cloud hosting usage, August", "paid"),
]

SEED_TIMESTAMP = "2026-10-01T09:00:00+00:00"


def get_db() -> sqlite3.Connection:
    """One connection per request, closed automatically at the end of it."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path: str) -> None:
    """Create tables and, on a brand-new database, insert the seed data."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            _seed(conn)
        conn.commit()
    finally:
        conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    username, password = SEED_USER
    conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, generate_password_hash(password)),
    )
    for name in SEED_VENDORS:
        conn.execute("INSERT INTO vendors (name) VALUES (?)", (name,))
    for vendor, number, cents, date, description, status in SEED_BILLS:
        vendor_id = conn.execute("SELECT id FROM vendors WHERE name = ?", (vendor,)).fetchone()[0]
        conn.execute(
            "INSERT INTO bills (vendor_id, invoice_number, amount_cents, invoice_date,"
            " description, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (vendor_id, number, cents, date, description, status, SEED_TIMESTAMP),
        )


def get_user_by_username(username: str):
    return get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
