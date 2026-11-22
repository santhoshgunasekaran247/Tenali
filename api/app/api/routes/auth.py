import os
import secrets
from urllib.parse import urlparse
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.services.tenant_auth import TenantAuth
from app.services.tenant_context import CSRF_COOKIE, SESSION_COOKIE, company_by_slug, host_company,platform_host
from app.services.tenant_security import Login, MemberCreate, Registration, normalize_domain, token_digest
from app.services.tenant_security import password_hash,password_matches
from app.services.federation_settings import public_config
from app.services.shopper_federation import verified_identity
from app.services import domain_onboarding
from app.services.custom_domain_routing import custom_domains_enabled
from app.services import social_domain_relay

router = APIRouter()


def identity_db():
    with SessionLocal() as db:
        yield db


def check_origin(request: Request):
    origin = request.headers.get("Origin")
    if origin and urlparse(origin).netloc.lower() != request.url.netloc.lower():
        raise HTTPException(403, "Cross-origin authentication request rejected")


def current_identity(request: Request, db=Depends(identity_db)):
    check_origin(request)
    identity = TenantAuth(db).identity(request.cookies.get(SESSION_COOKIE))
    tenant = host_company(db, request)
    requested_slug=request.headers.get('X-Tenant-Slug')
    if requested_slug:
        selected=company_by_slug(db,requested_slug)
        if not selected or str(selected['id'])!=str(identity['company_id']):
            raise HTTPException(403,"Session belongs to a different workspace")
    if tenant and str(tenant["id"]) != str(identity["company_id"]):
        raise HTTPException(403, "Session does not belong to this domain's workspace")
    if request.method not in {"GET", "HEAD"}:
        csrf = request.cookies.get(CSRF_COOKIE)
        if not csrf or csrf != request.headers.get("X-CSRF-Token"):
            raise HTTPException(403, "Refresh the page before submitting")
    return identity


def administrator(identity=Depends(current_identity)):
    if identity["role"] not in {"owner", "admin"}:
        raise HTTPException(403, "Administrator access is required")
    return identity


def set_session(response: Response, request: Request, token: str):
    secure = request.url.scheme == "https" or os.getenv("TENALI_ENV") == "production"
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=secure, samesite="lax", max_age=43200, path="/")
    response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(32), httponly=False, secure=secure, samesite="lax", max_age=43200, path="/")
    response.headers["Cache-Control"] = "no-store"


def session_response(auth: TenantAuth, token: str):
    identity = auth.identity(token)
    return {"user": identity, "workspaces": auth.memberships(str(identity["user_id"]))}


@router.post("/register", status_code=201)
def register(payload: Registration, request: Request, response: Response, db=Depends(identity_db)):
    check_origin(request)
    if host_company(db, request):
        raise HTTPException(403, "Create a business workspace on the platform registration page")
    raise HTTPException(410, "Create a workspace using social login; handwritten email registration is disabled.")


class WorkspaceSocialRegistration(BaseModel):
    model_config = {"extra": "forbid"}
    company_name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r'^[a-z0-9](?:[a-z0-9-]{1,46}[a-z0-9])$', max_length=48)
    id_token: str = Field(min_length=1, max_length=10000, repr=False)
    _name = field_validator("company_name")(Registration.clean_name.__func__)
    _slug = field_validator("slug")(Registration.valid_slug.__func__)


class WorkspaceSocialLogin(BaseModel):
    model_config = {"extra": "forbid"}
    id_token: str = Field(min_length=1, max_length=10000, repr=False)


@router.get("/social-config")
def social_config(request: Request, db=Depends(identity_db)):
    check_origin(request)
    return public_config(db)


@router.get("/domain-health")
def domain_health(request: Request, db=Depends(identity_db)):
    company = host_company(db, request)
    if not company:
        raise HTTPException(404, "Verified tenant domain required")
    return {"company_id": str(company["id"])}


@router.get("/social-return-origin")
def social_return_origin(origin: str, request: Request, db=Depends(identity_db)):
    check_origin(request)
    if not platform_host(request):
        raise HTTPException(403, "Use the platform social login callback")
    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.hostname or origin != "https://" + parsed.hostname:
        raise HTTPException(422, "Invalid social login return origin")
    base = os.getenv("TENALI_BASE_DOMAIN", "").lower().strip(".")
    allowed = parsed.hostname in {base, "app." + base}
    if not allowed:
        allowed = bool(db.execute(text("""
            select domain.id from tenant_domains domain
            join companies company on company.id=domain.company_id and company.is_active=true
            where domain.hostname=:host and domain.verified_at is not null
              and domain.hosting_status in ('provisioning','tls_pending','active')
        """), {"host": parsed.hostname}).scalar_one_or_none())
    if not allowed:
        raise HTTPException(403, "Social login return domain is not a verified storefront")
    return {"allowed": True}


class RelayKey(BaseModel):
    key: str = Field(min_length=32, max_length=128, repr=False)


class RelayResult(BaseModel):
    accessToken: str | None = Field(default=None, max_length=10000, repr=False)
    email: str | None = Field(default=None, max_length=254)
    expiresAt: int | None = None
    error: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def complete_result(self):
        if not self.error and not (self.accessToken and self.email and self.expiresAt):
            raise ValueError("A completed social login or explicit error is required")
        return self


class RelayCompletion(RelayKey):
    origin: str = Field(max_length=261)
    result: RelayResult


@router.post("/social-relays", status_code=201)
def create_social_relay(request: Request, db=Depends(identity_db)):
    check_origin(request)
    tenant = host_company(db, request)
    if not custom_domains_enabled() or not tenant:
        raise HTTPException(403, "Social login relay requires a verified storefront")
    TenantAuth(db).throttle("social-relay:" + (request.client.host if request.client else "unknown"), 30)
    return social_domain_relay.create_relay(db, str(tenant["id"]), request.url.hostname)


@router.post("/social-relays/{relay_id}/complete")
def complete_social_relay(relay_id: UUID, payload: RelayCompletion, request: Request, db=Depends(identity_db)):
    social_return_origin(payload.origin, request, db)
    return social_domain_relay.complete_relay(
        db, relay_id, payload.key, payload.result.model_dump(exclude_none=True), urlparse(payload.origin).hostname,
    )


@router.post("/social-relays/{relay_id}/poll")
def poll_social_relay(relay_id: UUID, payload: RelayKey, request: Request, db=Depends(identity_db)):
    check_origin(request)
    tenant = host_company(db, request)
    if not tenant:
        raise HTTPException(403, "Open the storefront that started this login")
    return social_domain_relay.poll_relay(db, relay_id, payload.key, str(tenant["id"]), request.url.hostname)


@router.post("/register-social", status_code=201)
def register_social(payload: WorkspaceSocialRegistration, request: Request, response: Response, db=Depends(identity_db)):
    check_origin(request)
    if not platform_host(request) or host_company(db, request) or request.headers.get("X-Tenant-Slug"):
        raise HTTPException(403, "Create a workspace on the platform registration page")
    auth = TenantAuth(db)
    auth.throttle("register:" + (request.client.host if request.client else "unknown"), 8)
    social = verified_identity(payload.id_token, public_config(db))
    token = auth.register_federated(payload.company_name, payload.slug, social)
    set_session(response, request, token)
    return session_response(auth, token)


@router.post("/login-social")
def login_social(payload: WorkspaceSocialLogin, request: Request, response: Response, db=Depends(identity_db)):
    check_origin(request)
    auth = TenantAuth(db)
    auth.throttle("social-login:" + (request.client.host if request.client else "unknown"), 20)
    tenant = host_company(db, request)
    slug = request.headers.get("X-Tenant-Slug")
    if slug:
        selected = company_by_slug(db, slug)
        if not selected or (tenant and str(selected["id"]) != str(tenant["id"])):
            raise HTTPException(403, "Workspace selection does not match this domain")
        tenant = selected
    if not tenant:
        raise HTTPException(422, "Enter your workspace address before signing in")
    social = verified_identity(payload.id_token, public_config(db))
    token = auth.login_federated(str(tenant["id"]), social)
    set_session(response, request, token)
    return session_response(auth, token)


@router.post("/login")
def login(payload: Login, request: Request, response: Response, db=Depends(identity_db)):
    check_origin(request)
    auth = TenantAuth(db)
    auth.throttle("login-ip:"+(request.client.host if request.client else "unknown"),80)
    auth.throttle("login:"+payload.email.strip().lower()+":"+(request.client.host if request.client else "unknown"))
    tenant = host_company(db, request)
    if tenant and request.headers.get('X-Tenant-Slug'):
        selected=company_by_slug(db,request.headers['X-Tenant-Slug'])
        if not selected or str(selected['id'])!=str(tenant['id']):
            raise HTTPException(403,"Workspace does not match this domain")
    if not tenant and request.headers.get('X-Tenant-Slug'):
        tenant=company_by_slug(db,request.headers['X-Tenant-Slug'])
        if not tenant:
            raise HTTPException(404,'Workspace not found')
    token = auth.login(payload.email, payload.password, str(tenant["id"]) if tenant else None)
    set_session(response, request, token)
    return session_response(auth, token)


@router.get("/session")
def session(request: Request, response: Response, identity=Depends(current_identity), db=Depends(identity_db)):
    response.headers["Cache-Control"] = "no-store"
    if not request.cookies.get(CSRF_COOKIE):
        response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(32), secure=request.url.scheme=="https" or os.getenv("TENALI_ENV")=="production", samesite="lax", path="/")
    return {"user": identity, "workspaces": TenantAuth(db).memberships(str(identity["user_id"]))}


@router.post("/logout")
def logout(request: Request, response: Response, identity=Depends(current_identity), db=Depends(identity_db)):
    db.execute(text("delete from tenant_sessions where token_hash=:token"), {"token": token_digest(request.cookies.get(SESSION_COOKIE, ""))})
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"signed_out": True}


class PasswordChange(BaseModel):
    current_password:str=Field(min_length=1,max_length=128)
    new_password:str=Field(min_length=12,max_length=128)


@router.post('/password')
def change_password(payload:PasswordChange,request:Request,identity=Depends(current_identity),db=Depends(identity_db)):
    stored=db.execute(text('select password_hash from tenant_users where id=:id for update'),{'id':str(identity['user_id'])}).scalar_one()
    if not stored:
        raise HTTPException(422, "This account uses social login. Manage its password with your social provider.")
    if not password_matches(payload.current_password,stored):
        raise HTTPException(422,'Current password is incorrect')
    db.execute(text('update tenant_users set password_hash=:hash where id=:id'),{'hash':password_hash(payload.new_password),'id':str(identity['user_id'])})
    db.execute(text('delete from tenant_sessions where user_id=:id and token_hash<>:current'),{'id':str(identity['user_id']),'current':token_digest(request.cookies.get(SESSION_COOKIE,''))})
    db.commit()
    return {'changed':True}


class WorkspaceSwitch(BaseModel):
    company_id: UUID


class WorkspaceCreate(BaseModel):
    company_name:str=Field(min_length=1,max_length=200)
    slug:str=Field(pattern=r'^[a-z0-9](?:[a-z0-9-]{1,46}[a-z0-9])$',max_length=48)
    password:str=Field(min_length=12,max_length=128)
    _name=field_validator('company_name')(Registration.clean_name.__func__)
    _slug=field_validator('slug')(Registration.valid_slug.__func__)


@router.post('/workspaces',status_code=201)
def create_workspace(payload:WorkspaceCreate,request:Request,response:Response,identity=Depends(current_identity),db=Depends(identity_db)):
    if not platform_host(request) or request.headers.get('X-Tenant-Slug'):
        raise HTTPException(403,'Create additional workspaces from the platform application')
    raise HTTPException(410, "Use the platform social-login registration page to create another workspace.")


@router.post("/switch")
def switch(payload: WorkspaceSwitch, request: Request, response: Response, identity=Depends(current_identity), db=Depends(identity_db)):
    tenant = host_company(db, request)
    if tenant and str(tenant["id"]) != str(payload.company_id):
        raise HTTPException(403, "Switch workspaces from the platform application, not another company's domain")
    auth = TenantAuth(db)
    token = auth.switch(identity, str(payload.company_id))
    db.execute(text("delete from tenant_sessions where token_hash=:token"), {"token": token_digest(request.cookies.get(SESSION_COOKIE, ""))})
    db.commit()
    set_session(response, request, token)
    return session_response(auth, token)


@router.get("/team")
def team(page_size: int | None = Query(None, ge=1, le=100),
         cursor: str | None = Query(None, max_length=1000),
         search: str = Query("", max_length=300),
         identity=Depends(administrator), db=Depends(identity_db)):
    service = TenantAuth(db)
    if page_size is None:
        if cursor or search:
            raise HTTPException(422, "page_size is required with search or cursor")
        return {"items": service.team(str(identity["company_id"]))}
    return service.team_page(str(identity["company_id"]), page_size, cursor, search)


@router.post("/team", status_code=201)
def create_member(payload: MemberCreate, return_team: bool = True, identity=Depends(administrator), db=Depends(identity_db)):
    return {"items": TenantAuth(db).add_member(str(identity["company_id"]), payload, str(identity["user_id"]), return_team=return_team)}


class MemberUpdate(BaseModel):
    role: str = Field(pattern=r"^(admin|staff|viewer)$")
    is_active: bool
    store_ids: list[UUID] | None = Field(default=None, max_length=100)
    modules: list[Literal["billing", "purchases", "inventory", "receivables", "accounts", "settlements", "reports", "parties", "masters", "orders"]] | None = Field(default=None, max_length=20)


@router.put("/team/{user_id}")
def update_member(user_id: UUID, payload: MemberUpdate, return_team: bool = True, identity=Depends(administrator), db=Depends(identity_db)):
    return {"items": TenantAuth(db).update_member(str(identity["company_id"]), str(user_id), payload.role, payload.is_active, str(identity["user_id"]), payload.store_ids, payload.modules, return_team=return_team)}


class DomainInput(BaseModel):
    hostname: str = Field(max_length=253)
    _host = field_validator("hostname")(normalize_domain)


@router.get("/domains")
def domains(identity=Depends(administrator), db=Depends(identity_db)):
    rows = db.execute(text(f"select {domain_onboarding.DOMAIN_COLUMNS} from tenant_domains where company_id=:company order by created_at"), {"company": str(identity["company_id"])}).mappings().all()
    enabled = custom_domains_enabled()
    config = None
    if enabled:
        from app.services.render_domains import get_config
        config = get_config()
        if config is None:
            raise HTTPException(503, "Automatic domain hosting is not configured by the platform administrator")
    items = []
    for row in rows:
        item = dict(row)
        if config:
            item["dns_records"] = domain_onboarding.dns_records(
                row["hostname"], row["verification_token"], config.web_host, config.api_host, config.apex_ip,
            )
        items.append(item)
    return {"items": items, "automatic_hosting": enabled,
            "cname_target": os.getenv("TENALI_DOMAIN_TARGET", ""), "base_domain": os.getenv("TENALI_BASE_DOMAIN", "")}


@router.post("/domains", status_code=201)
def add_domain(payload: DomainInput, identity=Depends(administrator), db=Depends(identity_db)):
    try:
        domain_onboarding.create_claim(db, str(identity["company_id"]), payload.hostname)
        TenantAuth(db).audit(str(identity['company_id']),str(identity['user_id']),'DOMAIN_CLAIMED',details={'hostname':payload.hostname})
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "This domain is already registered") from error
    return domains(identity, db)


@router.post("/domains/{domain_id}/verify")
def verify_domain(domain_id: UUID, identity=Depends(administrator), db=Depends(identity_db)):
    row = db.execute(text(f"select {domain_onboarding.DOMAIN_COLUMNS} from tenant_domains where id=:id and company_id=:company for update"), {"id": str(domain_id), "company": str(identity["company_id"])}).mappings().first()
    if not row:
        raise HTTPException(404, "Domain not found")
    if row["hosting_status"] != "manual" and not custom_domains_enabled():
        raise HTTPException(503, "Automatic hosting is disabled; ask the platform operator to enable domain provisioning")
    if row["hosting_status"] == "removing":
        raise HTTPException(409, "Domain removal is in progress")
    try:
        domain_onboarding.verify_ownership(db, row)
        TenantAuth(db).audit(str(identity['company_id']),str(identity['user_id']),'DOMAIN_VERIFIED',str(domain_id),{'hostname':row['hostname']})
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409,"This domain is already verified for another workspace") from error
    return domains(identity, db)


@router.delete("/domains/{domain_id}")
def delete_domain(domain_id: UUID, identity=Depends(administrator), db=Depends(identity_db)):
    row = db.execute(text("select hosting_status from tenant_domains where id=:id and company_id=:company for update"),
                     {"id": str(domain_id), "company": str(identity["company_id"])}).mappings().first()
    if not row:
        raise HTTPException(404, "Domain not found")
    if row["hosting_status"] != "manual" and not custom_domains_enabled():
        raise HTTPException(503, "Automatic hosting is disabled; ask the platform operator to enable managed domain cleanup")
    retained = db.execute(text("""select hostname from tenant_domain_bindings
        where domain_id=:id and render_id is not null and provider_owned=false"""),
        {"id": str(domain_id)}).scalars().all()
    if row["hosting_status"] != "manual":
        db.execute(text("""update tenant_domains set hosting_status='removing',verified_at=null,
            hosting_error=null,next_check_at=now() where id=:id"""), {"id": str(domain_id)})
    else:
        db.execute(text("delete from tenant_domains where id=:id"), {"id": str(domain_id)})
    TenantAuth(db).audit(str(identity['company_id']),str(identity['user_id']),'DOMAIN_REMOVED',str(domain_id))
    db.commit()
    return {"removed": row["hosting_status"] == "manual", "removing": row["hosting_status"] != "manual",
            "retained_hosting": retained}