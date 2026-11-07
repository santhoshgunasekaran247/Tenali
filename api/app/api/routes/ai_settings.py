from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text

from app.api.routes.platform import admin_identity
from app.api.routes.auth import identity_db
from app.dependencies import get_db
from app.ai.capabilities import platform_capabilities, save_capability, save_tenant_capability
from app.ai.schemas import CapabilityKey, CapabilityUpdate, TenantCapabilityUpdate
from app.services.feature_controls import (
    FeatureUpdate, PlatformAIUpdate, TenantAIUpdate, TenantLimitUpdate,
    company_features, platform_settings, save_feature, save_platform_settings,
    save_tenant_ai, save_tenant_limits, tenant_limits,
)

platform_router = APIRouter()
tenant_router = APIRouter()


@platform_router.get("/ai/capabilities")
def capabilities(company_id: UUID | None = None, identity=Depends(admin_identity), db=Depends(identity_db)):
    return platform_capabilities(db, company_id)


@platform_router.patch("/ai/capabilities/{key}")
def update_capability(key: CapabilityKey, payload: CapabilityUpdate, identity=Depends(admin_identity), db=Depends(identity_db)):
    return save_capability(db, key, payload, identity["id"])


@platform_router.patch("/ai/tenants/{company_id}/capabilities/{key}")
def update_tenant_capability(company_id: UUID, key: CapabilityKey, payload: TenantCapabilityUpdate,
                            identity=Depends(admin_identity), db=Depends(identity_db)):
    return save_tenant_capability(db, company_id, key, payload, identity["id"])


@platform_router.get("/ai/settings")
def settings(identity=Depends(admin_identity), db=Depends(identity_db)):
    return platform_settings(db)


@platform_router.get("/ai/usage")
def usage(offset: int = Query(0, ge=0), identity=Depends(admin_identity), db=Depends(identity_db)):
    rows = db.execute(text("""select company_id,model,count(*) as requests,sum(charged_tokens) as tokens,
        sum(charged_cost) as cost,count(*) filter(where status<>'settled') as unconfirmed
        from ai_usage_reservations where created_at>=date_trunc('month',now() at time zone 'UTC') at time zone 'UTC'
        group by company_id,model order by company_id,model limit 50 offset :offset"""), {"offset": offset}).mappings()
    return {"items": [dict(row) for row in rows], "currency": "USD", "period": "Current UTC month"}


@platform_router.put("/ai/settings")
def update_settings(payload: PlatformAIUpdate, identity=Depends(admin_identity), db=Depends(identity_db)):
    return save_platform_settings(db, payload, identity["id"])


@platform_router.get("/workspaces/{company_id}/features")
def features(company_id: UUID, identity=Depends(admin_identity), db=Depends(identity_db)):
    return company_features(db, company_id)


@platform_router.patch("/workspaces/{company_id}/features")
def update_features(company_id: UUID, payload: FeatureUpdate, identity=Depends(admin_identity), db=Depends(identity_db)):
    return save_feature(db, company_id, payload, identity["id"])


@platform_router.get("/ai/tenants/{company_id}")
def limits(company_id: UUID, identity=Depends(admin_identity), db=Depends(identity_db)):
    return tenant_limits(db, company_id)


@platform_router.patch("/ai/tenants/{company_id}")
def update_limits(company_id: UUID, payload: TenantLimitUpdate, identity=Depends(admin_identity), db=Depends(identity_db)):
    return save_tenant_limits(db, company_id, payload, identity["id"])


@tenant_router.get("/settings")
def tenant_settings(request: Request, db=Depends(get_db)):
    return company_features(db, request.state.tenant["company_id"])


@tenant_router.patch("/settings")
def update_tenant_settings(payload: TenantAIUpdate, request: Request, db=Depends(get_db)):
    if request.state.tenant["role"] not in {"owner", "admin"}:
        raise HTTPException(403, "Administrator access is required")
    return save_tenant_ai(db, request.state.tenant["company_id"], payload)
