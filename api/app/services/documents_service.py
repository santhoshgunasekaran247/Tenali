import base64
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.documents import AttachmentCreate, MAX_ATTACHMENTS, MAX_TOTAL_BYTES


class DocumentsService:
    def __init__(self, db: Session):
        self.db = db

    def resolve_company(self, company_id: str | None) -> str:
        result = self.db.execute(text("""
            select id from companies where is_active = true
            and (cast(:id as uuid) is null or id = cast(:id as uuid))
            order by created_at asc, id asc limit 1
        """), {"id": company_id}).scalar_one_or_none()
        if not result:
            raise HTTPException(status_code=404, detail="Company not found")
        return str(result)

    def _assert_entity(self, entity_type: str, entity_id: str, company_id: str, lock: bool = False) -> None:
        queries = {
            "purchase": "select id from purchases where id = :id and company_id = :company_id",
            "business_payment": """select id from account_transactions where id = :id and company_id = :company_id
                and category in ('business_purchase','business_billing','business_expense')
                and reversal_of_transaction_id is null""",
        }
        if entity_type not in queries:
            raise HTTPException(status_code=422, detail="Unsupported attachment record type")
        query = queries[entity_type] + (" for update" if lock else "")
        if not self.db.execute(text(query), {"id": entity_id, "company_id": company_id}).scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Attachment record not found")

    def list_attachments(self, entity_type: str, entity_id: str, company_id: str) -> dict:
        self._assert_entity(entity_type, entity_id, company_id)
        rows = self.db.execute(text("""
            select d.id, d.file_name, d.mime_type, d.file_size, d.created_at
            from documents d join document_links link on link.document_id = d.id
            where d.company_id = :company_id and link.entity_type = :entity_type
              and link.entity_id = :entity_id and d.file_content is not null
            order by d.created_at asc, d.id asc
        """), {"company_id": company_id, "entity_type": entity_type, "entity_id": entity_id}).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def add_attachments(self, entity_type: str, entity_id: str, company_id: str,
                        attachments: list[AttachmentCreate]) -> list[dict]:
        if not attachments:
            return []
        self._assert_entity(entity_type, entity_id, company_id, lock=True)
        existing = self.list_attachments(entity_type, entity_id, company_id)["items"]
        if len(existing) + len(attachments) > MAX_ATTACHMENTS:
            raise HTTPException(status_code=422, detail="A maximum of 5 attachments is allowed per record")
        decoded = [base64.b64decode(item.data_base64, validate=True) for item in attachments]
        if sum(item["file_size"] for item in existing) + sum(map(len, decoded)) > MAX_TOTAL_BYTES:
            raise HTTPException(status_code=422, detail="Total attachments cannot exceed 20 MB per record")
        result = []
        for item, content in zip(attachments, decoded):
            document_id = str(uuid4())
            row = self.db.execute(text("""
                insert into documents(id, company_id, document_type, file_name, storage_path, mime_type, file_size, file_content)
                values(:id, :company_id, :document_type, :file_name, :storage_path, :mime_type, :file_size, :file_content)
                returning id, file_name, mime_type, file_size, created_at
            """), {"id": document_id, "company_id": company_id, "document_type": f"{entity_type}_receipt",
                    "file_name": item.file_name, "storage_path": f"database://documents/{document_id}",
                    "mime_type": item.mime_type, "file_size": len(content), "file_content": content}).mappings().one()
            self.db.execute(text("""
                insert into document_links(document_id, entity_type, entity_id)
                values(:document_id, :entity_type, :entity_id)
            """), {"document_id": document_id, "entity_type": entity_type, "entity_id": entity_id})
            result.append(dict(row))
        return result

    def download(self, document_id: str, company_id: str) -> dict:
        row = self.db.execute(text("""
            select d.file_name, d.mime_type, d.file_content, link.entity_type, link.entity_id
            from documents d join document_links link on link.document_id = d.id
            where d.id = :id and d.company_id = :company_id and d.file_content is not null
            order by link.created_at asc limit 1
        """), {"id": document_id, "company_id": company_id}).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Attachment not found")
        self._assert_entity(row["entity_type"], str(row["entity_id"]), company_id)
        return dict(row)