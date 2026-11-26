import os
from http.cookies import SimpleCookie

from sqlalchemy import text
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.database import SessionLocal

CSRF_HEADERS = {
    "tenali_csrf": "X-Tenali-Staff-CSRF",
    "tenali_shopper_csrf": "X-Tenali-Shopper-CSRF",
}


def custom_domains_enabled():
    return os.getenv("TENALI_CUSTOM_DOMAINS_ENABLED", "").lower() == "true"


def api_frontend(hostname):
    with SessionLocal() as db:
        return db.execute(text("""
            select domain.hostname from tenant_domain_bindings binding
            join tenant_domains domain on domain.id=binding.domain_id
            join companies company on company.id=domain.company_id
            where binding.hostname=:host and binding.kind='api'
              and domain.verified_at is not null and company.is_active=true
              and domain.hosting_status in ('provisioning','tls_pending','active')
        """), {"host": hostname}).scalar_one_or_none()


class CustomDomainRouting:
    """Bind a verified tenant API host to its exact frontend origin."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not custom_domains_enabled():
            return await self.app(scope, receive, send)
        request = Request(scope)
        host = (request.url.hostname or "").lower()
        # Render's original API hostname must retain the existing platform rewrite.
        if not host.startswith("api.") or host.endswith(".onrender.com"):
            return await self.app(scope, receive, send)
        frontend = await run_in_threadpool(api_frontend, host)
        if not frontend:
            return await self.app(scope, receive, send)
        expected_origin = "https://" + frontend
        origin = request.headers.get("origin")
        if request.url.scheme != "https" or (origin and origin != expected_origin):
            return await JSONResponse(
                {"detail": "This API accepts only its verified storefront origin"},
                status_code=403, headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
        mapped = dict(scope)
        mapped["headers"] = [
            (key, value) for key, value in scope["headers"] if key.lower() != b"host"
        ] + [(b"host", frontend.encode("ascii"))]
        mapped["server"] = (frontend, 443)
        mapped["state"] = {**scope.get("state", {}), "tenant_api_host": host}

        async def token_headers(message):
            if message["type"] == "http.response.start":
                cookies = dict(request.cookies)
                for key, value in message.get("headers", []):
                    if key.lower() == b"set-cookie":
                        parsed = SimpleCookie()
                        parsed.load(value.decode("latin-1"))
                        for name in CSRF_HEADERS:
                            if name in parsed:
                                cookies[name] = parsed[name].value
                headers = list(message.get("headers", []))
                for cookie, header in CSRF_HEADERS.items():
                    if cookies.get(cookie):
                        headers.append((header.lower().encode("ascii"), cookies[cookie].encode("ascii")))
                headers.append((b"cache-control", b"private, no-store"))
                message = {**message, "headers": headers}
            await send(message)

        cors = CORSMiddleware(
            self.app, allow_origins=[expected_origin], allow_credentials=True,
            allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-CSRF-Token", "X-Tenant-Slug", "Idempotency-Key"],
            expose_headers=list(CSRF_HEADERS.values()) + ["Content-Disposition", "X-Bulk-Success-Count", "X-Bulk-Failure-Count"],
            max_age=600,
        )
        await cors(mapped, receive, token_headers)
