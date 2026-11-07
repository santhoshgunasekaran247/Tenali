import os
import re
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import text

FeatureKey = Literal["ai", "storefront"]


class AIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    global_enabled: bool = False
    routine_model: str = Field(default="", max_length=100)
    document_model: str = Field(default="", max_length=100)
    daily_request_limit: int = Field(default=50, ge=1, le=10000)
    monthly_token_limit: int = Field(default=1000000, ge=1, le=1000000000)
    monthly_cost_limit: int = Field(default=10, ge=1, le=10000)
    max_output_tokens: int = Field(default=2000, ge=100, le=32000)
    timeout_seconds: int = Field(default=60, ge=10, le=120)
    retention_days: int = Field(default=90, ge=1, le=3650)
    support_url: str = Field(default="", max_length=300)
    input_cost_per_million: Decimal = Field(default=Decimal("0"), ge=0, le=1000, max_digits=10, decimal_places=6)
    output_cost_per_million: Decimal = Field(default=Decimal("0"), ge=0, le=1000, max_digits=10, decimal_places=6)

    @field_validator("routine_model", "document_model")
    @classmethod
    def model_identifier(cls, value: str) -> str:
        if value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value):
            raise ValueError("Use a model identifier, not a URL or credential")
        return value

    @field_validator("support_url")
    @classmethod
    def support_destination(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
            return value
        if parsed.scheme == "mailto" and re.fullmatch(r"[^@\s?]+@[^@\s?]+\.[^@\s?]+", parsed.path) and not parsed.query and not parsed.fragment:
            return value
        raise ValueError("Use an HTTPS support URL or a mailto email address")

    @model_validator(mode="after")
    def enabled_models(self):
        if self.global_enabled and (not self.routine_model or not self.document_model):
            raise ValueError("Configure both models before enabling the global AI switch")
        return self


class AIOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    daily_request_limit: int | None = Field(default=None, ge=1, le=10000)
    monthly_token_limit: int | None = Field(default=None, ge=1, le=1000000000)
    monthly_cost_limit: int | None = Field(default=None, ge=1, le=10000)


class PlatformAIUpdate(AIConfig):
    expected_version: int = Field(ge=1)


class TenantLimitUpdate(AIOverrides):
    expected_version: int = Field(ge=1)


class FeatureUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature_key: FeatureKey
    platform_allowed: bool
    expected_version: int = Field(ge=1)


class TenantAIUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_enabled: bool
    expected_version: int = Field(ge=1)


class FeatureStatus(BaseModel):
    platform_allowed: bool
    tenant_enabled: bool
    effective_enabled: bool
    reason: str | None
    version: int


class CompanyFeatures(BaseModel):
    ai: FeatureStatus
    storefront: FeatureStatus
    ai_settings_version: int
    support_url: str


def platform_settings(db) -> dict:
    row = db.execute(text("select config,version from ai_platform_settings where id=true")).mappings().first()
    if not row:
        raise HTTPException(503, "AI platform settings are missing. Contact the platform administrator.")
    try:
        config = AIConfig.model_validate(row["config"])
    except ValidationError as error:
        raise HTTPException(503, "AI platform settings are invalid. Contact the platform administrator.") from error
    return {**config.model_dump(), "version": row["version"],
            "provider_configured": bool(os.getenv("OPENAI_API_KEY", "").strip()),
            "runtime_ready": True,
            "model_ready": config.routine_model in {value.strip() for value in os.getenv("OPENAI_ALLOWED_MODELS", "").split(",") if value.strip()}
                and config.input_cost_per_million > 0 and config.output_cost_per_million > 0}


def company_features(db, company_id) -> dict:
    company = db.execute(text("select is_active,storefront_enabled from companies where id=:id"),
                         {"id": str(company_id)}).mappings().first()
    if not company:
        raise HTTPException(404, "Workspace not found")
    rows = db.execute(text("select feature_key,platform_allowed,version from tenant_feature_controls where company_id=:id"),
                      {"id": str(company_id)}).mappings().all()
    controls = {row["feature_key"]: row for row in rows}
    preference = db.execute(text("select tenant_enabled,version from ai_tenant_settings where company_id=:id"),
                            {"id": str(company_id)}).mappings().first()
    if set(controls) != {"ai", "storefront"} or not preference:
        raise HTTPException(503, "Workspace feature settings are missing. Contact the platform administrator.")
    config = platform_settings(db)
    result = {}
    for key, control in controls.items():
        enabled = preference["tenant_enabled"] if key == "ai" else company["storefront_enabled"]
        reason = None
        if not company["is_active"]:
            reason = "workspace_disabled"
        elif not control["platform_allowed"]:
            reason = "platform_disabled"
        elif key == "ai" and not config["global_enabled"]:
            reason = "platform_ai_disabled"
        elif not enabled:
            reason = "tenant_disabled"
        elif key == "ai" and not config["runtime_ready"]:
            reason = "ai_not_available"
        elif key == "ai" and not config["provider_configured"]:
            reason = "provider_not_configured"
        elif key == "ai" and not config["model_ready"]:
            reason = "model_not_configured"
        result[key] = {"platform_allowed": control["platform_allowed"], "tenant_enabled": enabled,
                       "effective_enabled": reason is None, "reason": reason, "version": control["version"]}
    return {**result, "ai_settings_version": preference["version"], "support_url": config["support_url"]}


def audit_platform(db, admin_id, action, company_id=None):
    db.execute(text("insert into platform_audit(admin_id,company_id,action) values(:admin,:company,:action)"),
               {"admin": admin_id, "company": company_id, "action": action})


def lock_policy(db):
    # A shared advisory key serializes policy writes without granting tenant UPDATE on platform tables.
    db.execute(text("select pg_advisory_xact_lock(hashtextextended('tenali:feature-policy',0))"))


def save_platform_settings(db, payload: PlatformAIUpdate, admin_id):
    # Lock the singleton while checking tenant ceilings so a concurrent override cannot race this save.
    lock_policy(db)
    current = db.execute(text("select version from ai_platform_settings where id=true")).scalar_one_or_none()
    if current != payload.expected_version:
        raise HTTPException(409, "AI settings changed. Reload before saving.")
    config = AIConfig.model_validate(payload.model_dump(exclude={"expected_version"}))
    rows = db.execute(text("select config from ai_tenant_limits")).mappings()
    for row in rows:
        validate_limits(row["config"], config.model_dump())
    db.execute(text("""update ai_platform_settings set config=cast(:config as jsonb),version=version+1,
        updated_at=now(),updated_by=:admin where id=true"""), {"config": config.model_dump_json(), "admin": admin_id})
    audit_platform(db, admin_id, "AI_PLATFORM_SETTINGS_UPDATED")
    db.commit()
    return platform_settings(db)


def validate_limits(overrides, defaults):
    try:
        values = AIOverrides.model_validate(overrides).model_dump()
    except ValidationError as error:
        raise HTTPException(503, "Tenant AI limits are invalid. Contact the platform administrator.") from error
    if any(value is not None and value > defaults[key] for key, value in values.items()):
        raise HTTPException(422, "Tenant AI limits cannot exceed platform limits. Reset or lower tenant overrides first.")
    return {key: defaults[key] if value is None else value for key, value in values.items()}


def tenant_limits(db, company_id):
    row = db.execute(text("select config,version from ai_tenant_limits where company_id=:company"),
                     {"company": str(company_id)}).mappings().first()
    if not row:
        raise HTTPException(404, "Workspace AI limits not found")
    defaults = platform_settings(db)
    effective = validate_limits(row["config"], defaults)
    return {"overrides": AIOverrides.model_validate(row["config"]).model_dump(),
            "effective": effective, "version": row["version"]}


def save_tenant_limits(db, company_id, payload: TenantLimitUpdate, admin_id):
    lock_policy(db)
    config = AIOverrides.model_validate(payload.model_dump(exclude={"expected_version"}))
    validate_limits(config.model_dump(), platform_settings(db))
    updated = db.execute(text("""update ai_tenant_limits set config=cast(:config as jsonb),version=version+1,
        updated_at=now(),updated_by=:admin where company_id=:company and version=:version returning company_id"""),
        {"config": config.model_dump_json(), "admin": admin_id, "company": str(company_id), "version": payload.expected_version}).first()
    if not updated:
        raise HTTPException(409, "Tenant AI limits changed or workspace is missing. Reload before saving.")
    audit_platform(db, admin_id, "AI_TENANT_LIMITS_UPDATED", company_id)
    db.commit()
    return tenant_limits(db, company_id)


def save_feature(db, company_id, payload: FeatureUpdate, admin_id):
    lock_policy(db)
    updated = db.execute(text("""update tenant_feature_controls set platform_allowed=:allowed,version=version+1,
        updated_at=now(),updated_by=:admin where company_id=:company and feature_key=:feature
        and version=:version returning id"""),
        {"allowed": payload.platform_allowed, "admin": admin_id, "company": str(company_id),
         "feature": payload.feature_key, "version": payload.expected_version}).first()
    if not updated:
        raise HTTPException(409, "Feature settings changed or workspace is missing. Reload before saving.")
    audit_platform(db, admin_id, f"{payload.feature_key.upper()}_PLATFORM_{'ENABLED' if payload.platform_allowed else 'DISABLED'}", company_id)
    db.commit()
    return company_features(db, company_id)


def save_tenant_ai(db, company_id, payload: TenantAIUpdate):
    lock_policy(db)
    status = company_features(db, company_id)
    if payload.tenant_enabled and not status["ai"]["tenant_enabled"]:
        if not status["ai"]["platform_allowed"] or status["ai"]["reason"] == "platform_ai_disabled":
            raise HTTPException(403, "AI is disabled by Tenali Platform. Contact the platform administrator.")
    updated = db.execute(text("""update ai_tenant_settings set tenant_enabled=:enabled,version=version+1,updated_at=now()
        where company_id=:company and version=:version returning id"""),
        {"enabled": payload.tenant_enabled, "company": str(company_id), "version": payload.expected_version}).first()
    if not updated:
        raise HTTPException(409, "Tenant AI settings changed. Reload before saving.")
    db.commit()
    return company_features(db, company_id)
