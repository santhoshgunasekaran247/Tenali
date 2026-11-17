import json
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import text

from app.services.tenant_security import token_digest


def relay_cipher():
    try:
        return Fernet(os.getenv("TENALI_CREDENTIAL_KEY", "").encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise HTTPException(503, "Social login encryption is not configured on the platform") from error


def create_relay(db, company_id, hostname):
    relay_cipher()
    key = secrets.token_urlsafe(32)
    db.execute(text("delete from tenant_social_relays where expires_at<=now()"))
    relay_id = db.execute(text("""
        insert into tenant_social_relays(company_id,hostname,key_hash) values(:company,:host,:key) returning id
    """), {"company": company_id, "host": hostname, "key": token_digest(key)}).scalar_one()
    db.commit()
    return {"id": str(relay_id), "key": key}


def relay_row(db, relay_id, key):
    row = db.execute(text("""
        select id,company_id,hostname,result_ciphertext from tenant_social_relays
        where id=:id and key_hash=:key and expires_at>now() for update
    """), {"id": str(relay_id), "key": token_digest(key)}).mappings().first()
    if not row:
        raise HTTPException(410, "Social login expired or was already completed. Start again.")
    return row


def complete_relay(db, relay_id, key, result, hostname):
    row = relay_row(db, relay_id, key)
    if row["hostname"] != hostname or row["result_ciphertext"]:
        raise HTTPException(409, "Social login return domain or state does not match")
    encrypted = relay_cipher().encrypt(json.dumps(result).encode()).decode()
    db.execute(text("update tenant_social_relays set result_ciphertext=:result where id=:id"),
               {"id": str(relay_id), "result": encrypted})
    db.commit()
    return {"completed": True}


def poll_relay(db, relay_id, key, company_id, hostname):
    row = relay_row(db, relay_id, key)
    if str(row["company_id"]) != str(company_id) or row["hostname"] != hostname:
        raise HTTPException(403, "Social login belongs to another storefront")
    if not row["result_ciphertext"]:
        return {"pending": True}
    try:
        result = json.loads(relay_cipher().decrypt(row["result_ciphertext"].encode(), ttl=180))
    except (InvalidToken, ValueError, UnicodeError) as error:
        raise HTTPException(503, "Social login result is unavailable. Start again.") from error
    db.execute(text("delete from tenant_social_relays where id=:id"), {"id": str(relay_id)})
    db.commit()
    return {"pending": False, "result": result}
