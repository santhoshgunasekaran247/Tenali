import os
from urllib.parse import parse_qsl, urlencode, urlparse

from fastapi import HTTPException
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.database import SessionLocal
from app.services.tenant_auth import TenantAuth

SESSION_COOKIE = "tenali_session"
CSRF_COOKIE = "tenali_csrf"
PUBLIC_PATHS = {"/catalog/home", "/catalog/list", "/catalog/company"}


def request_hostname(request):
    host = request.url.hostname or ""
    return host.lower().rstrip(".")


def platform_host(request):
    host=request_hostname(request)
    if host in {"localhost","127.0.0.1"} and os.getenv("TENALI_ENV","development")!="production":
        return True
    base=os.getenv("TENALI_BASE_DOMAIN","").lower().strip(".")
    return bool(base and host in {base,"app."+base})


def company_by_slug(db, slug):
    return db.execute(text("""select company.id,company.tenant_slug from companies company
        where company.is_active=true and (company.tenant_slug=:slug or exists(
            select 1 from tenant_slug_aliases alias where alias.company_id=company.id and alias.tenant_slug=:slug))"""), {"slug": slug}).mappings().first()


def host_company(db, request):
    host = request_hostname(request)
    base = os.getenv("TENALI_BASE_DOMAIN", "").lower().strip(".")
    if base and host.endswith("."+base):
        slug = host[:-(len(base)+1)]
        if "." not in slug:
            return company_by_slug(db, slug)
    return db.execute(text("""select company.id,company.tenant_slug from tenant_domains domain
        join companies company on company.id=domain.company_id and company.is_active=true
        where domain.hostname=:host and domain.verified_at is not null"""), {"host": host}).mappings().first()


class TenantBoundary(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            path = path[4:]
        if request.method == "OPTIONS" or path in {"/health", "/health/", "/docs", "/redoc", "/openapi.json", "/domain-authorization"} or path.startswith("/catalog-assets/"):
            return await call_next(request)
        try:
            if path.startswith('/auth/'):
                with SessionLocal() as db:
                    if not host_company(db,request) and not platform_host(request):
                        raise HTTPException(404,'This domain is not configured for a workspace')
                return await call_next(request)
            with SessionLocal() as db:
                is_public = request.method in {"GET","HEAD"} and (path in PUBLIC_PATHS or path.startswith("/catalog/products/"))
                from_host = host_company(db, request)
                if not from_host and not platform_host(request):
                    raise HTTPException(404,"This domain is not configured for a workspace")
                if is_public:
                    slug = request.headers.get("X-Tenant-Slug")
                    local = request_hostname(request) in {"localhost", "127.0.0.1"} and os.getenv("TENALI_ENV", "development") != "production"
                    base = os.getenv("TENALI_BASE_DOMAIN", "").lower().strip(".")
                    platform = request_hostname(request) == base or request_hostname(request) == "app."+base if base else local
                    company = from_host
                    if slug and (local or platform):
                        company = company_by_slug(db, slug)
                    if not company:
                        raise HTTPException(404, "Choose a workspace storefront or use its verified domain")
                    request.state.tenant = {"company_id": str(company["id"]), "role": "public", "user_id": None}
                else:
                    identity = TenantAuth(db).identity(request.cookies.get(SESSION_COOKIE))
                    if from_host and str(from_host["id"]) != str(identity["company_id"]):
                        raise HTTPException(403, "This session belongs to another workspace")
                    slug = request.headers.get("X-Tenant-Slug")
                    if slug:
                        selected = company_by_slug(db, slug)
                        if not selected or str(selected["id"]) != str(identity["company_id"]):
                            raise HTTPException(403, "Workspace selection does not match your session")
                    if identity["role"] == "viewer" and request.method not in {"GET", "HEAD"}:
                        raise HTTPException(403, "This account has read-only access")
                    if path.startswith("/company") and request.method not in {"GET", "HEAD"} and identity["role"] not in {"owner", "admin"}:
                        raise HTTPException(403, "Administrator access is required")
                    if request.method not in {"GET", "HEAD"}:
                        origin = request.headers.get("Origin")
                        if origin and urlparse(origin).netloc.lower() != request.url.netloc.lower():
                            raise HTTPException(403, "Cross-origin write rejected")
                        csrf = request.cookies.get(CSRF_COOKIE)
                        if not csrf or request.headers.get("X-CSRF-Token") != csrf:
                            raise HTTPException(403, "Refresh the page before submitting this request")
                    request.state.tenant = dict(identity)
                expected = str(request.state.tenant["company_id"])
                pairs = parse_qsl(request.scope.get("query_string", b"").decode(), keep_blank_values=True)
                if any(key == "company_id" and value != expected for key, value in pairs):
                    raise HTTPException(403, "Company override rejected")
                pairs = [(key, value) for key, value in pairs if key != "company_id"]
                pairs.append(("company_id", expected))
                request.scope["query_string"] = urlencode(pairs).encode()
            response = await call_next(request)
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Vary"] = "Host, Cookie, X-Tenant-Slug"
            return response
        except HTTPException as error:
            return JSONResponse({"detail": error.detail}, status_code=error.status_code, headers={"Cache-Control":"no-store"})