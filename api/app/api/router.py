from fastapi import APIRouter

from app.api.routes.catalog import router as catalog_router
from app.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(catalog_router, prefix="/catalog", tags=["catalog"])
