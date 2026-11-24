from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.company import CompanySetupOut, CompanyUpdate, SiteTheme
from app.schemas.catalog import CatalogStorefrontPreviewResponse
from app.schemas.storefront import ProductTagsUpdate, StorefrontSectionsUpdate
from app.services.company_service import CompanyService
from app.services.catalog_service import CatalogService
from app.services.product_tags import ProductTagsService
from app.services.storefront_sections import StorefrontSectionsService

router = APIRouter()


@router.get("/features")
def features(company_id: UUID | None = None, db: Session = Depends(get_db)):
    return CompanyService(db).get(str(company_id) if company_id else None)["features"]


@router.get("", response_model=CompanySetupOut)
def get_company(company_id: UUID | None = None, db: Session = Depends(get_db)):
    return CompanyService(db).get(str(company_id) if company_id else None)


@router.put("", response_model=CompanySetupOut)
def update_company(payload: CompanyUpdate, company_id: UUID | None = None, db: Session = Depends(get_db)):
    return CompanyService(db).update(payload, str(company_id) if company_id else None)


@router.put("/site-theme", response_model=CompanySetupOut)
def update_site_theme(payload: SiteTheme, company_id: UUID | None = None, db: Session = Depends(get_db)):
    return CompanyService(db).update_site_theme(payload, str(company_id) if company_id else None)


@router.get("/storefront-preview", response_model=CatalogStorefrontPreviewResponse)
def storefront_preview(company_id: UUID | None = None, db: Session = Depends(get_db)):
    company = CompanyService(db).get(str(company_id) if company_id else None)
    return CatalogService(db).home(str(company["id"]))


@router.get("/storefront-sections")
def storefront_sections(company_id: UUID | None = None, db: Session = Depends(get_db)):
    return {"sections": StorefrontSectionsService(db).list(str(company_id) if company_id else None)}


@router.put("/storefront-sections")
def update_storefront_sections(
    payload: StorefrontSectionsUpdate,
    company_id: UUID | None = None,
    db: Session = Depends(get_db),
):
    return {"sections": StorefrontSectionsService(db).replace(payload, str(company_id) if company_id else None)}


@router.get("/product-tags")
def product_tags(company_id: UUID | None = None, db: Session = Depends(get_db)):
    return {"tags": ProductTagsService(db).list(str(company_id) if company_id else None)}


@router.put("/product-tags")
def update_product_tags(
    payload: ProductTagsUpdate,
    company_id: UUID | None = None,
    db: Session = Depends(get_db),
):
    return {"tags": ProductTagsService(db).replace(payload, str(company_id) if company_id else None)}