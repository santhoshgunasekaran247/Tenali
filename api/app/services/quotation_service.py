"""Quotations capture a price offer without creating an invoice or ledger effects."""
import json
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from app.schemas.billing import InvoiceCreate, QuotationCreate
from app.services.access import allowed_stores
from app.services.billing_service import BillingService
from app.services.commerce_stock import resolve_product_lines
from app.services.financial_amounts import document_total
from app.services.invoice_document import build_invoice_document
from app.services.masters_service import MastersService
from app.services.posting_service import finish_posting, replay_posting, request_hash
from app.services.stores_service import get_store


class QuotationService:
    def __init__(self, db):
        self.db = db

    def list(self, company_id, store_id=None, *, quotation_id=None, page_size: int | None = None, cursor: str | None = None,
             from_date: date | None = None, to_date: date | None = None):
        company = BillingService(self.db)._resolve_company_id(company_id)
        permitted = allowed_stores(self.db.info.get("tenant_context"))
        if store_id:
            get_store(self.db, company, store_id, require_active=False)
        query = """select q.*, s.code as store_code
            from quotations q join stores s on s.id=q.store_id and s.company_id=q.company_id
            where q.company_id=:company and (cast(:store as uuid) is null or q.store_id=cast(:store as uuid))
              and (cast(:quotation as uuid) is null or q.id=cast(:quotation as uuid))
              and (cast(:permitted as uuid[]) is null or q.store_id=any(cast(:permitted as uuid[])))
              and (cast(:from_date as date) is null or q.quotation_date>=cast(:from_date as date))
              and (cast(:to_date as date) is null or q.quotation_date<=cast(:to_date as date))"""
        params = {"company": company, "store": store_id, "quotation": quotation_id, "permitted": permitted,
                  "from_date": from_date, "to_date": to_date}
        if page_size is not None:
            from app.services.pagination import cursor_page, decode_cursor
            boundary = decode_cursor(cursor, ("created_at", "id"))
            if boundary:
                query += " and (q.created_at,q.id) < (cast(:created_at as timestamptz),cast(:id as uuid))"
                params.update(boundary)
            params["limit"] = page_size + 1
            query += " order by q.created_at desc,q.id desc limit :limit"
        else:
            query += " order by q.created_at desc,q.id desc"
        rows = self.db.execute(text(query), params).mappings().all()
        if page_size is not None:
            return cursor_page(rows, page_size, ("created_at", "id"))
        return {"items": [dict(row) for row in rows]}

    def prepare(self, company_id, payload: QuotationCreate):
        store = get_store(self.db, company_id, str(payload.store_id) if payload.store_id else None)
        customer = self.db.execute(text("""select id, legal_name, gst_number, address from parties
            where id=:party and company_id=:company and is_active=true
              and party_type in ('customer','customer_vendor')"""),
            {"party": str(payload.customer_party_id), "company": company_id}).mappings().first()
        if not customer:
            raise HTTPException(422, "Select an active customer from this workspace.")
        values = InvoiceCreate(customer_party_id=payload.customer_party_id, lines=payload.lines,
            billing_address=payload.billing_address, shipping_name=payload.shipping_name,
            shipping_address=payload.shipping_address, place_of_supply=payload.place_of_supply)
        if any(line.new_product for line in values.lines):
            raise HTTPException(422, "A quotation cannot create products. Select an existing product or describe the item.")
        resolve_product_lines(self.db, company_id, values.lines, persist_hsn=False)
        MastersService(self.db).apply_hsn_rates(values.lines, company_id)
        company = self.db.execute(text("""select company_name, address, gst_number, gst_registered,
            udyam_number, logo_url, phone, email, website, invoice_settings, prices_include_gst
            from companies where id=:company"""), {"company": company_id}).mappings().one()
        document = build_invoice_document(values, dict(company), dict(customer), store, bool(company["prices_include_gst"]))
        document_total(Decimal(document["subtotal"]), Decimal(document["gst_total"]), Decimal(document["total"]))
        document["document_title"] = "QUOTATION"
        return store, document

    def create(self, company_id, payload: QuotationCreate, *, commit: bool = True):
        company_id = BillingService(self.db)._resolve_company_id(company_id)
        store = get_store(self.db, company_id, str(payload.store_id) if payload.store_id else None)
        original_hash = request_hash(payload)
        cached = replay_posting(self.db, company_id, "quotation", payload)
        if cached is not None:
            get_store(self.db, company_id, cached["store_id"], require_active=False)
            return cached
        store, document = self.prepare(company_id, payload)
        row = self.db.execute(text("""insert into quotations(company_id,store_id,customer_party_id,
            quotation_number,quotation_date,reference,notes,document_data)
            values(:company,:store,:customer,:number,:date,:reference,:notes,cast(:document as jsonb)) returning *"""),
            {"company": company_id, "store": str(store["id"]), "customer": str(payload.customer_party_id),
             "number": f"QUO-{uuid4().hex.upper()}", "date": payload.quotation_date or date.today(),
             "reference": payload.reference, "notes": payload.notes,
             "document": json.dumps(jsonable_encoder(document))}).mappings().one()
        result = {**dict(row), "store_code": store["code"]}
        finish_posting(self.db, company_id, "quotation", payload, result, original_hash)
        if commit:
            self.db.commit()
        return result
