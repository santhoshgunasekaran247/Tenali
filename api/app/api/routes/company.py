from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.company import CompanySetupOut, CompanyUpdate, SiteTheme
from app.services.company_service import CompanyService
from app.services.object_storage import ObjectStorage, PRIVATE_BUCKET

router = APIRouter()


@router.get("/assets/{file_id}")
def private_image(file_id: UUID, request: Request, db: Session = Depends(get_db)):
    identity = request.state.tenant
    if identity["role"] not in {"owner", "admin"} and identity.get("modules") is not None and not set(identity["modules"]) & {"billing", "reports"}:
        raise HTTPException(403, "Billing or reports access is required for signature images")
    file = db.execute(text("select * from stored_files where id=:id and company_id=:company and bucket=:bucket and file_kind='signature'"),
        {"id": file_id, "company": identity["company_id"], "bucket": PRIVATE_BUCKET}).mappings().first()
    if not file or not file["mime_type"].startswith("image/"):
        raise HTTPException(404, "Image not found")
    return Response(ObjectStorage().read(file["bucket"], file["object_path"]), media_type=file["mime_type"],
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("", response_model=CompanySetupOut)
def get_company(company_id: UUID | None = None, db: Session = Depends(get_db)):
    return CompanyService(db).get(str(company_id) if company_id else None)


@router.put("", response_model=CompanySetupOut)
def update_company(payload: CompanyUpdate, company_id: UUID | None = None, db: Session = Depends(get_db)):
    return CompanyService(db).update(payload, str(company_id) if company_id else None)


@router.put("/site-theme", response_model=CompanySetupOut)
def update_site_theme(payload: SiteTheme, company_id: UUID | None = None, db: Session = Depends(get_db)):
    return CompanyService(db).update_site_theme(payload, str(company_id) if company_id else None)