from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.schemas.stores import StoreInput
from app.services.access import allowed_stores, check_store

STORE_COLUMNS = """id, company_id, code, name, kind, holds_stock, fulfilment_store_id, allows_pickup, address,
    state_code, pincode, latitude, longitude, gst_number, whatsapp_number, settlement_account_id, is_default, is_active"""


def resolve_company_id(db: Session, company_id: str | None) -> str:
    row = db.execute(
        text("""select id from companies where is_active = true
            and (cast(:id as uuid) is null or id = cast(:id as uuid)) order by created_at, id limit 1"""),
        {"id": company_id},
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Company not found")
    return str(row)


def get_store(db: Session, company_id: str, store_id: str | None, *, lock: bool = False,
              require_active: bool = True) -> dict:
    """Return the requested store, or the company's default store when store_id is omitted."""
    row = db.execute(
        text(f"""select {STORE_COLUMNS} from stores
            where company_id = :company
              and (cast(:store as uuid) is null and is_default or id = cast(:store as uuid))
            {'for update' if lock else ''}"""),
        {"company": company_id, "store": store_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Store not found" if store_id else "The company has no default store")
    if require_active and not row["is_active"]:
        raise HTTPException(422, f"Store {row['code']} is inactive")
    check_store(db.info.get("tenant_context"), row)
    return dict(row)


def stock_store(db: Session, company_id: str, store_id: str | None, *, lock: bool = False) -> dict:
    store = get_store(db, company_id, store_id, lock=lock)
    if not store["holds_stock"]:
        raise HTTPException(422, f"Store {store['code']} does not hold stock; use its fulfilment store")
    return store


class StoresService:
    def __init__(self, db: Session, company_id: str | None = None):
        self.db = db
        self.company_id = resolve_company_id(db, company_id)

    def list_stores(self, include_inactive: bool = True) -> dict:
        permitted = allowed_stores(self.db.info.get("tenant_context"))
        rows = self.db.execute(
            text(f"""select {STORE_COLUMNS} from stores where company_id = :company
                and (:all or is_active) and (cast(:permitted as uuid[]) is null or id = any(cast(:permitted as uuid[])))
                order by is_default desc, kind, code"""),
            {"company": self.company_id, "all": include_inactive, "permitted": permitted},
        ).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def _validate(self, payload: StoreInput, store_id: str | None) -> None:
        if payload.fulfilment_store_id:
            target = get_store(self.db, self.company_id, str(payload.fulfilment_store_id))
            if not target["holds_stock"]:
                raise HTTPException(422, "The fulfilment store must be a warehouse or shop that holds stock")
            if store_id and str(target["id"]) == store_id:
                raise HTTPException(422, "A store cannot fulfil itself")
        if payload.settlement_account_id:
            account = self.db.execute(
                text("select id from accounts where id = :id and company_id = :company and is_active"),
                {"id": str(payload.settlement_account_id), "company": self.company_id},
            ).scalar_one_or_none()
            if not account:
                raise HTTPException(422, "Settlement account must be an active account of this company")

    def create_store(self, payload: StoreInput) -> dict:
        self._validate(payload, None)
        values = payload.model_dump()
        values.update(company=self.company_id, holds_stock=payload.kind != "online")
        try:
            row = self.db.execute(
                text(f"""insert into stores (company_id, code, name, kind, holds_stock, fulfilment_store_id, allows_pickup,
                        address, state_code, pincode, latitude, longitude, gst_number, whatsapp_number,
                        settlement_account_id, is_active)
                    values (:company, :code, :name, :kind, :holds_stock, :fulfilment_store_id, :allows_pickup,
                        :address, :state_code, :pincode, :latitude, :longitude, :gst_number, :whatsapp_number,
                        :settlement_account_id, :is_active)
                    returning {STORE_COLUMNS}"""),
                values,
            ).mappings().one()
        except IntegrityError as error:
            self.db.rollback()
            if "stores_company_id_code_key" in str(error):
                raise HTTPException(409, f"Store code {payload.code} already exists") from error
            raise HTTPException(422, "Store could not be saved; check the code, GSTIN and contact details") from error
        self.db.commit()
        return dict(row)

    def update_store(self, store_id: str, payload: StoreInput) -> dict:
        current = get_store(self.db, self.company_id, store_id, lock=True, require_active=False)
        self._validate(payload, store_id)
        if payload.kind != current["kind"] and self._has_history(store_id):
            raise HTTPException(422, "Store kind cannot change once it has stock or documents")
        if payload.code != current["code"] and self._has_documents(store_id):
            raise HTTPException(422, "Store code cannot change once documents are numbered with it")
        if not payload.is_active:
            if current["is_default"]:
                raise HTTPException(422, "Make another store the default before deactivating this one")
            if self._stock_quantity(store_id) != 0:
                raise HTTPException(422, "Transfer the remaining stock out before deactivating this store")
            dependants = self.db.execute(
                text("select code from stores where company_id = :company and fulfilment_store_id = :id and is_active"),
                {"company": self.company_id, "id": store_id},
            ).scalars().all()
            if dependants:
                raise HTTPException(422, f"Online store(s) {', '.join(dependants)} still fulfil from this store")
        values = payload.model_dump()
        values.update(id=store_id, company=self.company_id, holds_stock=payload.kind != "online")
        try:
            row = self.db.execute(
                text(f"""update stores set code = :code, name = :name, kind = :kind, holds_stock = :holds_stock,
                        fulfilment_store_id = :fulfilment_store_id, allows_pickup = :allows_pickup, address = :address,
                        state_code = :state_code, pincode = :pincode, latitude = :latitude, longitude = :longitude,
                        gst_number = :gst_number, whatsapp_number = :whatsapp_number,
                        settlement_account_id = :settlement_account_id, is_active = :is_active, updated_at = now()
                    where id = :id and company_id = :company returning {STORE_COLUMNS}"""),
                values,
            ).mappings().one()
        except IntegrityError as error:
            self.db.rollback()
            if "stores_company_id_code_key" in str(error):
                raise HTTPException(409, f"Store code {payload.code} already exists") from error
            raise HTTPException(422, "Store could not be saved; check the code, GSTIN and contact details") from error
        self.db.commit()
        return dict(row)

    def set_default(self, store_id: str) -> dict:
        store = get_store(self.db, self.company_id, store_id)
        if not store["holds_stock"]:
            raise HTTPException(422, "The default store must hold stock")
        self.db.execute(text("update stores set is_default = false where company_id = :company and is_default"),
                        {"company": self.company_id})
        self.db.execute(text("update stores set is_default = true, updated_at = now() where id = :id and company_id = :company"),
                        {"id": store_id, "company": self.company_id})
        self.db.commit()
        return get_store(self.db, self.company_id, store_id)

    def _stock_quantity(self, store_id: str):
        return self.db.execute(
            text("select coalesce(sum(quantity), 0) from stock_balances where company_id = :company and store_id = :id"),
            {"company": self.company_id, "id": store_id},
        ).scalar_one()

    def _has_documents(self, store_id: str) -> bool:
        return bool(self.db.execute(
            text("""select exists(select 1 from invoices where company_id = :company and store_id = :id)
                or exists(select 1 from purchases where company_id = :company and store_id = :id)"""),
            {"company": self.company_id, "id": store_id},
        ).scalar_one())

    def _has_history(self, store_id: str) -> bool:
        return self._has_documents(store_id) or bool(self.db.execute(
            text("select exists(select 1 from stock_movements where company_id = :company and store_id = :id)"),
            {"company": self.company_id, "id": store_id},
        ).scalar_one())
