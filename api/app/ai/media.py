import base64
import binascii
import io
import warnings
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import text

from app.services.feature_controls import platform_settings

MAX_BYTES = 2 * 1024 * 1024


def normalize_upload(payload):
    name = "".join(char for char in payload.file_name.replace("\\", "/").rsplit("/", 1)[-1]
                   if 32 <= ord(char) != 127).strip()
    if not name:
        raise HTTPException(422, "File name is required.")
    try:
        raw = base64.b64decode(payload.data_base64, validate=True)
    except (ValueError, binascii.Error) as error:
        raise HTTPException(422, "Invalid file encoding.") from error
    if not raw or len(raw) > MAX_BYTES:
        raise HTTPException(422, "Choose a non-empty file no larger than 2 MB.")
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
                    image.thumbnail((512, 512))
                    output = io.BytesIO()
                    image.convert("RGB").save(output, format="JPEG", quality=85)
                    return name, "image/jpeg", output.getvalue(), None, 16000
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise HTTPException(422, "Invalid or oversized image.") from error
    if payload.mime_type == "text/plain":
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
            if reader.is_encrypted or not 1 <= len(reader.pages) <= 5:
                raise HTTPException(422, "Use an unencrypted PDF with one to five pages.")
            if any(len(page.get_contents().get_data()) > 1_000_000 for page in reader.pages if page.get_contents()):
                raise HTTPException(422, "PDF page contents are too large.")
            content = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except (PdfReadError, ValueError, KeyError, RecursionError) as error:
            raise HTTPException(422, "This PDF could not be safely read.") from error
    encoded = content.encode()
    if not content.strip() or len(encoded) > 12000 or any(ord(char) < 32 and char not in "\r\n\t" for char in content):
        raise HTTPException(422, "Use a text document with 1-12,000 UTF-8 bytes. For scanned PDFs, upload a page as an image.")
    return name, "text/plain", encoded, content, len(encoded) + 512


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
