from pathlib import Path
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.services.tenant_context import TenantBoundary
from app.services.tenant_context import company_by_slug
from sqlalchemy.exc import IntegrityError
from fastapi.responses import JSONResponse
from fastapi import Query,HTTPException
from sqlalchemy import text
from app.core.database import SessionLocal


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_title,
        version=settings.app_version,
        description=settings.app_description,
        docs_url=None if os.getenv("TENALI_ENV")=="production" else "/docs",
        redoc_url=None if os.getenv("TENALI_ENV")=="production" else "/redoc",
        openapi_url=None if os.getenv("TENALI_ENV")=="production" else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TenantBoundary)

    @app.get('/domain-authorization',include_in_schema=False)
    def authorize_tls_domain(domain:str=Query(max_length=253)):
        domain=domain.lower().strip().rstrip('.')
        base=os.getenv('TENALI_BASE_DOMAIN','').lower().strip('.')
        with SessionLocal() as db:
            allowed=bool(base and domain in {base,'app.'+base})
            if not allowed and base and domain.endswith('.'+base):
                slug=domain[:-(len(base)+1)]
                allowed=bool(company_by_slug(db,slug))
            if not allowed:
                allowed=bool(db.execute(text('select domain.id from tenant_domains domain join companies company on company.id=domain.company_id and company.is_active=true where domain.hostname=:host and domain.verified_at is not null'),{'host':domain}).scalar_one_or_none())
        if not allowed:raise HTTPException(403,'Domain is not authorized')
        return {'authorized':True}

    @app.exception_handler(IntegrityError)
    async def invalid_relationship(request,error):
        return JSONResponse({"detail":"The selected data is invalid, already exists, or does not belong to this workspace."},status_code=422)

    # Serve routes at both root and /api so older clients keep working.
    app.include_router(api_router)
    app.include_router(api_router, prefix="/api")

    prototype_assets_dir = (
        Path(__file__).resolve().parents[2] / "tenali-v31-exact-prototype" / "assets"
    )
    if prototype_assets_dir.exists():
        app.mount(
            "/catalog-assets",
            StaticFiles(directory=prototype_assets_dir),
            name="catalog-assets",
        )
        app.mount('/api/catalog-assets',StaticFiles(directory=prototype_assets_dir),name='api-catalog-assets')

    return app


app = create_app()
