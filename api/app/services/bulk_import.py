"""Tenant-scoped spreadsheet import and selected-record export."""
import base64
import io
import warnings
from ipaddress import ip_address
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlalchemy import bindparam, text

from app.schemas.inventory import InventoryLookupCreate, ProductInput, VariantImageInput, VendorOfferInput
from app.schemas.masters import HsnMasterCreate, HsnMasterUpdate
from app.schemas.parties import PartyCreate, PartyUpdate
from app.services.bulk_workbooks import FIELDS, MAX_LOOKUPS, MAX_ROWS, OFFER_FIELDS
from app.services.inventory_service import InventoryService
from app.services.masters_service import MastersService
from app.services.parties_service import PartiesService
from app.services.object_storage import FileStore, portable_image_url


def _id(value, label="id"):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as error:
        raise HTTPException(422, f"{label} must be a valid ID from this workspace.") from error


def _changes(row, fields):
    return {field: (None if value == "<clear>" else value)
            for field in fields if (value := row.get(field)) is not None and value != ""}


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _names(value):
    if value is None:
        return []
    names = [_text(name) for name in str(value).split("|")]
    if any(not name for name in names) or len({name.casefold() for name in names}) != len(names):
        raise HTTPException(422, "Use unique, nonempty names separated by |.")
    return names


def _image_url(value):
    message = "Use a public HTTPS image URL or an existing Tenali image URL."
    if not isinstance(value, str):
        raise HTTPException(422, message)
    source = value.strip()
    if source.startswith(("/api/public-images/", "/api/catalog-assets/", "/catalog-assets/", "assets/")):
        return source
    try:
        parsed = urlsplit(source)
        hostname = (parsed.hostname or "").rstrip(".").lower()
        if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
            raise ValueError(message)
        parsed.port
        try:
            address = ip_address(hostname)
        except ValueError:
            if ("." not in hostname or hostname.endswith((".localhost", ".local", ".internal"))
                    or hostname.rsplit(".", 1)[-1].isdigit()):
                raise ValueError(message) from None
        else:
            if not address.is_global or address.is_multicast:
                raise ValueError(message)
    except ValueError as error:
        raise HTTPException(422, message) from error
    return source


def image_file_source(images, name):
    if name not in images:
        raise HTTPException(422, f"Image file '{name}' is missing from the ZIP.")
    content = images[name]
    if not content or len(content) > 1024 * 1024:
        raise HTTPException(422, "Each image must be nonempty and at most 1 MiB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > 16_000_000 or getattr(image, "n_frames", 1) != 1:
                    raise HTTPException(422, "Use a single PNG, JPEG or WebP image with at most 16 million pixels.")
                mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[image.format]
                image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise HTTPException(422, "The image file could not be read.") from error
    return content, mime, f"data:{mime};base64," + base64.b64encode(content).decode("ascii")


class BulkImport:
    def __init__(self, db, company_id):
        self.db = db
        self.company_id = str(company_id)
        self.inventory = InventoryService(db, self.company_id)
        self.masters = MastersService(db)
        self.parties = PartiesService(db)

    def suggestions(self):
        queries = {
            "brands": "select name,description from brands where company_id=:company and is_active order by name,id",
            "categories": "select name from product_categories where company_id=:company and is_active order by name,id",
            "hsn": "select code,description,gst_rate from hsn_masters where company_id=:company and is_active order by code",
            "vendors": "select legal_name from parties where company_id=:company and is_active and party_type in ('vendor','customer_vendor') order by legal_name,id",
        }
        result = {}
        for key, query in queries.items():
            values = self.db.execute(text(query + " limit :limit"), {"company": self.company_id, "limit": MAX_LOOKUPS + 1}).mappings().all()
            if len(values) > MAX_LOOKUPS:
                raise HTTPException(422, f"Too many {key} suggestions to generate a workbook.")
            result[key] = [str(next(iter(value.values()))) for value in values]
            if key == "brands":
                result["brand_descriptions"] = [value["description"] or "" for value in values]
            elif key == "hsn":
                result["hsn_descriptions"] = [value["description"] for value in values]
                result["hsn_gst_rates"] = [float(value["gst_rate"]) for value in values]
        result.update(party_types=["customer", "vendor", "customer_vendor", "friend", "employee", "other"],
                      pricing_modes=["price", "discount", "inherit"], booleans=["TRUE", "FALSE"],
                      image_entities=["product", "brand", "category"], record_types=["product", "child"],
                      vendor_availability=["UNKNOWN", "AVAILABLE", "OUT_OF_STOCK", "ON_ORDER"])
        return result

    def _lookup(self, kind, name, description=""):
        if not name:
            raise HTTPException(422, "A brand or category name cannot be blank.")
        table = {"brands": "brands", "categories": "product_categories"}[kind]
        rows = self.db.execute(text(f"""select id,is_active from {table}
            where company_id=:company and lower(name)=lower(:name) limit 2"""),
            {"company": self.company_id, "name": name}).mappings().all()
        if len(rows) > 1:
            raise HTTPException(422, f"More than one {kind} record matches '{name}'; resolve the duplicate first.")
        if rows:
            if not rows[0]["is_active"]:
                raise HTTPException(422, f"'{name}' is inactive; reactivate it first.")
            return str(rows[0]["id"])
        payload = InventoryLookupCreate(name=name, description=description)
        return str(self.inventory.create_lookup(kind, payload.name, payload.description, commit=False)["id"])

    def _hsn(self, code, description, rate):
        row = self.db.execute(text("select is_active from hsn_masters where company_id=:company and code=:code"),
                              {"company": self.company_id, "code": code}).mappings().first()
        if row:
            if not row["is_active"]:
                raise HTTPException(422, f"HSN {code} is inactive; reactivate it first.")
        else:
            self.masters.create_hsn(HsnMasterCreate(code=code, description=description, gst_rate=rate),
                                    self.company_id, commit=False)

    def _vendor(self, name):
        if not name:
            raise HTTPException(422, "A vendor name cannot be blank.")
        rows = self.db.execute(text("""select id,party_type,is_active from parties
            where company_id=:company and lower(legal_name)=lower(:name) limit 2"""),
            {"company": self.company_id, "name": name}).mappings().all()
        if len(rows) > 1:
            raise HTTPException(422, f"More than one contact matches vendor '{name}'.")
        if rows:
            if not rows[0]["is_active"] or rows[0]["party_type"] not in {"vendor", "customer_vendor"}:
                raise HTTPException(422, f"'{name}' is not an active vendor.")
            return str(rows[0]["id"])
        return str(self.parties.create(self.company_id, PartyCreate(party_type="vendor", legal_name=name), commit=False)["id"])

    def _product_values(self, record):
        values = {key: record[key] for key in ProductInput.model_fields if key in record}
        values["image_urls"] = (record.get("image_urls") or "").split("|") if record.get("image_urls") else []
        return values

    def _offer(self, product_id, vendor_id, row, current, variant_id=None):
        existing = next((offer for offer in current.get("offers", [])
                         if str(offer["vendor_id"]) == vendor_id), None)
        if existing and not existing["is_active"]:
            raise HTTPException(422, "The vendor mapping is inactive; reactivate it first.")
        values = {key: existing[key] for key in VendorOfferInput.model_fields if existing and key in existing}
        values.update(vendor_id=vendor_id, variant_id=variant_id)
        values.update({field if field in VendorOfferInput.model_fields else field.removeprefix("vendor_"): value
                       for field, value in _changes(row, OFFER_FIELDS).items()})
        return self.inventory.save_offer(product_id, VendorOfferInput.model_validate(values),
                                         str(existing["id"]) if existing else None, commit=False)

    def _child_parent(self, row):
        parent_id = _text(row.get("parent_product_id"))
        sku = _text(row.get("parent_sku"))
        if not parent_id and not sku:
            raise HTTPException(422, "Child rows need parent_product_id or parent_sku.")
        if parent_id:
            parent_id = _id(parent_id, "parent_product_id")
            parent = self.inventory.detail(parent_id)
            if sku and parent.get("sku") != sku:
                raise HTTPException(422, "parent_product_id and parent_sku refer to different products.")
            return parent_id
        matches = self.db.execute(text("select id from products where company_id=:company and sku=:sku limit 2"),
                                  {"company": self.company_id, "sku": sku}).scalars().all()
        if len(matches) != 1:
            raise HTTPException(422, "Parent SKU must match exactly one product in this workspace. Upload the parent first.")
        return str(matches[0])

    def product(self, row, images=None):
        record_type = _text(row.get("record_type")).lower() or "product"
        if record_type == "child":
            return self.variant({**row, "product_id": self._child_parent(row),
                                 "variant_name": row.get("variant_name") or row.get("name")}, images)
        if record_type != "product":
            raise HTTPException(422, "record_type must be product or child.")
        if row.get("parent_product_id") or row.get("parent_sku"):
            raise HTTPException(422, "Set record_type to child when specifying a parent.")
        product_id = _id(row["id"]) if row.get("id") not in (None, "") else None
        current = self.inventory.detail(product_id) if product_id else None
        values = self._product_values(current) if current else {}
        fields = ("name", "sku", "description", "image_url", "image_background", "selling_price",
                  "discount_percent", "pricing_mode", "is_active", "catalog_visible")
        values.update(_changes(row, fields))
        if _changes(row, ("image_url",)).get("image_url") is not None:
            values["image_url"] = _image_url(row["image_url"])
        filename = _text(row.get("image_file"))
        if filename:
            if row.get("image_url") not in (None, ""):
                raise HTTPException(422, "Provide either image_file or image_url, not both.")
            values["image_url"] = image_file_source(images or {}, filename)[2]
        if "brand" in _changes(row, ("brand",)):
            name = _changes(row, ("brand",))["brand"]
            values["brand_id"] = self._lookup("brands", _text(name), _text(row.get("brand_description"))) if name else None
        if "categories" in _changes(row, ("categories",)):
            ids = [self._lookup("categories", name) for name in _names(_changes(row, ("categories",))["categories"])]
            values.update(category_ids=ids, category_id=ids[0] if ids else None)
        for prefix, field, entity in (("brand", "brand_id", "brand"), ("category", "category_id", "category")):
            url, filename = row.get(f"{prefix}_image_url"), row.get(f"{prefix}_image_file")
            if url or filename:
                if not values.get(field):
                    raise HTTPException(422, f"Set the {prefix} name before adding its image.")
                self.image({"id": str(values[field]), "entity": entity, "image_url": url, "image_file": filename}, images or {})
        if "labels" in _changes(row, ("labels",)):
            values["tags"] = _names(_changes(row, ("labels",))["labels"])
        if "hsn_code" in _changes(row, ("hsn_code",)):
            code = _text(_changes(row, ("hsn_code",))["hsn_code"])
            if code:
                self._hsn(code, _text(row.get("hsn_description")), row.get("gst_rate"))
            values["hsn_code"] = code or None
        vendor_change = _changes(row, ("vendor",))
        vendor_id = self._vendor(_text(vendor_change["vendor"])) if vendor_change.get("vendor") else None
        if _changes(row, OFFER_FIELDS) and not vendor_id:
            raise HTTPException(422, "Set vendor to import its offer details.")
        if vendor_id and current:
            self._offer(product_id, vendor_id, row, current)
        if vendor_change and (current or not vendor_id):
            values["preferred_vendor_id"] = vendor_id
        staged = {**values, "pricing_mode": "price"} if vendor_id and not current and values.get("pricing_mode") == "discount" else values
        product = self.inventory.save_product(ProductInput.model_validate(staged), product_id, commit=False)
        product_id = str(product["id"])
        if vendor_id and not current:
            self._offer(product_id, vendor_id, row, product)
            values["preferred_vendor_id"] = vendor_id
            product = self.inventory.save_product(ProductInput.model_validate(values), product_id, commit=False)
        return str(product["id"])

    def variant(self, row, images=None):
        product_id = _id(row.get("product_id"), "product_id")
        variant_id = _id(row["id"]) if row.get("id") not in (None, "") else None
        product = self.inventory.detail(product_id)
        current = next((item for item in product["variants"] if str(item["id"]) == variant_id), None) if variant_id else None
        if variant_id and not current:
            raise HTTPException(404, "Variant does not belong to this product.")
        values = {key: current[key] for key in VariantImageInput.model_fields if current and key in current}
        values.update(_changes(row, VariantImageInput.model_fields))
        if _changes(row, ("image_url",)).get("image_url") is not None:
            values["image_url"] = _image_url(row["image_url"])
        filename = _text(row.get("image_file"))
        if filename:
            if row.get("image_url") not in (None, ""):
                raise HTTPException(422, "Provide either image_file or image_url, not both.")
            values["image_url"] = image_file_source(images or {}, filename)[2]
        vendor_change = _changes(row, ("vendor",))
        vendor_id = self._vendor(_text(vendor_change["vendor"])) if vendor_change.get("vendor") else None
        if vendor_change and not vendor_id:
            values["preferred_vendor_id"] = None
        if _changes(row, OFFER_FIELDS) and not vendor_id:
            raise HTTPException(422, "Set vendor to import its offer details.")
        if vendor_id and current:
            self._offer(product_id, vendor_id, row, current, variant_id)
            values["preferred_vendor_id"] = vendor_id
        requested_mode = values.get("pricing_mode", "inherit")
        if vendor_id and not current and requested_mode == "discount":
            values["pricing_mode"] = "inherit"
        result = self.inventory.save_variant(product_id, VariantImageInput.model_validate(values), variant_id, commit=False)
        saved_id = str(result["saved_variant_id"])
        if vendor_id and not current:
            child = next(item for item in result["variants"] if str(item["id"]) == saved_id)
            self._offer(product_id, vendor_id, row, child, saved_id)
            values.update(preferred_vendor_id=vendor_id, pricing_mode=requested_mode)
            self.inventory.save_variant(product_id, VariantImageInput.model_validate(values), saved_id, commit=False)
        return saved_id

    def hsn(self, row):
        record_id = _id(row["id"]) if row.get("id") not in (None, "") else None
        values = _changes(row, FIELDS["hsn"][1:])
        if "code" in values:
            values["code"] = _text(values["code"])
        if not record_id:
            return str(self.masters.create_hsn(HsnMasterCreate.model_validate(values), self.company_id, commit=False)["id"])
        current = self.db.execute(text("select * from hsn_masters where company_id=:company and id=:id"),
                                  {"company": self.company_id, "id": record_id}).mappings().first()
        if not current:
            raise HTTPException(404, "HSN record not found.")
        if values.get("code") and values["code"] != current["code"]:
            raise HTTPException(422, "An existing HSN code cannot be changed; create another code instead.")
        fields = {key: values.get(key, current[key]) for key in HsnMasterUpdate.model_fields}
        return str(self.masters.update_hsn(record_id, HsnMasterUpdate.model_validate(fields), self.company_id, commit=False)["id"])

    def party(self, row):
        record_id = _id(row["id"]) if row.get("id") not in (None, "") else None
        values = _changes(row, FIELDS["parties"][1:])
        if "legal_name" in values and not _text(values["legal_name"]):
            raise HTTPException(422, "Contact name cannot be blank.")
        if "is_active" in values and values["is_active"] is None:
            raise HTTPException(422, "Contact active status cannot be cleared.")
        if record_id:
            return str(self.parties.update(record_id, PartyUpdate.model_validate(values), self.company_id, commit=False)["id"])
        active = PartyUpdate.model_validate({"is_active": values.pop("is_active", True)}).is_active
        created = self.parties.create(self.company_id, PartyCreate.model_validate(values), commit=False)
        if active is False:
            created = self.parties.update(str(created["id"]), PartyUpdate(is_active=False), self.company_id, commit=False)
        return str(created["id"])

    def master(self, kind, row, images=None):
        record_id = _id(row["id"]) if row.get("id") not in (None, "") else None
        changes = _changes(row, ("name", "description", "is_active"))
        if "description" in changes and changes["description"] is None:
            changes["description"] = ""
        if record_id:
            table = {"brands": "brands", "categories": "product_categories"}[kind]
            current = self.db.execute(text(f"select name,description,is_active from {table} where company_id=:company and id=:id"),
                                      {"company": self.company_id, "id": record_id}).mappings().first()
            if not current:
                raise HTTPException(404, "Master record not found.")
            payload = InventoryLookupCreate.model_validate({**dict(current), "description": current["description"] or "", **changes})
            record_id = str(self.inventory.update_lookup(kind, record_id, payload, commit=False)["id"])
        else:
            payload = InventoryLookupCreate.model_validate(changes)
            record_id = str(self.inventory.create_lookup(kind, payload.name, payload.description, payload.is_active, commit=False)["id"])
        if row.get("image_url") == "<clear>" and not row.get("image_file"):
            table = {"brands": "brands", "categories": "product_categories"}[kind]
            self.db.execute(text(f"update {table} set image_url=null where id=:id and company_id=:company"),
                            {"id": record_id, "company": self.company_id})
        elif row.get("image_url") or row.get("image_file"):
            self.image({**row, "id": record_id, "entity": "brand" if kind == "brands" else "category"}, images or {})
        return record_id

    def image(self, row, images):
        record_id = _id(row.get("id"))
        entity = _text(row.get("entity")).lower()
        if entity not in {"product", "brand", "category"}:
            raise HTTPException(422, "Image entity must be product, brand or category.")
        name, url = _text(row.get("image_file")), _text(row.get("image_url"))
        if bool(name) == bool(url):
            raise HTTPException(422, "Provide exactly one image_file or image_url.")
        background = _text(row.get("image_background"))
        if entity != "product" and background:
            raise HTTPException(422, "Image background is supported only for products.")
        files = FileStore(self.db)
        if name:
            content, mime, source = image_file_source(images, name)
        else:
            source = _image_url(url)
        if entity == "product":
            product = self.inventory.detail(record_id)
            values = self._product_values(product)
            values["image_url"] = source
            if background:
                values["image_background"] = background
            self.inventory.save_product(ProductInput.model_validate(values), record_id, commit=False)
        else:
            table = {"brand": "brands", "category": "product_categories"}[entity]
            exists = self.db.execute(text(f"select id from {table} where id=:id and company_id=:company for update"),
                                     {"id": record_id, "company": self.company_id}).scalar_one_or_none()
            if not exists:
                raise HTTPException(404, "Image record not found in this workspace.")
            image_url = portable_image_url(files.save(self.company_id, content, mime, public=True, kind="image", portable=True)) \
                if name else files.image(self.company_id, source)
            self.db.execute(text(f"update {table} set image_url=:image where id=:id and company_id=:company"),
                            {"image": image_url, "id": record_id, "company": self.company_id})
        return record_id

    def apply_row(self, kind, row, images=None):
        if kind == "products":
            return self.product(row, images)
        if kind == "variants":
            return self.variant(row, images)
        if kind == "hsn":
            return self.hsn(row)
        if kind == "parties":
            return self.party(row)
        if kind == "images":
            return self.image(row, images or {})
        if kind in {"brands", "categories"}:
            return self.master(kind, row, images)
        raise HTTPException(422, "Invalid bulk record type.")

    def export_rows(self, kind, ids):
        if kind not in FIELDS or kind == "images" or not ids or len(ids) > MAX_ROWS:
            raise HTTPException(422, f"Select between 1 and {MAX_ROWS} records.")
        ids = list(dict.fromkeys(_id(value) for value in ids))
        if kind == "products":
            records = self.inventory.list_products(ids)["items"]
            categories = {str(row["id"]): row["name"] for row in self.db.execute(text(
                "select id,name from product_categories where company_id=:company"), {"company": self.company_id}).mappings()}
            rows = []
            for item in records:
                category_names = [categories[str(value)] for value in item.get("category_ids", [])]
                labels = item.get("tags", [])
                if any("|" in name for name in [*category_names, *labels]):
                    raise HTTPException(422, "Category and label names containing | cannot be exported; rename them first.")
                offer = next((offer for offer in item.get("offers", [])
                              if str(offer["vendor_id"]) == str(item.get("preferred_vendor_id"))), {})
                rows.append({**item, "record_type": "product", "brand": item.get("brand_name"), "categories": "|".join(category_names),
                             "labels": "|".join(labels), "vendor": item.get("preferred_vendor_name"),
                             **self._export_offer(offer)})
                for child in self.inventory.detail(str(item["id"]))["variants"]:
                    offer = next((offer for offer in child.get("offers", [])
                                  if str(offer["vendor_id"]) == str(child.get("preferred_vendor_id"))), {})
                    rows.append({**child, "name": child["variant_name"], "record_type": "child",
                                 "parent_product_id": str(item["id"]), "parent_sku": item.get("sku"),
                                 "vendor": offer.get("vendor_name"), **self._export_offer(offer)})
        elif kind == "variants":
            query = text("""select v.* from product_variants v join products p on p.id=v.product_id
                where p.company_id=:company and v.id in :ids""").bindparams(bindparam("ids", expanding=True))
            rows = []
            for row in self.db.execute(query, {"company": self.company_id, "ids": ids}).mappings():
                child = next(item for item in self.inventory.detail(str(row["product_id"]))["variants"]
                             if str(item["id"]) == str(row["id"]))
                offer = next((offer for offer in child.get("offers", [])
                              if str(offer["vendor_id"]) == str(child.get("preferred_vendor_id"))), {})
                rows.append({**child, "product_id": row["product_id"],
                             "vendor": offer.get("vendor_name"), **self._export_offer(offer)})
        else:
            table = {"hsn": "hsn_masters", "parties": "parties", "brands": "brands", "categories": "product_categories"}[kind]
            query = text(f"select * from {table} where company_id=:company and id in :ids").bindparams(bindparam("ids", expanding=True))
            rows = [dict(row) for row in self.db.execute(query, {"company": self.company_id, "ids": ids}).mappings()]
        if {str(row["id"]) for row in rows if row.get("record_type") != "child"} != set(ids):
            raise HTTPException(404, "One or more selected records do not belong to this workspace.")
        if len(rows) > MAX_ROWS:
            raise HTTPException(422, "Products and their children exceed 2,000 rows. Select fewer products.")
        return [{field: str(value) if isinstance(value, UUID) else value
                 for field in FIELDS[kind] if (value := row.get(field)) is not None} for row in rows]

    @staticmethod
    def _export_offer(offer):
        return {field: offer.get(field if field in VendorOfferInput.model_fields else field.removeprefix("vendor_"))
                for field in OFFER_FIELDS}
