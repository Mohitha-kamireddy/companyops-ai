"""get_bills and verify_bill: read-only tools that query MiniERP's JSON API."""
from decimal import Decimal
from typing import Any

from backend.app.tools.base import Tool, ToolError
from backend.app.tools.erp_client import ERPAuthError, ERPClient, ERPError, ERPUnavailable


def _fetch_bills(client: ERPClient) -> list[dict[str, Any]]:
    """GET /api/bills, translating ERP client failures into ToolErrors."""
    try:
        payload = client.get_json("/api/bills")
    except ERPUnavailable as exc:
        raise ToolError(str(exc), error_type="erp_unavailable", retryable=True) from None
    except ERPAuthError as exc:
        raise ToolError(str(exc), error_type="erp_auth_failed") from None
    except ERPError as exc:
        raise ToolError(str(exc), error_type="erp_error", retryable=True) from None

    bills = payload.get("bills") if isinstance(payload, dict) else None
    if not isinstance(bills, list):
        raise ToolError("ERP returned an unexpected response shape for /api/bills", error_type="erp_error")
    return bills


class GetBillsTool(Tool):
    name = "get_bills"
    description = (
        "Fetch all bills currently recorded in the ERP (MiniERP GET /api/bills), newest first. "
        "Each bill has id, vendor, invoice_number, amount, invoice_date, description, status."
    )
    input_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    def __init__(self, client: ERPClient):
        self._client = client

    def execute(self) -> dict[str, Any]:
        bills = _fetch_bills(self._client)
        return {"count": len(bills), "bills": bills}


def _norm(text: Any) -> str:
    """Collapse runs of whitespace and trim, so layout differences don't cause false mismatches."""
    return " ".join(str(text).split())


class VerifyBillTool(Tool):
    name = "verify_bill"
    description = (
        "Independently check that a bill exists in the ERP with exactly the expected values. "
        "Looks the bill up by invoice_number in the ERP's own records and compares vendor, "
        "invoice_number, amount, invoice_date and description. "
        "Read output.verified: it is true only if the bill exists and every field matches. "
        "A failed verification is a normal result (success=true, verified=false) and "
        "output.checks shows exactly which fields differ."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "vendor": {"type": "string", "minLength": 1, "description": "Expected vendor name."},
            "invoice_number": {"type": "string", "minLength": 1, "description": "Expected invoice number."},
            "amount": {"type": "number", "description": "Expected amount, e.g. 4825.5."},
            "invoice_date": {
                "type": "string",
                "pattern": r"^\d{4}-\d{2}-\d{2}$",
                "description": "Expected invoice date, YYYY-MM-DD.",
            },
            "description": {"type": "string", "description": "Expected description (may be empty)."},
        },
        "required": ["vendor", "invoice_number", "amount", "invoice_date", "description"],
        "additionalProperties": False,
    }

    def __init__(self, client: ERPClient):
        self._client = client

    def execute(
        self, vendor: str, invoice_number: str, amount: float, invoice_date: str, description: str
    ) -> dict[str, Any]:
        bills = _fetch_bills(self._client)

        wanted_number = invoice_number.strip()
        with_number = [b for b in bills if str(b.get("invoice_number", "")).strip() == wanted_number]
        if not with_number:
            return {
                "verified": False,
                "bill_found": False,
                "bill_id": None,
                "checks": {},
                "mismatches": ["invoice_number"],
                "message": f"No bill with invoice number '{wanted_number}' exists in the ERP.",
            }

        # Prefer the record whose vendor also matches; otherwise report it with a vendor mismatch.
        bill = next((b for b in with_number if _norm(b.get("vendor", "")).casefold() == _norm(vendor).casefold()), with_number[0])

        checks = {
            "vendor": self._check(vendor, bill.get("vendor"), _norm(vendor).casefold() == _norm(bill.get("vendor", "")).casefold()),
            "invoice_number": self._check(invoice_number, bill.get("invoice_number"), True),
            "amount": self._check(amount, bill.get("amount"), self._amounts_equal(amount, bill.get("amount"))),
            "invoice_date": self._check(invoice_date, bill.get("invoice_date"), invoice_date == bill.get("invoice_date")),
            "description": self._check(description, bill.get("description"), _norm(description) == _norm(bill.get("description", ""))),
        }
        mismatches = [name for name, check in checks.items() if not check["match"]]
        verified = not mismatches
        message = (
            f"ERP record #{bill.get('id')} matches all expected fields."
            if verified
            else f"ERP record #{bill.get('id')} exists but these fields differ: {', '.join(mismatches)}."
        )
        return {
            "verified": verified,
            "bill_found": True,
            "bill_id": bill.get("id"),
            "checks": checks,
            "mismatches": mismatches,
            "message": message,
        }

    @staticmethod
    def _check(expected: Any, actual: Any, match: bool) -> dict[str, Any]:
        return {"expected": expected, "actual": actual, "match": match}

    @staticmethod
    def _amounts_equal(expected: Any, actual: Any) -> bool:
        try:
            return Decimal(str(expected)) == Decimal(str(actual))
        except Exception:  # actual missing or not numeric
            return False
