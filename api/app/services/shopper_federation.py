import logging
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import text

from app.services.customer_contacts import normalize_email, normalize_phone
from app.services.federation_settings import FederationSettings, token_claims

logger = logging.getLogger(__name__)
ACCOUNT_COLUMNS = "id,email,display_name,phone,customer_party_id"


def verified_identity(token: str, config: dict | None = None) -> dict:
    if not config or not config["enabled"]:
        raise HTTPException(503, "Social login is not configured or is disabled")
    try:
        settings = FederationSettings(supabase_url=config["supabase"]["url"],
            public_key=config["supabase"]["publicKey"], providers=config["providers"], enabled=True)
    except ValueError as error:
        raise HTTPException(503, "Supabase social-login configuration is invalid") from error
    try:
        response = httpx.get(settings.supabase_url + "/auth/v1/user",
            headers={"apikey": settings.public_key, "Authorization": "Bearer " + token}, timeout=10, follow_redirects=False)
    except httpx.RequestError as error:
        logger.warning("Supabase identity service is unavailable (%s)", type(error).__name__)
        raise HTTPException(503, "Unable to verify social login. Please retry.") from None
    if response.status_code in (401, 403):
        raise HTTPException(401, "Federated login is invalid or expired. Sign in again.")
    if response.status_code != 200:
        logger.warning("Supabase identity verification returned HTTP %s", response.status_code)
        raise HTTPException(503, "Unable to verify social login. Check Supabase configuration or retry.")
    # /user authenticates the token first. Editable user_metadata never supplies identity.
    try:
        user = response.json()
        claims = token_claims(token)
        uid = str(UUID(user["id"]))
        if claims.get("sub") != uid or claims.get("iss") != settings.supabase_url + "/auth/v1":
            raise ValueError("Identity or issuer mismatch")
        if claims.get("role") != "authenticated" or user.get("is_anonymous"):
            raise HTTPException(422, "Anonymous and non-user login are not accepted.")
        methods = claims.get("amr", [])
        if not isinstance(methods, list) or not any(isinstance(item, dict) and item.get("method") == "oauth" for item in methods):
            raise HTTPException(422, "Use a social account. Email/password, OTP and magic links are not accepted.")
        provider = user.get("app_metadata", {}).get("provider")
        if provider not in settings.providers:
            raise HTTPException(422, "Use an enabled social login provider.")
        profile = next((item.get("identity_data", {}) for item in user.get("identities", [])
                        if item.get("provider") == provider), {})
        email = normalize_email(profile.get("email"))
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise HTTPException(401, "Supabase returned an invalid social identity. Sign in again.") from error
    if not email:
        raise HTTPException(422, "The login provider must supply an email. Try Google.")
    return {"uid": uid, "email": email, "name": str(profile.get("full_name") or profile.get("name") or "")}


def federated_account(db, company_id, identity, phone=None, display_name=None):
    db.execute(text("select pg_advisory_xact_lock(hashtextextended(:key,0))"),
               {"key": f"shopper-identity:{company_id}:{identity['uid']}"})
    account = db.execute(text(f"""select {ACCOUNT_COLUMNS},is_active from shopper_accounts
        where company_id=:company and supabase_uid=:uid for update"""),
        {"company": company_id, "uid": identity["uid"]}).mappings().first()
    if account:
        if not account["is_active"]:
            raise HTTPException(403, "This shopper account is inactive. Contact the store.")
        return dict(account)
    # A matching email or typed phone is not permission to claim a legacy account.
    existing_email = db.execute(text("select id from shopper_accounts where company_id=:company and email=:email"),
                                {"company": company_id, "email": identity["email"]}).scalar_one_or_none()
    if existing_email:
        raise HTTPException(409, "An existing account uses this email. Contact the store for account recovery; accounts are not automatically merged.")
    try:
        normalized = normalize_phone(phone, required=True)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    name = (display_name or identity["name"]).strip()
    if not name or len(name) > 150:
        raise HTTPException(422, "Enter your name (up to 150 characters)")
    return dict(db.execute(text(f"""insert into shopper_accounts
        (company_id,email,display_name,supabase_uid,phone)
        values(:company,:email,:name,:uid,:phone) returning {ACCOUNT_COLUMNS}"""),
        {"company": company_id, "email": identity["email"], "name": name, "uid": identity["uid"],
         "phone": normalized}).mappings().one())


def link_customer(db, company_id, shopper_id, party_id, actor_id):
    account = db.execute(text("""select id,customer_party_id from shopper_accounts
        where company_id=:company and id=:id and is_active for update"""),
        {"company": company_id, "id": shopper_id}).mappings().first()
    if not account:
        raise HTTPException(404, "Shopper not found")
    if account["customer_party_id"]:
        if str(account["customer_party_id"]) == str(party_id):
            return {"linked": True}
        raise HTTPException(409, "This shopper is already linked. Relinking requires identity review.")
    db.execute(text("select pg_advisory_xact_lock(hashtextextended(:key,0))"),
               {"key": f"shopper-customer:{company_id}:{party_id}"})
    party = db.execute(text("""select id from parties where company_id=:company and id=:party
        and is_active and system_role is null and party_type in ('customer','customer_vendor') for update"""),
        {"company": company_id, "party": party_id}).scalar_one_or_none()
    if not party:
        raise HTTPException(422, "Select an active counter customer in this workspace")
    claimed = db.execute(text("select id from shopper_accounts where company_id=:company and customer_party_id=:party"),
                         {"company": company_id, "party": party_id}).scalar_one_or_none()
    if claimed:
        raise HTTPException(409, "This counter customer is already linked to another online account")
    db.execute(text("""update shopper_accounts set customer_party_id=:party,linked_by=:actor,linked_at=now()
        where company_id=:company and id=:id"""),
        {"company": company_id, "id": shopper_id, "party": party_id, "actor": actor_id})
    db.execute(text("""insert into audit_events(company_id,actor_user_id,action,entity_type,entity_id,new_value,source_type)
        values(:company,:actor,'CUSTOMER_LINKED','shopper_account',:id,
        jsonb_build_object('customer_party_id',cast(:party as text)),'manual_customer_link')"""),
        {"company": company_id, "actor": actor_id, "id": shopper_id, "party": str(party_id)})
    db.commit()
    return {"linked": True}
