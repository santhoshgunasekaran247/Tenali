import base64
import json
import os
import re

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from sqlalchemy import text

PROVIDERS = {"google", "facebook", "custom:yahoo", "azure", "apple"}


def token_claims(token: str) -> dict:
    """Decode only; callers must independently authenticate user tokens."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Expected a JWT")
    claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    if not isinstance(claims, dict):
        raise ValueError("Expected JWT claims")
    return claims


class FederationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supabase_url: str = Field(max_length=253)
    public_key: str = Field(max_length=2000, repr=False)
    providers: list[str] = Field(min_length=1, max_length=5)
    enabled: bool = False

    @field_validator("supabase_url")
    @classmethod
    def project_url(cls, value):
        value = value.strip().rstrip("/")
        if value and not re.fullmatch(r"https://[a-z0-9]{20}\.supabase\.co", value):
            raise ValueError("Enter the hosted Supabase project URL (https://<project-ref>.supabase.co)")
        return value

    @field_validator("public_key")
    @classmethod
    def browser_key(cls, value):
        value = value.strip()
        if not value or re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]{10,}", value):
            return value
        try:
            if token_claims(value).get("role") == "anon":
                return value
        except (ValueError, UnicodeDecodeError):
            pass
        raise ValueError("Use a public publishable or legacy anon key, never a secret/service-role key")

    @field_validator("providers")
    @classmethod
    def provider_list(cls, value):
        if len(set(value)) != len(value) or not set(value) <= PROVIDERS:
            raise ValueError("Choose distinct supported social providers")
        return value

    @model_validator(mode="after")
    def enabled_configuration(self):
        if self.enabled and (not self.supabase_url or not self.public_key):
            raise ValueError("Project URL and public key are required to enable social login")
        return self


def settings_for(db):
    row = db.execute(text("select supabase_url,public_key,providers,enabled from platform_auth_settings where id=true")).mappings().first()
    if row:
        return dict(row)
    return {"supabase_url": os.getenv("TENALI_SUPABASE_URL", "").strip(),
            "public_key": os.getenv("TENALI_SUPABASE_PUBLIC_KEY", "").strip(),
            "providers": [value.strip() for value in os.getenv("TENALI_SUPABASE_PROVIDERS", "google,facebook").split(",") if value.strip()],
            "enabled": os.getenv("TENALI_SUPABASE_AUTH_ENABLED", "").lower() == "true"}


def public_config(db):
    try:
        settings = FederationSettings(**settings_for(db))
    except ValueError as error:
        raise HTTPException(503, "Supabase social-login settings are invalid. Contact the platform administrator.") from error
    return {"enabled": settings.enabled,
            "supabase": {"url": settings.supabase_url, "publicKey": settings.public_key},
            "providers": settings.providers}


def save_settings(db, payload, admin_id):
    previous = settings_for(db)
    if previous["supabase_url"] and payload.supabase_url != previous["supabase_url"]:
        identities = db.execute(text("""select exists(select 1 from shopper_accounts where supabase_uid is not null)
            or exists(select 1 from tenant_users where supabase_uid is not null)""")).scalar_one()
        if identities:
            raise HTTPException(409, "The Supabase project cannot change after social accounts exist. A managed identity migration is required.")
    db.execute(text("""insert into platform_auth_settings(id,supabase_url,public_key,providers,enabled)
        values(true,:supabase_url,:public_key,:providers,:enabled)
        on conflict(id) do update set supabase_url=excluded.supabase_url,public_key=excluded.public_key,
        providers=excluded.providers,enabled=excluded.enabled,updated_at=now()"""), payload.model_dump())
    db.execute(text("insert into platform_audit(admin_id,action) values(:admin,'SOCIAL_LOGIN_SETTINGS_UPDATED')"), {"admin": admin_id})
    db.commit()
    return {"saved": True, "message": "Public Supabase settings saved. Configure providers and redirect URLs in Supabase, then test a real login."}
