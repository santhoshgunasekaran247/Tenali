from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_title,
        version=settings.app_version,
        description=settings.app_description,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    return app


app = create_app()
