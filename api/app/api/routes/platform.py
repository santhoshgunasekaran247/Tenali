import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.api.routes.auth import identity_db
from app.services.customer_security import ADMIN_COOKIE, ADMIN_CSRF, SHOP_COOKIE, check_write, ensure_csrf, expiry, set_cookies, verify_password
from app.services.tenant_auth import TenantAuth
from app.services.tenant_context import host_company, platform_host, SESSION_COOKIE
from app.services.tenant_security import Login, token_digest
from app.services.federation_settings import FederationSettings, settings_for, save_settings

router = APIRouter()


def platform_request(request: Request, db=Depends(identity_db)):
    if not platform_host(request) or host_company(db, request) or request.headers.get("X-Tenant-Slug"):
        raise HTTPException(403, "Platform administration is available only on the platform host")
    if request.cookies.get(SESSION_COOKIE):
        try:
            TenantAuth(db).identity(request.cookies[SESSION_COOKIE])
        except HTTPException as error:
            if error.status_code != 401:
                raise
        else:
            raise HTTPException(403, "Workspace accounts cannot access platform administration. Sign out of the workspace first.")
    if request.cookies.get(SHOP_COOKIE) and db.execute(text("""select 1 from shopper_sessions s
        join shopper_accounts a on a.id=s.shopper_id and a.company_id=s.company_id and a.is_active
        join companies c on c.id=s.company_id and c.is_active
        where s.token_hash=:token and s.expires_at>now()"""),
        {"token": token_digest(request.cookies[SHOP_COOKIE])}).first():
        raise HTTPException(403, "Shopper accounts cannot access platform administration. Sign out of the shopper account first.")
    check_write(request)


def admin_identity(request: Request, gate=Depends(platform_request), db=Depends(identity_db)):
    check_write(request, ADMIN_CSRF)
    row = db.execute(text("""select admin.id,admin.email,admin.display_name from platform_sessions session
        join platform_admins admin on admin.id=session.admin_id and admin.is_active=true
        where session.token_hash=:token and session.expires_at>now()"""),
        {"token": token_digest(request.cookies.get(ADMIN_COOKIE, ""))}).mappings().first()
    if not row:
        raise HTTPException(401, "Platform administrator sign-in required")
    return dict(row)


@router.get("/social-login")
def social_settings(identity=Depends(admin_identity), db=Depends(identity_db)):
    return settings_for(db)


@router.put("/social-login")
def update_social_settings(payload: FederationSettings, identity=Depends(admin_identity), db=Depends(identity_db)):
    return save_settings(db, payload, identity["id"])


@router.post("/login")
def login(payload: Login, request: Request, response: Response, gate=Depends(platform_request), db=Depends(identity_db)):
    TenantAuth(db).throttle("platform-login:" + (request.client.host if request.client else "unknown"), 15)
    row = db.execute(text("select * from platform_admins where email=:email"),
                     {"email": payload.email.strip().lower()}).mappings().first()
    verify_password(payload.password, row["password_hash"] if row and row["is_active"] else None)
    token = secrets.token_urlsafe(48)
    db.execute(text("delete from platform_sessions where expires_at<now()"))
    db.execute(text("insert into platform_sessions(token_hash,admin_id,expires_at) values(:token,:admin,:expires)"),
               {"token": token_digest(token), "admin": row["id"], "expires": expiry()})
    db.execute(text("insert into platform_audit(admin_id,action) values(:admin,'LOGIN')"), {"admin": row["id"]})
    db.commit()
    set_cookies(response, request, token, ADMIN_COOKIE, ADMIN_CSRF)
    return {"id": row["id"], "email": row["email"], "display_name": row["display_name"]}


@router.get("/session")
def session(request: Request, response: Response, identity=Depends(admin_identity)):
    ensure_csrf(response, request, ADMIN_CSRF)
    return identity


@router.post("/logout")
def logout(request: Request, response: Response, identity=Depends(admin_identity), db=Depends(identity_db)):
    db.execute(text("delete from platform_sessions where token_hash=:token"),
               {"token": token_digest(request.cookies.get(ADMIN_COOKIE, ""))})
    db.commit()
    response.delete_cookie(ADMIN_COOKIE, path="/")
    response.delete_cookie(ADMIN_CSRF, path="/")
    return {"signed_out": True}


@router.get("/workspaces")
def workspaces(offset: int = Query(0, ge=0), identity=Depends(admin_identity), db=Depends(identity_db)):
    return {"items": [dict(row) for row in db.execute(text("""select id,company_name,tenant_slug,is_active
        from companies order by company_name,id limit 50 offset :offset"""), {"offset": offset}).mappings()]}


class WorkspaceStatus(BaseModel):
    is_active: bool


@router.patch("/workspaces/{company_id}")
def workspace_status(company_id: UUID, payload: WorkspaceStatus, identity=Depends(admin_identity), db=Depends(identity_db)):
    row = db.execute(text("update companies set is_active=:active where id=:company returning id"),
                     {"company": company_id, "active": payload.is_active}).first()
    if not row:
        raise HTTPException(404, "Workspace not found")
    if not payload.is_active:
        db.execute(text("delete from tenant_sessions where company_id=:company"), {"company": company_id})
        db.execute(text("delete from shopper_sessions where company_id=:company"), {"company": company_id})
    db.execute(text("insert into platform_audit(admin_id,company_id,action) values(:admin,:company,:action)"),
               {"admin": identity["id"], "company": company_id, "action": "WORKSPACE_ENABLED" if payload.is_active else "WORKSPACE_DISABLED"})
    db.commit()
    return {"updated": True}
