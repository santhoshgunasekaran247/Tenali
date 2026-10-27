from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.company import CompanySetupOut, CompanyUpdate, SiteTheme
from app.services.company_service import CompanyService

router = APIRouter()


@router.get("", response_model=CompanySetupOut)
def get_company(company_id: UUID | None = None, db: Session = Depends(get_db)):
    return CompanyService(db).get(str(company_id) if company_id else None)


@router.put("", response_model=CompanySetupOut)
def update_company(payload: CompanyUpdate, company_id: UUID | None = None, db: Session = Depends(get_db)):
    return CompanyService(db).update(payload, str(company_id) if company_id else None)


@router.put("/site-theme", response_model=CompanySetupOut)
def update_site_theme(payload: SiteTheme, company_id: UUID | None = None, db: Session = Depends(get_db)):
    return CompanyService(db).update_site_theme(payload, str(company_id) if company_id else None)