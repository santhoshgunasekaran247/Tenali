import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import HTTPException, Request, Response
from sqlalchemy import text

from app.services.tenant_context import company_by_slug, host_company, platform_host
from app.services.tenant_security import PASSWORD_ITERATIONS, password_matches, token_digest

SHOP_COOKIE = "tenali_shopper"
SHOP_CSRF = "tenali_shopper_csrf"
ADMIN_COOKIE = "tenali_platform"
ADMIN_CSRF = "tenali_platform_csrf"


def check_write(request: Request, csrf_cookie: str | None = None):
    if request.method in {"GET", "HEAD"}:
        return
    origin = request.headers.get("Origin")
    if origin and urlparse(origin).netloc.lower() != request.url.netloc.lower():
        raise HTTPException(403, "Cross-origin request rejected")
    if csrf_cookie:
        csrf = request.cookies.get(csrf_cookie)
        if not csrf or not secrets.compare_digest(csrf, request.headers.get("X-CSRF-Token", "")):
            raise HTTPException(403, "Refresh the page before submitting")


def storefront_company(db, request: Request):
    company = host_company(db, request)
    if not company and not platform_host(request):
        raise HTTPException(404, "This domain is not configured for a workspace")
    slug = request.headers.get("X-Tenant-Slug")
    if slug:
        selected = company_by_slug(db, slug)
        if not selected or (company and str(selected["id"]) != str(company["id"])):
            raise HTTPException(404, "Workspace not found")
        company = selected
    if not company:
        raise HTTPException(422, "Open a workspace storefront first")
    return company


def verify_password(password: str, stored: str | None):
    dummy = f"pbkdf2_sha256${PASSWORD_ITERATIONS}$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    matched = password_matches(password, stored or dummy)
    if not stored or not matched:
        raise HTTPException(401, "Email or password is incorrect")


def expiry():
    return datetime.now(timezone.utc) + timedelta(hours=12)


def set_cookies(response: Response, request: Request, token: str, cookie: str, csrf: str):
    secure = request.url.scheme == "https" or os.getenv("TENALI_ENV") == "production"
    response.set_cookie(cookie, token, httponly=True, secure=secure, samesite="lax", max_age=43200, path="/")
    response.set_cookie(csrf, secrets.token_urlsafe(32), secure=secure, samesite="lax", max_age=43200, path="/")
    response.headers["Cache-Control"] = "no-store"


def ensure_csrf(response: Response, request: Request, cookie: str):
    if not request.cookies.get(cookie):
        response.set_cookie(cookie, secrets.token_urlsafe(32), secure=request.url.scheme == "https" or os.getenv("TENALI_ENV") == "production",
                            samesite="lax", max_age=43200, path="/")


def shopper_identity(db, request: Request, company_id: str):
    check_write(request, SHOP_CSRF)
    row = db.execute(text("""select account.id,account.email,account.display_name
        from shopper_sessions session join shopper_accounts account
        on account.id=session.shopper_id and account.company_id=session.company_id
        where session.token_hash=:token and session.company_id=:company
        and session.expires_at>now() and account.is_active=true"""),
        {"token": token_digest(request.cookies.get(SHOP_COOKIE, "")), "company": company_id}).mappings().first()
    if not row:
        raise HTTPException(401, "Sign in to your shopper account for this store")
    return dict(row)
