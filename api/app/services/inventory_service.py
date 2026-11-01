import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.schemas.inventory import BulkVendorMapping, ExternalMovementSource, ProductInput, ReorderReminder, StockAdjustment, StockTransferCreate, VariantInput, VendorOfferInput
from app.services.access import allowed_stores
from app.services.inventory_pricing import resolve_catalog_price
from app.services.period_lock_service import assert_period_open
from app.services.posting_service import replay_posting, finish_posting, request_hash


class InventoryService:
    def __init__(self, db: Session, company_id: str | None = None):
        self.db = db
        company = db.execute(text("""select id from companies where is_active = true
            and (cast(:id as uuid) is null or id = cast(:id as uuid)) order by created_at, id limit 1"""), {"id": company_id}).scalar_one_or_none()
        if not company:
            raise HTTPException(404, "Company not found")
        self.company_id = str(company)

    def _product(self, product_id: str, lock: bool = False) -> dict:
        row = self.db.execute(text("select * from products where id=:id and company_id=:company" + (" for update" if lock else "")),
                              {"id": product_id, "company": self.company_id}).mappings().first()
        if not row:
            raise HTTPException(404, "Product not found")
        return dict(row)

    def _variant(self, product_id: str, variant_id: str) -> dict:
        row = self.db.execute(text("select * from product_variants where id=:id and product_id=:product"),
                              {"id": variant_id, "product": product_id}).mappings().first()
        if not row:
            raise HTTPException(404, "Variant does not belong to this product")
        return dict(row)

    def _vendor(self, vendor_id: str) -> None:
        if not self.db.execute(text("""select id from parties where id=:id and company_id=:company
            and is_active=true and party_type in ('vendor','customer_vendor')"""),
            {"id": vendor_id, "company": self.company_id}).scalar_one_or_none():
            raise HTTPException(422, "Select an active vendor from this company")

    def _write(self, table: str, values: dict, row_id: str | None = None) -> str:
        if table not in {"products", "product_variants", "vendor_contributions"}:
            raise ValueError("Invalid inventory table")
        params = {}
        expressions = {}
        for key, value in values.items():
            if not re.fullmatch(r"[a-z_]+", key):
                raise ValueError("Invalid inventory field")
            if key == "attributes":
                params[key] = json.dumps(value)
                expressions[key] = f"cast(:{key} as jsonb)"
            else:
                params[key] = str(value) if isinstance(value, UUID) else value
                expressions[key] = f":{key}"
        if row_id:
            params["row_id"] = row_id
            query = f"update {table} set " + ", ".join(f"{key}={expression}" for key, expression in expressions.items()) + ", updated_at=now() where id=:row_id returning id"
        else:
            query = f"insert into {table} (" + ", ".join(expressions) + ") values (" + ", ".join(expressions.values()) + ") returning id"
        return str(self.db.execute(text(query), params).scalar_one())

    def lookups(self) -> dict:
        result = {}
        for key, table in [("brands", "brands"), ("categories", "product_categories")]:
            result[key] = [dict(row) for row in self.db.execute(text(f"select id, name, code from {table} where company_id=:company and is_active=true order by name"), {"company": self.company_id}).mappings()]
        result["vendors"] = [dict(row) for row in self.db.execute(text("""select id, legal_name, contact_person, phone, email, address from parties
            where company_id=:company and is_active=true and party_type in ('vendor','customer_vendor') order by legal_name"""), {"company": self.company_id}).mappings()]
        return result

    def master_entries(self,kind:str)->dict:
        table={"brands":"brands","categories":"product_categories"}.get(kind)
        if not table:
            raise HTTPException(422,"Invalid master type")
        return {"items":[dict(row) for row in self.db.execute(text(f"select id,name,code,description,is_active from {table} where company_id=:company order by name"),{"company":self.company_id}).mappings()]}

    def update_lookup(self,kind:str,record_id:str,payload)->dict:
        table={"brands":"brands","categories":"product_categories"}.get(kind)
        if not table:
            raise HTTPException(422,"Invalid master type")
        try:
            row=self.db.execute(text(f"update {table} set name=:name,description=:description,is_active=:active"+(", display_title=:name" if kind=="categories" else "")+" where id=:id and company_id=:company returning id,name,code,description,is_active"),
                {"id":record_id,"company":self.company_id,"name":payload.name,"description":payload.description,"active":payload.is_active}).mappings().first()
            if not row:
                raise HTTPException(404,"Master entry not found")
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            raise HTTPException(409,"This name already exists") from error
        return dict(row)

    def create_lookup(self, kind: str, name: str, description: str = "", is_active: bool = True) -> dict:
        table = {"brands": "brands", "categories": "product_categories"}.get(kind)
        if not table:
            raise HTTPException(422, "Invalid lookup type")
        code = (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "item")[:60] + "-" + uuid4().hex[:8]
        try:
            row = self.db.execute(text(f"insert into {table}(company_id,name,code,description,is_active) values(:company,:name,:code,:description,:active) returning id,name,code,description,is_active"),
                                  {"company": self.company_id, "name": name, "code": code,"description":description,"active":is_active}).mappings().one()
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            raise HTTPException(409, "This name already exists") from error
        return dict(row)

    def _validate_item(self, values: dict, product_id: str | None, variant_id: str | None = None) -> None:
        for field, table in [("brand_id", "brands"), ("category_id", "product_categories")]:
            if values.get(field) and not self.db.execute(text(f"select id from {table} where id=:id and company_id=:company and is_active=true"),
                {"id": str(values[field]), "company": self.company_id}).scalar_one_or_none():
                raise HTTPException(422, f"Invalid {field}")
        if values.get("hsn_code") and not self.db.execute(text("select id from hsn_masters where company_id=:company and code=:code and is_active=true"),
            {"company": self.company_id, "code": values["hsn_code"]}).scalar_one_or_none():
            raise HTTPException(422, "Select an active HSN/SAC code")
        if values.get("preferred_vendor_id"):
            vendor_id = str(values["preferred_vendor_id"])
            self._vendor(vendor_id)
            if not product_id or not self.db.execute(text("""select id from vendor_contributions where product_id=:product
                and variant_id is not distinct from cast(:variant as uuid) and vendor_id=:vendor and is_active=true limit 1"""),
                {"product": product_id, "variant": variant_id, "vendor": vendor_id}).scalar_one_or_none():
                raise HTTPException(422, "Map an active vendor offer to this product/variant before selecting it as preferred")

    def _data(self) -> tuple:
        products = [dict(row) for row in self.db.execute(text("""select p.*, b.name as brand_name, c.name as category_name
            from products p left join brands b on b.id=p.brand_id left join product_categories c on c.id=p.category_id
            where p.company_id=:company order by p.home_order,p.name,p.id"""), {"company": self.company_id}).mappings()]
        variants = [dict(row) for row in self.db.execute(text("select v.* from product_variants v join products p on p.id=v.product_id where p.company_id=:company order by v.created_at,v.id"), {"company": self.company_id}).mappings()]
        offers = [dict(row) for row in self.db.execute(text("""select offer.*, vendor.legal_name as vendor_name, vendor.contact_person,
            vendor.phone, vendor.email, vendor.address, vendor.is_active as vendor_active
            from vendor_contributions offer join products p on p.id=offer.product_id
            join parties vendor on vendor.id=offer.vendor_id and vendor.company_id=p.company_id
            where p.company_id=:company order by offer.created_at,offer.id"""), {"company": self.company_id}).mappings()]
        stocks = {(str(row["product_id"]), str(row["variant_id"]) if row["variant_id"] else None): row["quantity"] for row in self.db.execute(text("""
            select product_id,variant_id,sum(quantity) as quantity from stock_balances where company_id=:company group by product_id,variant_id
        """), {"company": self.company_id}).mappings()}
        store_stocks = defaultdict(list)
        permitted = allowed_stores(self.db.info.get("tenant_context"))
        for row in self.db.execute(text("""select b.product_id,b.variant_id,b.store_id,s.code as store_code,s.name as store_name,sum(b.quantity) as quantity
            from stock_balances b join stores s on s.id=b.store_id where b.company_id=:company
            and (cast(:permitted as uuid[]) is null or b.store_id=any(cast(:permitted as uuid[])))
            group by b.product_id,b.variant_id,b.store_id,s.code,s.name,s.is_default order by s.is_default desc,s.code"""), {"company": self.company_id, "permitted": permitted}).mappings():
            store_stocks[(str(row["product_id"]), str(row["variant_id"]) if row["variant_id"] else None)].append(
                {"store_id": str(row["store_id"]), "store_code": row["store_code"], "store_name": row["store_name"], "quantity": row["quantity"]})
        self._store_stocks = store_stocks
        return products, variants, offers, stocks

    def _enrich(self, item: dict, offers: list[dict], quantity, inherited_vendor=None, parent: dict | None = None) -> dict:
        result = dict(item)
        preferred = item.get("preferred_vendor_id") or inherited_vendor
        available = [offer for offer in offers if offer["is_active"] and offer["vendor_active"]]
        offer = next((offer for offer in available if preferred and str(offer["vendor_id"]) == str(preferred)), None)
        mrp = offer["mrp"] if offer else (item.get("mrp") if not preferred else None)
        pricing = parent if item.get("pricing_mode") == "inherit" and parent else item
        try:
            result.update(resolve_catalog_price(mrp, pricing.get("selling_price"), pricing.get("discount_percent"), pricing.get("pricing_mode", "price")))
            result["pricing_error"] = None
        except HTTPException as error:
            result.update(effective_mrp=mrp, catalog_price=item.get("selling_price"), effective_discount=None, pricing_error=error.detail)
        result.update(effective_buying_price=offer["buying_price"] if offer else None,
                      preferred_vendor_name=offer["vendor_name"] if offer else None,
                      vendor_available_quantity=offer.get("available_quantity", 0) if offer else None,
                      vendor_availability=offer.get("availability", "UNKNOWN") if offer else "UNKNOWN",
                      vendor_lead_time_days=offer.get("lead_time_days", 0) if offer else None,
                      vendor_count=len(available), stock_qty=quantity or Decimal("0"), offers=offers,
                      store_stocks=getattr(self, "_store_stocks", {}).get((str(item.get("product_id") or item.get("id")), str(item["id"]) if item.get("product_id") else None), []))
        return result

    def list_products(self) -> dict:
        products, variants, offers, stocks = self._data()
        offer_map = defaultdict(list)
        for offer in offers:
            offer_map[(str(offer["product_id"]), str(offer["variant_id"]) if offer["variant_id"] else None)].append(offer)
        variant_map = defaultdict(list)
        for variant in variants:
            variant_map[str(variant["product_id"])].append(variant)
        totals = defaultdict(Decimal)
        for (product_id, _), quantity in stocks.items():
            totals[product_id] += quantity
        result = []
        for product in products:
            product_id = str(product["id"])
            item = self._enrich(product, offer_map[(product_id, None)], totals[product_id])
            item["base_stock_qty"] = stocks.get((product_id, None), Decimal("0"))
            item["variants"] = [self._enrich(variant, offer_map[(product_id, str(variant["id"]))], stocks.get((product_id, str(variant["id"]))), product.get("preferred_vendor_id"), product) for variant in variant_map[product_id]]
            result.append(item)
        return {"items": result}

    def detail(self, product_id: str) -> dict:
        self._product(product_id)
        return next(item for item in self.list_products()["items"] if str(item["id"]) == product_id)

    def _check_price(self, product_id: str, variant_id: str | None = None) -> None:
        product = self.detail(product_id)
        item = next((variant for variant in product["variants"] if str(variant["id"]) == variant_id), None) if variant_id else product
        if item and item["pricing_error"]:
            raise HTTPException(422, item["pricing_error"])
        if not variant_id:
            for variant in product["variants"]:
                if variant["is_active"] and variant["pricing_error"]:
                    raise HTTPException(422, f"{variant['variant_name']}: {variant['pricing_error']}")

    def save_product(self, payload: ProductInput, product_id: str | None = None) -> dict:
        if product_id:
            self._product(product_id, lock=True)
        values = payload.model_dump()
        self._validate_item(values, product_id)
        values["image_urls"] = "|".join(values["image_urls"])
        if not product_id:
            values.update(company_id=self.company_id, portal_product_id=f"PRD-{uuid4().hex[:12].upper()}")
        product_id = self._write("products", values, product_id)
        self._check_price(product_id)
        self.db.commit()
        return self.detail(product_id)

    def save_variant(self, product_id: str, payload: VariantInput, variant_id: str | None = None) -> dict:
        self._product(product_id, lock=True)
        if variant_id:
            self._variant(product_id, variant_id)
        values = payload.model_dump()
        self._validate_item(values, product_id, variant_id)
        duplicate = self.db.execute(text("""select id from product_variants where product_id=:product and is_active=true
            and id is distinct from cast(:id as uuid) and lower(coalesce(size,''))=lower(:size)
            and lower(coalesce(colour,''))=lower(:colour) and (coalesce(:size,'')<>'' or coalesce(:colour,'')<>'') limit 1"""),
            {"product": product_id, "id": variant_id, "size": values.get("size") or "", "colour": values.get("colour") or ""}).scalar_one_or_none()
        if duplicate:
            raise HTTPException(409, "An active variant with this size and colour already exists")
        if not variant_id:
            values["product_id"] = product_id
        variant_id = self._write("product_variants", values, variant_id)
        self._check_price(product_id, variant_id)
        self.db.commit()
        return self.detail(product_id)

    def save_offer(self, product_id: str, payload: VendorOfferInput, offer_id: str | None = None, commit: bool = True) -> dict:
        product = self._product(product_id, lock=True)
        self._vendor(str(payload.vendor_id))
        variant_id = str(payload.variant_id) if payload.variant_id else None
        variant = self._variant(product_id, variant_id) if variant_id else None
        if offer_id and not self.db.execute(text("select id from vendor_contributions where id=:id and product_id=:product"), {"id": offer_id, "product": product_id}).scalar_one_or_none():
            raise HTTPException(404, "Vendor offer not found")
        duplicate = self.db.execute(text("""select id from vendor_contributions where product_id=:product and vendor_id=:vendor
            and variant_id is not distinct from cast(:variant as uuid) and id is distinct from cast(:id as uuid) limit 1"""),
            {"product": product_id, "vendor": str(payload.vendor_id), "variant": variant_id, "id": offer_id}).scalar_one_or_none()
        if duplicate:
            raise HTTPException(409, "This vendor is already mapped to the selected product/variant; edit its offer")
        if offer_id:
            old = self.db.execute(text("select vendor_id,variant_id from vendor_contributions where id=:id"), {"id": offer_id}).mappings().one()
            if str(old["vendor_id"]) != str(payload.vendor_id) or old["variant_id"] != payload.variant_id:
                raise HTTPException(422, "An offer's product, variant and vendor cannot be changed; deactivate it and add a new mapping")
        values = payload.model_dump()
        if not offer_id:
            values["product_id"] = product_id
        self._write("vendor_contributions", values, offer_id)
        target = variant or product
        if not target.get("preferred_vendor_id") and payload.is_active and not (variant and product.get("preferred_vendor_id")):
            self._write("product_variants" if variant else "products", {"preferred_vendor_id": payload.vendor_id}, variant_id or product_id)
        self._check_price(product_id, variant_id)
        if commit:
            self.db.commit()
        return self.detail(product_id)

    def bulk_map(self, payload: BulkVendorMapping) -> dict:
        self._vendor(str(payload.vendor_id))
        product_ids = sorted({str(product_id) for product_id in payload.product_ids})
        for product_id in product_ids:
            self._product(product_id, lock=True)
        for product_id in product_ids:
            exists = self.db.execute(text("select id from vendor_contributions where product_id=:product and vendor_id=:vendor and variant_id is null limit 1"), {"product": product_id, "vendor": str(payload.vendor_id)}).scalar_one_or_none()
            if not exists:
                self.save_offer(product_id, VendorOfferInput(vendor_id=payload.vendor_id), commit=False)
        self.db.commit()
        return {"mapped_count": len(product_ids)}

    def adjust_stock(self, product_id: str, payload: StockAdjustment, commit: bool = True, reference_type: str = "manual_inventory",
                     reference_id: str | None = None, store_id: str | None = None, movement_type: str | None = None) -> dict:
        from app.services.stores_service import stock_store
        self._product(product_id, lock=True)
        store = stock_store(self.db, self.company_id, store_id or (str(payload.store_id) if payload.store_id else None))
        store_id = str(store["id"])
        cached = replay_posting(self.db, self.company_id, f"stock:{product_id}", payload) if commit else None
        if cached is not None:
            return cached
        if reference_type == "manual_inventory":
            assert_period_open(self.db, self.company_id, date.today(), "Adjusting inventory")
        variant_id = str(payload.variant_id) if payload.variant_id else None
        if variant_id:
            self._variant(product_id, variant_id)
        row = self.db.execute(text("""select id,quantity from stock_balances where company_id=:company and store_id=:store
            and product_id=:product and variant_id is not distinct from cast(:variant as uuid) for update"""),
            {"company": self.company_id, "store": store_id, "product": product_id, "variant": variant_id}).mappings().first()
        total = row["quantity"] if row else Decimal("0")
        new_total = total + (payload.quantity if payload.direction == "IN" else -payload.quantity)
        if new_total < 0:
            raise HTTPException(422, f"Stock at {store['code']} cannot become negative (available {total})")
        if payload.direction == "OUT":
            from app.services.shop_stock import reserved_stock
            reserved = reserved_stock(self.db, self.company_id, product_id, variant_id, store_id,
                                      reference_id if reference_type == "shop_order" else None)
            if new_total < reserved:
                raise HTTPException(422, f"Stock at {store['code']} is reserved by online orders ({reserved} reserved)")
        if row:
            self.db.execute(text("update stock_balances set quantity=:quantity where id=:id"), {"id": row["id"], "quantity": new_total})
        else:
            self.db.execute(text("insert into stock_balances(company_id,store_id,product_id,variant_id,quantity) values(:company,:store,:product,:variant,:quantity)"),
                            {"company": self.company_id, "store": store_id, "product": product_id, "variant": variant_id, "quantity": new_total})
        movement = movement_type or ("SALE" if reference_type in {"invoice", "shop_order"} else "PURCHASE" if reference_type == "purchase_receipt"
                                     else f"ADJUSTMENT_{payload.direction}")
        self.db.execute(text("""insert into stock_movements(company_id,store_id,product_id,variant_id,movement_type,quantity,notes,reference_type,reference_id)
            values(:company,:store,:product,:variant,:movement,:quantity,:notes,:reference_type,:reference_id)"""),
            {"company": self.company_id, "store": store_id, "product": product_id, "variant": variant_id, "movement": movement, "quantity": payload.quantity,
             "notes": payload.notes, "reference_type": reference_type, "reference_id": reference_id})
        result = self.detail(product_id)
        if commit:
            finish_posting(self.db, self.company_id, f"stock:{product_id}", payload, result)
            self.db.commit()
        return result

    def available_stock(self, store_id: str, product_id: str, variant_id: str | None, exclude_order: str | None = None) -> Decimal:
        from app.services.shop_stock import reserved_stock
        balance = self.db.execute(text("""select coalesce(sum(quantity),0) from stock_balances where company_id=:company
            and store_id=:store and product_id=:product and variant_id is not distinct from cast(:variant as uuid)"""),
            {"company": self.company_id, "store": store_id, "product": product_id, "variant": variant_id}).scalar_one()
        return Decimal(str(balance)) - reserved_stock(self.db, self.company_id, product_id, variant_id, store_id, exclude_order)

    def transfer_stock(self, payload: StockTransferCreate) -> dict:
        from app.services.stores_service import stock_store
        cached = replay_posting(self.db, self.company_id, "stock_transfer", payload)
        if cached is not None:
            return cached
        source = stock_store(self.db, self.company_id, str(payload.from_store_id))
        target = stock_store(self.db, self.company_id, str(payload.to_store_id))
        if source["id"] == target["id"]:
            raise HTTPException(422, "Choose two different stores")
        transfer_date = payload.transfer_date or date.today()
        assert_period_open(self.db, self.company_id, transfer_date, "Transferring stock")
        row = self.db.execute(text("""insert into stock_transfers(company_id,from_store_id,to_store_id,transfer_date,reference,notes,lines,created_by)
            values(:company,:from_store,:to_store,:date,:reference,:notes,cast(:lines as jsonb),cast(:actor as uuid)) returning id"""),
            {"company": self.company_id, "from_store": str(source["id"]), "to_store": str(target["id"]), "date": transfer_date,
             "reference": payload.reference, "notes": payload.notes,
             "lines": json.dumps([line.model_dump(mode="json") for line in payload.lines]),
             "actor": (self.db.info.get("tenant_context") or {}).get("user_id")}).mappings().one()
        transfer_id = str(row["id"])
        for line in sorted(payload.lines, key=lambda item: (str(item.product_id), str(item.variant_id or ""))):
            note = f"Transfer {source['code']} -> {target['code']}: {payload.notes}"
            movement_out = StockAdjustment(variant_id=line.variant_id, direction="OUT", quantity=line.quantity, notes=note)
            movement_in = StockAdjustment(variant_id=line.variant_id, direction="IN", quantity=line.quantity, notes=note)
            self.adjust_stock(str(line.product_id), movement_out, commit=False, reference_type="stock_transfer",
                              reference_id=transfer_id, store_id=str(source["id"]), movement_type="TRANSFER_OUT")
            self.adjust_stock(str(line.product_id), movement_in, commit=False, reference_type="stock_transfer",
                              reference_id=transfer_id, store_id=str(target["id"]), movement_type="TRANSFER_IN")
        result = self.transfer_detail(transfer_id)
        finish_posting(self.db, self.company_id, "stock_transfer", payload, result)
        self.db.commit()
        return result

    def reverse_transfer(self, transfer_id: str, notes: str) -> dict:
        from app.schemas.inventory import StockTransferCreate, StockTransferLine
        original = self.transfer_detail(transfer_id)
        if original["reversal_of_transfer_id"]:
            raise HTTPException(422, "A reversal transfer cannot be reversed again")
        if original["reversed_by_transfer_id"]:
            raise HTTPException(422, "This transfer has already been reversed")
        payload = StockTransferCreate(
            from_store_id=original["to_store_id"], to_store_id=original["from_store_id"],
            notes=notes, reference=original["reference"], idempotency_key=f"reverse:{transfer_id}",
            lines=[StockTransferLine(**line) for line in original["lines"]],
        )
        result = self.transfer_stock(payload)
        self.db.execute(text("update stock_transfers set reversal_of_transfer_id=:original where id=:id and company_id=:company"),
                        {"original": transfer_id, "id": str(result["id"]), "company": self.company_id})
        self.db.commit()
        return self.transfer_detail(str(result["id"]))

    def transfer_detail(self, transfer_id: str) -> dict:
        row = self.db.execute(text("""select t.*, src.code as from_store_code, dst.code as to_store_code,
                (select r.id from stock_transfers r where r.company_id=t.company_id and r.reversal_of_transfer_id=t.id) as reversed_by_transfer_id
            from stock_transfers t join stores src on src.id=t.from_store_id join stores dst on dst.id=t.to_store_id
            where t.id=:id and t.company_id=:company"""), {"id": transfer_id, "company": self.company_id}).mappings().first()
        if not row:
            raise HTTPException(404, "Transfer not found")
        return dict(row)

    def list_transfers(self, limit: int = 100) -> dict:
        rows = self.db.execute(text("""select t.*, src.code as from_store_code, dst.code as to_store_code,
                (select r.id from stock_transfers r where r.company_id=t.company_id and r.reversal_of_transfer_id=t.id) as reversed_by_transfer_id
            from stock_transfers t join stores src on src.id=t.from_store_id join stores dst on dst.id=t.to_store_id
            where t.company_id=:company order by t.transfer_date desc, t.created_at desc limit :limit"""),
            {"company": self.company_id, "limit": max(1, min(limit, 500))}).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def movements(self, product_id: str) -> dict:
        self._product(product_id)
        return {"items": [dict(row) for row in self.db.execute(text("select * from stock_movements where company_id=:company and product_id=:product order by created_at desc,id desc limit 50"), {"company": self.company_id, "product": product_id}).mappings()]}

    def stock_reconciliation(self) -> dict:
        rows = self.db.execute(
            text(
                """
                with balances as (
                    select store_id, product_id, variant_id, sum(quantity) as quantity
                    from stock_balances where company_id = :company
                    group by store_id, product_id, variant_id
                ),
                movements as (
                    select m.store_id, m.product_id, m.variant_id, count(*) as movement_count,
                           sum(case when m.movement_type in ('PURCHASE','GIFT_IN','ADJUSTMENT_IN','TRANSFER_IN')
                                    then m.quantity else -m.quantity end) as quantity,
                           count(*) filter (where
                               (m.reference_type in ('invoice', 'invoice_cancellation')
                                and not exists (select 1 from invoices i
                                    where i.company_id = m.company_id and i.id = m.reference_id))
                               or
                               (m.reference_type in ('purchase_receipt', 'purchase_cancellation')
                                and not exists (select 1 from purchases p
                                    where p.company_id = m.company_id and p.id = m.reference_id))
                               or
                               (m.reference_type = 'shop_order'
                                and not exists (select 1 from shop_orders o
                                    where o.company_id = m.company_id and o.id = m.reference_id))
                               or
                               (m.reference_type = 'stock_transfer'
                                and not exists (select 1 from stock_transfers t
                                    where t.company_id = m.company_id and t.id = m.reference_id))
                           ) as missing_document_references
                    from stock_movements m where m.company_id = :company
                    group by m.store_id, m.product_id, m.variant_id
                )
                select s.id as store_id, s.code as store_code, p.id as product_id, p.name as product_name,
                       coalesce(b.variant_id, m.variant_id) as variant_id, v.variant_name,
                       coalesce(b.quantity, 0) as balance_quantity,
                       coalesce(m.quantity, 0) as movement_quantity,
                       coalesce(b.quantity, 0) - coalesce(m.quantity, 0) as difference,
                       coalesce(m.movement_count, 0) as movement_count,
                       coalesce(m.missing_document_references, 0) as missing_document_references
                from balances b full outer join movements m
                  on m.store_id = b.store_id and m.product_id = b.product_id and m.variant_id is not distinct from b.variant_id
                join stores s on s.id = coalesce(b.store_id, m.store_id)
                  and (cast(:permitted as uuid[]) is null or s.id = any(cast(:permitted as uuid[])))
                join products p on p.id = coalesce(b.product_id, m.product_id) and p.company_id = :company
                left join product_variants v on v.id = coalesce(b.variant_id, m.variant_id)
                order by s.is_default desc, s.code, p.name, v.variant_name nulls first, p.id
                """
            ),
            {"company": self.company_id, "permitted": allowed_stores(self.db.info.get("tenant_context"))},
        ).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def missing_movement_sources(self) -> dict:
        rows = self.db.execute(
            text(
                """
                select m.id, m.product_id, p.name as product_name, m.variant_id, v.variant_name,
                       m.movement_type, m.quantity, m.reference_type, m.reference_id, m.notes, m.created_at
                from stock_movements m
                join products p on p.id = m.product_id and p.company_id = m.company_id
                left join product_variants v on v.id = m.variant_id
                where m.company_id = :company
                  and ((m.reference_type in ('invoice', 'invoice_cancellation')
                        and not exists (select 1 from invoices i
                            where i.company_id = m.company_id and i.id = m.reference_id))
                       or (m.reference_type in ('purchase_receipt', 'purchase_cancellation')
                        and not exists (select 1 from purchases pu
                            where pu.company_id = m.company_id and pu.id = m.reference_id)))
                order by m.created_at, m.id
                """
            ),
            {"company": self.company_id},
        ).mappings().all()
        return {"items": [dict(row) for row in rows]}

    def attribute_external_source(self, movement_id: str, payload: ExternalMovementSource) -> dict:
        """Re-attribute a movement whose in-system source document no longer exists to an external document.

        Quantities and balances are never changed; only the source attribution and notes are updated,
        and only when the referenced invoice/purchase is actually missing.
        """
        missing = {str(row["id"]) for row in self.missing_movement_sources()["items"]}
        if movement_id not in missing:
            raise HTTPException(422, "Only movements whose source document is missing can be re-attributed")
        row = self.db.execute(
            text(
                """
                update stock_movements
                set reference_type = 'external_document', reference_id = null,
                    notes = :notes
                where id = :id and company_id = :company
                returning id, product_id, variant_id, movement_type, quantity, reference_type, reference_id, notes
                """
            ),
            {
                "id": movement_id, "company": self.company_id,
                "notes": f"External document {payload.external_reference}: {payload.notes}",
            },
        ).mappings().one()
        self.db.commit()
        return dict(row)

    def alerts(self) -> dict:
        result = []
        for product in self.list_products()["items"]:
            if not product["is_active"]:
                continue
            for item in [product, *product["variants"]]:
                if not item["is_active"] or not item["reorder_enabled"]:
                    continue
                low = item["stock_qty"] <= item["reorder_level"]
                due = bool(item["reorder_reminder_date"] and item["reorder_reminder_date"] <= date.today())
                if low or due:
                    result.append({"product_id": product["id"], "variant_id": item["id"] if item is not product else None,
                                   "product_name": product["name"], "variant_name": item.get("variant_name"),
                                   "stock_qty": item["stock_qty"], "reorder_level": item["reorder_level"],
                                   "reorder_quantity": max(Decimal("0"), item["reorder_target"] - item["stock_qty"]),
                                   "reminder_date": item["reorder_reminder_date"], "reminder_due": due, "low_stock": low})
        return {"items": result}

    def remind(self, product_id: str, payload: ReorderReminder) -> dict:
        self._product(product_id, lock=True)
        variant_id = str(payload.variant_id) if payload.variant_id else None
        if variant_id:
            self._variant(product_id, variant_id)
        self._write("product_variants" if variant_id else "products", {"reorder_reminder_date": payload.reminder_date}, variant_id or product_id)
        self.db.commit()
        return self.alerts()
