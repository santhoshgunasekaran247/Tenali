import base64
import binascii
import json
from datetime import date, datetime
from uuid import UUID

from fastapi import HTTPException


def decode_cursor(cursor: str | None, fields: tuple[str, ...]) -> dict:
    if not cursor:
        return {}
    try:
        payload = json.loads(base64.b64decode(cursor.encode("ascii") + b"=" * (-len(cursor) % 4), altchars=b"-_", validate=True))
        if not isinstance(payload, dict) or set(payload) != set(fields):
            raise ValueError("Invalid cursor fields")
        for field in fields:
            if not isinstance(payload[field], str):
                raise ValueError("Invalid cursor value")
            if field == "id":
                UUID(payload[field])
            elif field == "home_order":
                value = int(payload[field])
                if not -(2**31) <= value < 2**31:
                    raise ValueError("Invalid cursor value")
            elif field in ("created_at", "reminded_at"):
                datetime.fromisoformat(payload[field])
            elif field in ("transaction_date", "invoice_date", "purchase_date", "payment_date", "sort_date"):
                date.fromisoformat(payload[field])
        return payload
    except (ValueError, TypeError, UnicodeError, binascii.Error, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail="Invalid page cursor") from error


def cursor_page(rows, page_size: int, fields: tuple[str, ...]) -> dict:
    items = [dict(row) for row in rows[:page_size]]
    next_cursor = None
    if len(rows) > page_size and items:
        values = {field: str(items[-1][field]) for field in fields}
        next_cursor = base64.urlsafe_b64encode(json.dumps(values, separators=(",", ":")).encode()).decode().rstrip("=")
    return {"items": items, "next_cursor": next_cursor}
