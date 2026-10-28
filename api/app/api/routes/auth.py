import os
import secrets
from urllib.parse import urlparse
from uuid import UUID

import dns.exception
import dns.resolver
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.services.tenant_auth import TenantAuth
from app.services.tenant_context import CSRF_COOKIE, SESSION_COOKIE, company_by_slug, host_company,platform_host
from app.services.tenant_security import Login, MemberCreate, Registration, normalize_domain, token_digest
from app.services.tenant_security import password_hash,password_matches

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
    auth = TenantAuth(db)
    auth.throttle("register:"+(request.client.host if request.client else "unknown"), 8)
    token = auth.register(payload)
    set_session(response, request, token)
    return session_response(auth, token)


@router.post("/login")
def login(payload: Login, request: Request, response: Response, db=Depends(identity_db)):
    check_origin(request)
    auth = TenantAuth(db)
    auth.throttle("login-ip:"+(request.client.host if request.client else "unknown"),80)
    auth.throttle("login:"+payload.email.strip().lower()+":"+(request.client.host if request.client else "unknown"))
    tenant = host_company(db, request)
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
    _name=field_validator('company_name')(Registration.clean_name.__func__)
    _slug=field_validator('slug')(Registration.valid_slug.__func__)


@router.post('/workspaces',status_code=201)
def create_workspace(payload:WorkspaceCreate,request:Request,response:Response,identity=Depends(current_identity),db=Depends(identity_db)):
    if not platform_host(request) or request.headers.get('X-Tenant-Slug'):
        raise HTTPException(403,'Create additional workspaces from the platform application')
    auth=TenantAuth(db)
    auth.throttle('workspace:'+str(identity['user_id']),5)
    token=auth.create_workspace(str(identity['user_id']),payload.company_name,payload.slug)
    db.execute(text('delete from tenant_sessions where token_hash=:token'),{'token':token_digest(request.cookies.get(SESSION_COOKIE,''))})
    db.commit()
    set_session(response,request,token)
    return session_response(auth,token)


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
def team(identity=Depends(administrator), db=Depends(identity_db)):
    return {"items": TenantAuth(db).team(str(identity["company_id"]))}


@router.post("/team", status_code=201)
def create_member(payload: MemberCreate, identity=Depends(administrator), db=Depends(identity_db)):
    return {"items": TenantAuth(db).add_member(str(identity["company_id"]), payload,str(identity['user_id']))}


class MemberUpdate(BaseModel):
    role: str = Field(pattern=r"^(admin|staff|viewer)$")
    is_active: bool


@router.put("/team/{user_id}")
def update_member(user_id: UUID, payload: MemberUpdate, identity=Depends(administrator), db=Depends(identity_db)):
    return {"items": TenantAuth(db).update_member(str(identity["company_id"]), str(user_id), payload.role, payload.is_active,str(identity['user_id']))}


class DomainInput(BaseModel):
    hostname: str = Field(max_length=253)
    _host = field_validator("hostname")(normalize_domain)


@router.get("/domains")
def domains(identity=Depends(administrator), db=Depends(identity_db)):
    rows = db.execute(text("select id,hostname,verification_token,verified_at from tenant_domains where company_id=:company order by created_at"), {"company": str(identity["company_id"])}).mappings().all()
    return {"items": [dict(row) for row in rows], "cname_target": os.getenv("TENALI_DOMAIN_TARGET", ""), "base_domain": os.getenv("TENALI_BASE_DOMAIN", "")}


@router.post("/domains", status_code=201)
def add_domain(payload: DomainInput, identity=Depends(administrator), db=Depends(identity_db)):
    base = os.getenv("TENALI_BASE_DOMAIN", "").lower().strip(".")
    if base and (payload.hostname == base or payload.hostname.endswith("."+base)):
        raise HTTPException(422, "Platform domains cannot be claimed as custom domains")
    try:
        db.execute(text("insert into tenant_domains(company_id,hostname,verification_token) values(:company,:host,:token)"),
                   {"company": str(identity["company_id"]), "host": payload.hostname, "token": secrets.token_urlsafe(32)})
        TenantAuth(db).audit(str(identity['company_id']),str(identity['user_id']),'DOMAIN_CLAIMED',details={'hostname':payload.hostname})
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "This domain is already registered") from error
    return domains(identity, db)


@router.post("/domains/{domain_id}/verify")
def verify_domain(domain_id: UUID, identity=Depends(administrator), db=Depends(identity_db)):
    row = db.execute(text("select hostname,verification_token from tenant_domains where id=:id and company_id=:company"), {"id": str(domain_id), "company": str(identity["company_id"])}).mappings().first()
    if not row:
        raise HTTPException(404, "Domain not found")
    try:
        answers = dns.resolver.resolve("_tenali-verification."+row["hostname"], "TXT", lifetime=5)
        values = [b"".join(answer.strings).decode() for answer in answers]
    except (dns.exception.DNSException, UnicodeDecodeError) as error:
        raise HTTPException(422, "Verification TXT record is not visible yet. Check DNS and try again.") from error
    if row["verification_token"] not in values:
        raise HTTPException(422, "DNS ownership token does not match")
    try:
        db.execute(text("update tenant_domains set verified_at=now() where id=:id and company_id=:company"), {"id": str(domain_id), "company": str(identity["company_id"])})
        TenantAuth(db).audit(str(identity['company_id']),str(identity['user_id']),'DOMAIN_VERIFIED',str(domain_id),{'hostname':row['hostname']})
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409,"This domain is already verified for another workspace") from error
    return domains(identity, db)


@router.delete("/domains/{domain_id}")
def delete_domain(domain_id: UUID, identity=Depends(administrator), db=Depends(identity_db)):
    db.execute(text("delete from tenant_domains where id=:id and company_id=:company"), {"id": str(domain_id), "company": str(identity["company_id"])})
    TenantAuth(db).audit(str(identity['company_id']),str(identity['user_id']),'DOMAIN_REMOVED',str(domain_id))
    db.commit()
    return {"removed": True}