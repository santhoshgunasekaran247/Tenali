from fastapi import APIRouter

from app.api.routes.accounts import router as accounts_router
from app.api.routes.billing import router as billing_router
from app.api.routes.catalog import router as catalog_router
from app.api.routes.collections import router as collections_router
from app.api.routes.company import router as company_router
from app.api.routes.reports import router as reports_router
from app.api.routes.inventory import router as inventory_router
from app.api.routes.documents import router as documents_router
from app.api.routes.masters import router as masters_router
from app.api.routes.health import router as health_router
from app.api.routes.parties import router as parties_router
from app.api.routes.purchases import router as purchases_router
from app.api.routes.settlements import router as settlements_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(catalog_router, prefix="/catalog", tags=["catalog"])
api_router.include_router(company_router, prefix="/company", tags=["company"])
api_router.include_router(reports_router,prefix="/reports",tags=["reports"])
api_router.include_router(inventory_router, prefix="/inventory", tags=["inventory"])
api_router.include_router(documents_router, prefix="/documents", tags=["documents"])
api_router.include_router(masters_router, prefix="/masters", tags=["masters"])
api_router.include_router(parties_router, prefix="/parties", tags=["parties"])
api_router.include_router(accounts_router, prefix="/accounts", tags=["accounts"])
api_router.include_router(billing_router, prefix="/billing", tags=["billing"])
api_router.include_router(purchases_router, prefix="/purchases", tags=["purchases"])
api_router.include_router(settlements_router, prefix="/settlements", tags=["settlements"])
api_router.include_router(collections_router, prefix="/collections", tags=["collections"])
