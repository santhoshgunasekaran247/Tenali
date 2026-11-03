from fastapi import APIRouter, Depends, Request

from app.api.routes.auth import administrator, identity_db
from app.api.routes.platform import admin_identity
from app.schemas.policies import PolicyKind, PolicyPublish, PolicySave, PolicyScope
from app.services import policies
from app.services.customer_security import storefront_company

public_router = APIRouter()
tenant_router = APIRouter()
platform_router = APIRouter()


@public_router.get("/{scope}")
def public_policies(scope: PolicyScope, request: Request, db=Depends(identity_db)):
    company_id = str(storefront_company(db, request)["id"]) if scope == "tenant" else None
    return policies.published_list(db, company_id)


@public_router.get("/{scope}/{kind}")
def public_policy(scope: PolicyScope, kind: PolicyKind, request: Request, db=Depends(identity_db)):
    company_id = str(storefront_company(db, request)["id"]) if scope == "tenant" else None
    return policies.published_document(db, company_id, kind)


@tenant_router.get("")
def tenant_drafts(identity=Depends(administrator), db=Depends(identity_db)):
    return policies.drafts(db, str(identity["company_id"]), identity["email"])


@tenant_router.put("/{kind}")
def save_tenant_policy(kind: PolicyKind, payload: PolicySave, identity=Depends(administrator), db=Depends(identity_db)):
    return policies.save_draft(db, str(identity["company_id"]), kind, payload, str(identity["user_id"]))


@tenant_router.post("/{kind}/publish")
def publish_tenant_policy(kind: PolicyKind, payload: PolicyPublish, identity=Depends(administrator), db=Depends(identity_db)):
    return policies.publish(db, str(identity["company_id"]), kind, payload, str(identity["user_id"]))


@platform_router.get("")
def platform_drafts(identity=Depends(admin_identity), db=Depends(identity_db)):
    return policies.drafts(db, None)


@platform_router.put("/{kind}")
def save_platform_policy(kind: PolicyKind, payload: PolicySave, identity=Depends(admin_identity), db=Depends(identity_db)):
    return policies.save_draft(db, None, kind, payload, str(identity["id"]))


@platform_router.post("/{kind}/publish")
def publish_platform_policy(kind: PolicyKind, payload: PolicyPublish, identity=Depends(admin_identity), db=Depends(identity_db)):
    return policies.publish(db, None, kind, payload, str(identity["id"]))
