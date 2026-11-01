import hashlib
import json
from decimal import Decimal

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text


def request_hash(payload) -> str:
    return hashlib.sha256(payload.model_dump_json().encode()).hexdigest()


def legacy_money_request_hash(payload) -> str:
    values = json.loads(payload.model_dump_json())
    for field in ("subtotal", "gst_total", "total", "amount_received", "amount_paid", "amount"):
        value = getattr(payload, field, None)
        if isinstance(value, Decimal):
            values[field] = float(value)
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def replay_posting(db, company_id: str, operation: str, payload):
    key = getattr(payload, "idempotency_key", None)
    if not key:
        return None
    db.execute(text("select pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": f"{company_id}:{operation}:{key}"})
    row = db.execute(text("select payload_hash,response from posting_requests where company_id=:company and operation=:operation and request_key=:key"),
                     {"company": company_id, "operation": operation, "key": key}).mappings().first()
    if row:
        if row["payload_hash"] not in {request_hash(payload), legacy_money_request_hash(payload)}:
            raise HTTPException(409, "This submission key was already used with different values; refresh before retrying")
        return row["response"]
    return None


def finish_posting(db, company_id: str, operation: str, payload, response, original_hash: str | None = None):
    key = getattr(payload, "idempotency_key", None)
    if key:
        db.execute(text("""insert into posting_requests(company_id,operation,request_key,payload_hash,response)
            values(:company,:operation,:key,:hash,cast(:response as jsonb))"""),
            {"company": company_id, "operation": operation, "key": key, "hash": original_hash or request_hash(payload),
             "response": json.dumps(jsonable_encoder(response))})