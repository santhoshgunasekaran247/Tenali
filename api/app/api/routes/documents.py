from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.documents import AttachmentListResponse, AttachmentUpload, EntityType
from app.services.documents_service import DocumentsService

router = APIRouter()


@router.get("/{document_id}/download")
def download_document(document_id: UUID, company_id: UUID | None = None, db: Session = Depends(get_db)):
    service = DocumentsService(db)
    company = service.resolve_company(str(company_id) if company_id else None)
    document = service.download(str(document_id), company)
    return Response(content=bytes(document["file_content"]), media_type=document["mime_type"], headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document['file_name'], safe='')}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
    })


@router.get("/{entity_type}/{entity_id}", response_model=AttachmentListResponse)
def list_attachments(entity_type: EntityType, entity_id: UUID, company_id: UUID | None = None,
                     db: Session = Depends(get_db)):
    service = DocumentsService(db)
    company = service.resolve_company(str(company_id) if company_id else None)
    return service.list_attachments(entity_type, str(entity_id), company)


@router.post("/{entity_type}/{entity_id}", response_model=AttachmentListResponse, status_code=201)
def upload_attachments(entity_type: EntityType, entity_id: UUID, payload: AttachmentUpload,
                       company_id: UUID | None = None, db: Session = Depends(get_db)):
    service = DocumentsService(db)
    company = service.resolve_company(str(company_id) if company_id else None)
    items = service.add_attachments(entity_type, str(entity_id), company, payload.items)
    db.commit()
    return {"items": items}