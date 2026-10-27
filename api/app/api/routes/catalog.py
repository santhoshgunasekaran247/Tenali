from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.catalog import CatalogHomeResponse, CatalogListResponse, CatalogProductResponse
from app.services.catalog_service import CatalogService

router = APIRouter()


@router.get("/home", response_model=CatalogHomeResponse)
def catalog_home(company_id: str | None = None, db: Session = Depends(get_db)):
    service = CatalogService(db)
    return service.home(company_id=company_id)


@router.get("/list", response_model=CatalogListResponse)
def catalog_list(
    company_id: str | None = None,
    brand: str | None = None,
    category: str | None = None,
    db: Session = Depends(get_db),
):
    service = CatalogService(db)
    return service.list(company_id=company_id, brand=brand, category=category)


@router.get("/products/{product_id}", response_model=CatalogProductResponse)
def catalog_product_detail(
    product_id: str,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = CatalogService(db)
    return service.product_detail(product_id=product_id, company_id=company_id)
