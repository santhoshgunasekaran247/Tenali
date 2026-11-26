import base64
import binascii
import io
import warnings
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException
from defusedxml.common import DefusedXmlException
from openpyxl import load_workbook
from PIL import Image, ImageChops, ImageOps, ImageStat, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import text

from app.ai.schemas import MAX_AI_UPLOAD_BYTES
from app.services.feature_controls import platform_settings
from app.services.product_images import PHOTO_REFERENCE

MAX_IMAGE_BYTES = 2 * 1024 * 1024
STORED_SIDE = 2048
MODEL_SIDE = 1024
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_EMBEDDED_IMAGES = 8
IMAGE_TOKEN_BOUND = 16000


def embedded_images(content):
    """Extract bounded, ordered document images and their source locations."""
    images = []

    def add(raw, location):
        if len(images) >= MAX_EMBEDDED_IMAGES:
            raise HTTPException(422, f"Use documents with at most {MAX_EMBEDDED_IMAGES} embedded images; split larger catalogs.")
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(422, "An embedded image is empty or exceeds 2 MB.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.width * image.height > 16_000_000 or getattr(image, "n_frames", 1) != 1:
                        raise HTTPException(422, "Embedded images must be still images with at most 16 million pixels.")
                    image.verify()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
            raise HTTPException(422, f"Embedded image at {location} could not be read.") from error
        images.append({"content": raw, "location": location})

    try:
        if content.startswith(b"%PDF-"):
            reader = PdfReader(io.BytesIO(content), strict=True)
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                for page_number, page in enumerate(reader.pages, 1):
                    for image in page.images:
                        add(image.data, f"PDF page {page_number}")
        elif content.startswith(b"PK"):
            book = load_workbook(io.BytesIO(content), read_only=False, data_only=False, keep_links=False)
            try:
                for sheet in book:
                    if sheet.sheet_state != "visible":
                        continue
                    for image in sheet._images:
                        anchor = getattr(image.anchor, "_from", None)
                        location = f"Excel sheet {sheet.title}" + (f", row {anchor.row + 1}, column {anchor.col + 1}" if anchor else "")
                        add(image._data(), location)
            finally:
                book.close()
    except (PdfReadError, BadZipFile, OSError, ValueError, KeyError, RecursionError, NotImplementedError, DefusedXmlException,
            Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise HTTPException(422, "Embedded document images could not be safely read.") from error
    return images


def catalog_assets(files):
    """Keep original attachment indexes stable and append embedded images."""
    assets = [dict(item) for item in files]
    for item in files:
        if item["mime_type"] != "text/plain":
            continue
        content = item["content"]
        if not (content.startswith(b"%PDF-") or content.startswith(b"PK")):
            continue
        embedded = embedded_images(content)
        required = len(item["extracted_text"].encode()) + 512 + len(embedded) * IMAGE_TOKEN_BOUND
        if item["input_bound"] < required:
            raise HTTPException(422, "Enable the catalog workbook option, then re-upload this document to process its embedded images.")
        for image in embedded:
            assets.append({"mime_type": "image/embedded", **image})
    return assets


def model_image(content):
    """The copy sent to the model: 1024px keeps one image well under the paid-input bound."""
    with Image.open(io.BytesIO(content)) as image:
        if image.format == "JPEG" and max(image.size) <= MODEL_SIDE:
            return content
        if "A" in image.getbands() or "transparency" in image.info:
            rgba = image.convert("RGBA")
            image = Image.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        else:
            image = image.convert("RGB")
        image.thumbnail((MODEL_SIDE, MODEL_SIDE))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85)
        return output.getvalue()


def photo_reference(attachment_id, box):
    return f"ai-photo:{attachment_id}/{box}"


def crop_region(content, box, *, preserve_alpha=False):
    """Full-resolution RGB crop of a 0-1000 normalized "x0,y0,x1,y1" region, or None."""
    try:
        x0, y0, x1, y1 = (float(part) for part in str(box).split(","))
    except ValueError:
        return None
    if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000) or (x1 - x0) < 20 or (y1 - y0) < 20:
        return None
    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            mode = "RGBA" if preserve_alpha and ("A" in image.getbands() or "transparency" in image.info) else "RGB"
            return image.convert(mode).crop((round(x0 * width / 1000), round(y0 * height / 1000),
                                             round(x1 * width / 1000), round(y1 * height / 1000)))
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def referenced_photo(db, company_id, reference, user_id=None):
    """Lossless PNG of a bill photo reference owned by this company (and user, for AI drafts)."""
    match = PHOTO_REFERENCE.match(reference or "")
    if not match:
        raise HTTPException(422, "Invalid document photo reference.")
    content = db.execute(text("""select content from ai_attachments where id=:id and company_id=:company
        and (cast(:user as uuid) is null or user_id=cast(:user as uuid)) and content is not null
        and mime_type like 'image/%'"""), {"id": match[1], "company": str(company_id),
                                            "user": str(user_id) if user_id else None}).scalar_one_or_none()
    region = crop_region(content, match[2], preserve_alpha=True) if content else None
    if region is None:
        raise HTTPException(422, "The bill photo for this product was removed or expired. Upload a product image in Inventory.")
    output = io.BytesIO()
    region.save(output, format="PNG", optimize=True)
    return output.getvalue()


def normalize_upload(payload):
    name = "".join(char for char in payload.file_name.replace("\\", "/").rsplit("/", 1)[-1]
                   if 32 <= ord(char) != 127).strip()
    if not name:
        raise HTTPException(422, "File name is required.")
    try:
        raw = base64.b64decode(payload.data_base64, validate=True)
    except (ValueError, binascii.Error) as error:
        raise HTTPException(422, "Invalid file encoding.") from error
    if not raw or len(raw) > MAX_AI_UPLOAD_BYTES:
        raise HTTPException(422, "Choose a non-empty file no larger than 20 MB.")
    if payload.mime_type.startswith("image/"):
        expected = {"image/png": ("PNG", (".png",)), "image/jpeg": ("JPEG", (".jpg", ".jpeg")),
                    "image/webp": ("WEBP", (".webp",))}[payload.mime_type]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format != expected[0] or not name.lower().endswith(expected[1]):
                        raise HTTPException(422, "Image content, extension and type must match.")
                    if image.width * image.height > 16_000_000 or getattr(image, "n_frames", 1) != 1:
                        raise HTTPException(422, "Use a single still image with at most 16 million pixels.")
                    image.load()
                    image = ImageOps.exif_transpose(image)
                    rgba = image.convert("RGBA") if "A" in image.getbands() or "transparency" in image.info else None
                    if rgba is not None and rgba.getchannel("A").getextrema()[0] < 255:
                        for side in (STORED_SIDE, 1600, 1200, 1000):
                            reduced = rgba.copy()
                            reduced.thumbnail((side, side))
                            output = io.BytesIO()
                            reduced.save(output, format="PNG", optimize=True)
                            if output.tell() <= MAX_IMAGE_BYTES:
                                return name, "image/png", output.getvalue(), None, IMAGE_TOKEN_BOUND
                        raise HTTPException(422, "Transparent image remains too large after resizing.")
                    image = image.convert("RGB")
                    # Keep up to 2048px so product photos cropped from a bill stay sharp; the model gets a 1024px copy.
                    image.thumbnail((STORED_SIDE, STORED_SIDE))
                    for quality in (92, 85, 75, 65):
                        output = io.BytesIO()
                        image.save(output, format="JPEG", quality=quality)
                        if output.tell() <= MAX_IMAGE_BYTES:
                            break
                    else:
                        raise HTTPException(422, "Image remains larger than 2 MB after resizing. Use a smaller image.")
                    return name, "image/jpeg", output.getvalue(), None, IMAGE_TOKEN_BOUND
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise HTTPException(422, "Invalid or oversized image.") from error
    if payload.mime_type == XLSX_MIME:
        if not name.lower().endswith(".xlsx"):
            raise HTTPException(422, "Use .xlsx for an Excel workbook.")
        try:
            with ZipFile(io.BytesIO(raw)) as archive:
                entries = archive.infolist()
                if len(entries) > 1000 or sum(item.file_size for item in entries) > 40 * 1024 * 1024 or any(item.flag_bits & 1 for item in entries):
                    raise HTTPException(422, "Excel workbook is encrypted or too large when expanded.")
            book = load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
            try:
                if len(book.sheetnames) > 5:
                    raise HTTPException(422, "Use an Excel workbook with at most five sheets.")
                lines = []
                for sheet in book:
                    if sheet.sheet_state != "visible":
                        continue
                    if (sheet.max_row or 0) > 2000 or (sheet.max_column or 0) > 30:
                        raise HTTPException(422, "Each Excel sheet must have at most 2,000 rows and 30 columns.")
                    sheet.reset_dimensions()
                    lines.append(f"Sheet: {sheet.title}")
                    for number, row in enumerate(sheet.iter_rows(), 1):
                        if number > 2000 or len(row) > 30:
                            raise HTTPException(422, "Each Excel sheet must have at most 2,000 rows and 30 columns.")
                        if any(cell.data_type == "f" for cell in row):
                            raise HTTPException(422, "Paste formula results as values before uploading an Excel workbook.")
                        values = [str(cell.value) if cell.value is not None else "" for cell in row]
                        if any(values):
                            lines.append(f"Row {number}: " + " | ".join(values))
                content = "\n".join(lines)
            finally:
                book.close()
        except (BadZipFile, OSError, ValueError, KeyError, DefusedXmlException) as error:
            raise HTTPException(422, "Excel workbook could not be safely read.") from error
    elif payload.mime_type == "text/plain":
        if not name.lower().endswith(".txt"):
            raise HTTPException(422, "Use .txt for a UTF-8 text document.")
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise HTTPException(422, "The text document must use UTF-8.") from error
    else:
        if not name.lower().endswith(".pdf") or not raw.startswith(b"%PDF-"):
            raise HTTPException(422, "PDF content, extension and type must match.")
        try:
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= 20:
                raise HTTPException(422, "Use an unencrypted PDF with one to twenty pages.")
            if any(len(page.get_contents().get_data()) > 1_000_000 for page in reader.pages if page.get_contents()):
                raise HTTPException(422, "PDF page contents are too large.")
            page_text = [page.extract_text() or "" for page in reader.pages]
            content = "\n\n".join(f"PDF page {number}: {value}" for number, value in enumerate(page_text, 1) if value.strip())
        except (PdfReadError, ValueError, KeyError, RecursionError) as error:
            raise HTTPException(422, "This PDF could not be safely read.") from error
    embedded = embedded_images(raw) if payload.catalog_images and payload.mime_type in {XLSX_MIME, "application/pdf"} else []
    if not content.strip() and embedded:
        content = "This document contains images but no extractable text."
    encoded = content.encode()
    if not content.strip() or len(encoded) > 12000 or any(ord(char) < 32 and char not in "\r\n\t" for char in content):
        raise HTTPException(422, "Use a text document with 1-12,000 UTF-8 bytes. For scanned PDFs, upload a page as an image.")
    return name, "text/plain", raw if payload.mime_type in {XLSX_MIME, "application/pdf"} else encoded, content, len(encoded) + 512 + len(embedded) * IMAGE_TOKEN_BOUND


def photo_regions(content, *, columns=96):
    """Find picture-like blocks (dense, roughly square) on a document page, top to bottom, as 0-1000
    "x0,y0,x1,y1" boxes. Text strokes are sparse and header/total bars are long, so neither qualifies."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            rows = max(1, round(columns * height / width))
            small = image.convert("RGB").resize((columns * 4, rows * 4))
    except (UnidentifiedImageError, OSError, ValueError):
        return []
    background = max(small.getcolors(small.width * small.height), key=lambda item: item[0])[1]
    ink = ImageChops.difference(small, Image.new("RGB", small.size, background)).convert("L").point(
        lambda value: 255 if value > 40 else 0)
    dense = {(row, column) for row in range(rows) for column in range(columns)
             if ImageStat.Stat(ink.crop((column * 4, row * 4, column * 4 + 4, row * 4 + 4))).mean[0] >= 0.75 * 255}
    seen, regions = set(), []
    for cell in sorted(dense):
        if cell in seen:
            continue
        seen.add(cell)
        stack, component = [cell], []
        while stack:
            row, column = stack.pop()
            component.append((row, column))
            for near in ((row + 1, column), (row - 1, column), (row, column + 1), (row, column - 1)):
                if near in dense and near not in seen:
                    seen.add(near)
                    stack.append(near)
        top, bottom = min(row for row, _ in component), max(row for row, _ in component) + 1
        left, right = min(column for _, column in component), max(column for _, column in component) + 1
        span_x, span_y = right - left, bottom - top
        if span_x < 4 or span_y < 4 or max(span_x / span_y, span_y / span_x) > 3 or len(component) < 0.5 * span_x * span_y:
            continue
        # Photos have shading; QR codes, stamps and flat logos are mostly two-tone.
        tones = small.convert("L").crop((left * 4, top * 4, right * 4, bottom * 4))
        histogram = tones.histogram()
        if sum(histogram[40:216]) < 0.3 * sum(histogram) or ImageStat.Stat(tones).stddev[0] < 15:
            continue
        regions.append((top, ",".join(str(round(value)) for value in (
            max(0, left - 1) * 1000 / columns, max(0, top - 1) * 1000 / rows,
            min(columns, right + 1) * 1000 / columns, min(rows, bottom + 1) * 1000 / rows))))
    return [box for _, box in sorted(regions)]


def photo_preview(content, box, side=480):
    """Small JPEG preview of a bill photo region for the private review screen, or None."""
    region = crop_region(content, box)
    if region is None:
        return None
    region.thumbnail((side, side))
    output = io.BytesIO()
    region.save(output, format="JPEG", quality=85)
    return output.getvalue()


class MediaService:
    def __init__(self, assistant):
        self.assistant = assistant
        self.db, self.scope = assistant.db, assistant.scope

    def upload(self, conversation_id, payload):
        self.assistant.require_enabled()
        self.assistant.lock_conversation(conversation_id)
        conversation = self.assistant.conversation(conversation_id)
        if conversation["status"] != "active" or not platform_settings(self.db)["document_inputs_enabled"]:
            raise HTTPException(403, "Document/image inputs are disabled, or this conversation is archived.")
        name, mime, raw, content, bound = normalize_upload(payload)
        count = self.db.execute(text("""select count(*) from ai_attachments where conversation_id=:conversation
            and company_id=:company and user_id=:user and expires_at>now() and content is not null"""),
            {**self.scope, "conversation": str(conversation_id)}).scalar_one()
        if count >= 10:
            raise HTTPException(422, "A conversation may hold ten private files. Remove an unused file first.")
        row = self.db.execute(text("""insert into ai_attachments(id,company_id,user_id,conversation_id,file_name,mime_type,
            content,extracted_text,input_bound,expires_at) values(:id,:company,:user,:conversation,:name,:mime,:raw,:text,:bound,:expires)
            returning id,file_name,mime_type,created_at,expires_at"""), {**self.scope, "id": uuid4(),
            "conversation": str(conversation_id), "name": name, "mime": mime, "raw": raw, "text": content,
            "bound": bound, "expires": conversation["expires_at"]}).mappings().one()
        self.assistant.audit(conversation_id, "PRIVATE_FILE_UPLOADED", row["id"])
        self.db.commit()
        return dict(row)

    def attachments(self, conversation_id, ids):
        items = []
        for attachment_id in ids:
            row = self.db.execute(text("""select * from ai_attachments where id=:id and company_id=:company and user_id=:user
                and conversation_id=:conversation and expires_at>now() and content is not null"""),
                {**self.scope, "id": str(attachment_id), "conversation": str(conversation_id)}).mappings().first()
            if not row:
                raise HTTPException(404, "Private attachment not found, expired or removed.")
            items.append(dict(row))
        return items

    def photo(self, reference):
        """Private review preview of a bill photo reference owned by the current user."""
        match = PHOTO_REFERENCE.match(reference or "")
        if not match:
            raise HTTPException(422, "Invalid document photo reference.")
        row = self.db.execute(text("""select conversation_id,content from ai_attachments where id=:id and company_id=:company
            and user_id=:user and content is not null and mime_type like 'image/%'"""),
            {**self.scope, "id": match[1]}).mappings().first()
        if not row:
            raise HTTPException(404, "Document photo not found, expired or removed.")
        self.assistant.conversation(row["conversation_id"])
        preview = photo_preview(row["content"], match[2])
        if preview is None:
            raise HTTPException(422, "Invalid document photo region.")
        return preview

    def remove(self, attachment_id):
        row = self.db.execute(text("""select conversation_id from ai_attachments where id=:id and company_id=:company
            and user_id=:user and content is not null"""), {**self.scope, "id": str(attachment_id)}).mappings().first()
        if not row:
            raise HTTPException(404, "Private attachment not found.")
        self.assistant.lock_conversation(row["conversation_id"])
        self.assistant.conversation(row["conversation_id"])
        self.db.execute(text("""update ai_attachments set content=null,extracted_text=null,file_name='Removed'
            where id=:id and company_id=:company and user_id=:user"""), {**self.scope, "id": str(attachment_id)})
        self.assistant.audit(row["conversation_id"], "PRIVATE_FILE_REMOVED", attachment_id)
        self.db.commit()
        return {"removed": True}

    def scrub(self, conversation_id):
        self.db.execute(text("""update ai_attachments set content=null,extracted_text=null,file_name='Removed'
            where conversation_id=:id and company_id=:company and user_id=:user"""),
            {**self.scope, "id": str(conversation_id)})
