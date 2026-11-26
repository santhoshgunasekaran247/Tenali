"""Reviewable product workbooks generated from a private AI reply."""
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.ai.media import MediaService, catalog_assets, catalog_photo_regions, crop_region
from app.services.bulk_import import BulkImport
from app.services.bulk_workbooks import workbook

REQUEST_PREFIX = "[TENALI_CATALOG_WORKBOOK]\n"
REPLY_PREFIX = "[TENALI_CATALOG_WORKBOOK_V1]\n"
CATALOG_INSTRUCTIONS = """
The user requests a reviewable product import workbook, not a business operation.
Extract product data only from the user's message and attached documents. Never invent
HSN, tax rates, prices, brands, categories or other facts. Leave uncertain fields null.
Use | between multiple category or label names. Set image_index to the zero-based
image reference index only for an image that visibly contains the product.
When numbered photo panels are provided, set image_box to the matching region:N
identifier (label R1 means region:1). Never estimate coordinates for those images.
Match the product to the visible photo, not to an assumed row/column sequence.
Without numbered panels, image_box may be x0,y0,x1,y1 in 0-1000 coordinates,
normalized independently to the full image width and height, including blank margins.
Exclude neighbouring products, price/description rows and blank space from crops.
If the image association or boundaries are uncertain, leave both fields null.
Use the provided PDF page and Excel sheet/row locations to help associate images,
but never guess an uncertain association. Describe the source catalog's visual
theme in reply. Set image_background only when a specific color is requested.
Explain uncertainties, missing data or omitted images in reply. No records are saved.
"""


class CatalogRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    sku: str | None
    description: str | None
    brand: str | None
    categories: str | None
    hsn_code: str | None
    hsn_description: str | None
    gst_rate: str | None
    vendor: str | None
    labels: str | None
    selling_price: str | None
    image_background: str | None
    image_index: int | None
    image_box: str | None = Field(description="Use the supplied region:N photo label when available; otherwise a normalized x0,y0,x1,y1 box.")


class CatalogOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reply: str
    clarification: str | None
    products: list[CatalogRow] = Field(max_length=40)


def catalog_answer(parsed: CatalogOutput) -> str:
    if not parsed.products:
        raise ValueError("No products found")
    for row in parsed.products:
        if not row.name.strip() or (row.image_index is None) != (row.image_box is None):
            raise ValueError("Invalid catalog row")
    result = REPLY_PREFIX + parsed.model_dump_json()
    if len(result) > 12000:
        raise ValueError("Catalog reply is too large")
    return result


def download_catalog(assistant, conversation_id, message_id):
    from app.ai.capabilities import current_identity
    assistant.require_enabled()
    assistant.conversation(conversation_id)
    assistant.identity = current_identity(assistant.db, assistant.identity)
    if assistant.identity.get("role") not in {"owner", "admin"}:
        raise HTTPException(403, "Only workspace owners and administrators can download bulk workbooks.")
    row = assistant.db.execute(text("""select a.content,u.attachment_ids from ai_messages a
        join ai_messages u on u.company_id=a.company_id and u.user_id=a.user_id
          and u.conversation_id=a.conversation_id and u.client_key=a.client_key and u.role='user'
        where a.id=:message and a.company_id=:company and a.user_id=:user
          and a.conversation_id=:conversation and a.role='assistant' and a.status='completed'"""),
        {**assistant.scope, "conversation": str(conversation_id), "message": str(message_id)}).mappings().first()
    if not row or not row["content"].startswith(REPLY_PREFIX):
        raise HTTPException(404, "Catalog workbook not found.")
    try:
        parsed = CatalogOutput.model_validate_json(row["content"][len(REPLY_PREFIX):])
        catalog_answer(parsed)
    except ValueError as error:
        raise HTTPException(422, "The saved catalog response is invalid.") from error
    files = catalog_assets(MediaService(assistant).attachments(conversation_id, row["attachment_ids"]))
    regions = {index: {f"region:{number}": box for number, box in enumerate(catalog_photo_regions(image["content"]), 1)}
               for index, image in enumerate(files) if image["mime_type"].startswith("image/")}
    records, images = [], {}
    for index, product in enumerate(parsed.products, 1):
        record = product.model_dump(exclude={"image_index", "image_box"}, exclude_none=True)
        if product.image_index is not None:
            if product.image_index < 0 or product.image_index >= len(files):
                raise HTTPException(422, f"Product {index} refers to an unavailable image.")
            image = files[product.image_index]
            if not image["mime_type"].startswith("image/"):
                raise HTTPException(422, f"Product {index} refers to a document instead of an image.")
            box = product.image_box
            choices = regions[product.image_index]
            if box and box.startswith("region:"):
                box = choices.get(box)
                if box is None:
                    raise HTTPException(422, f"Product {index} refers to an unavailable photo panel. Regenerate the catalog reply.")
            elif choices:
                raise HTTPException(422, f"Product {index} uses estimated image coordinates. Regenerate the catalog reply to select numbered photo panels.")
            region = crop_region(image["content"], box, preserve_alpha=True)
            if region is None:
                raise HTTPException(422, f"Product {index} has an invalid image region.")
            region.thumbnail((1200, 1200))
            output = BytesIO()
            transparent = region.mode == "RGBA"
            region.save(output, format="PNG" if transparent else "JPEG", **({} if transparent else {"quality": 85}))
            if output.tell() > 1024 * 1024:
                raise HTTPException(422, f"Product {index} image exceeds the bulk image size limit.")
            record["image_file"] = f"product-{index}.{'png' if transparent else 'jpg'}"
            images[record["image_file"]] = output.getvalue()
        records.append(record)
    if sum(map(len, images.values())) > 8 * 1024 * 1024:
        raise HTTPException(422, "Catalog images exceed the bulk image package limit; split the request.")
    notes = parsed.reply + (("\n\n" + parsed.clarification) if parsed.clarification else "")
    content = workbook("products", records, BulkImport(assistant.db, assistant.scope["company"]).suggestions(), notes=notes)
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.xlsx", content)
        for name, image in images.items():
            archive.writestr(f"images/{name}", image)
    return output.getvalue()
