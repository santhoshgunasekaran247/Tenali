import base64
import hashlib
import logging
import os
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import text

from app.schemas.company import validate_image_source

logger = logging.getLogger(__name__)
PUBLIC_BUCKET = "tenali-public"
PRIVATE_BUCKET = "tenali-private"
MIME_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "application/pdf": "pdf"}


class ObjectStorage:
    def __init__(self):
        self.url = os.getenv("TENALI_SUPABASE_URL", "").strip().rstrip("/")
        self.key = os.getenv("TENALI_SUPABASE_STORAGE_KEY", "").strip()
        from app.services.federation_settings import FederationSettings
        try:
            FederationSettings.project_url(self.url)
        except ValueError as error:
            raise HTTPException(503, "Configure the hosted Supabase storage project URL on the server") from error
        if not self.url or not self.key:
            raise HTTPException(503, "Supabase storage is not configured. Contact the platform administrator.")

    def request(self, method, path, **kwargs):
        try:
            response = httpx.request(method, self.url + "/storage/v1/" + path,
                headers={"apikey": self.key, "Authorization": "Bearer " + self.key, **kwargs.pop("headers", {})},
                timeout=60, follow_redirects=False, **kwargs)
        except httpx.RequestError as error:
            logger.warning("Supabase storage transport failed (%s)", type(error).__name__)
            raise HTTPException(503, "File storage is unavailable. The operation was not confirmed; please retry.") from None
        return response

    @staticmethod
    def require_success(response, operation):
        if response.status_code not in (200, 201):
            logger.error("Supabase storage %s failed: HTTP %s", operation, response.status_code)
            raise HTTPException(503, "File storage operation failed. Check storage configuration and available quota.")

    def ensure_buckets(self):
        for bucket, public in [(PUBLIC_BUCKET, True), (PRIVATE_BUCKET, False)]:
            response = self.request("GET", "bucket/" + bucket)
            if response.status_code in (400, 404):
                created = self.request("POST", "bucket", json={"id": bucket, "name": bucket, "public": public,
                    "file_size_limit": 5 * 1024 * 1024, "allowed_mime_types": list(MIME_EXTENSIONS)})
                self.require_success(created, "create bucket")
                response = self.request("GET", "bucket/" + bucket)
            self.require_success(response, "inspect bucket")
            if response.json().get("public") is not public:
                raise HTTPException(503, "Supabase bucket privacy is incorrect. Review storage configuration before uploading.")

    @staticmethod
    def object_location(bucket, path):
        if bucket not in {PUBLIC_BUCKET, PRIVATE_BUCKET}:
            raise HTTPException(422, "Invalid storage bucket")
        parts = path.split("/")
        if len(parts) != 2 or str(UUID(parts[0])) != parts[0] or not parts[1] or any(value in path for value in ("..", "\\", "?", "#")):
            raise HTTPException(422, "Invalid tenant storage path")
        return bucket + "/" + quote(path, safe="/")

    def read(self, bucket, path):
        response = self.request("GET", "object/authenticated/" + self.object_location(bucket, path))
        self.require_success(response, "read file")
        return response.content

    def put_verified(self, company_id, content, mime_type, public=False, kind="document"):
        if not content or mime_type not in MIME_EXTENSIONS or len(content) > 5 * 1024 * 1024:
            raise HTTPException(422, "Use a supported non-empty file no larger than 5 MB")
        if kind not in {"image", "signature", "document"} or (public and kind != "image"):
            raise HTTPException(422, "Invalid stored file purpose")
        bucket = PUBLIC_BUCKET if public else PRIVATE_BUCKET
        digest = hashlib.sha256(content).hexdigest()
        path = f"{UUID(str(company_id))}/{kind}-{digest}.{MIME_EXTENSIONS[mime_type]}"
        location = self.object_location(bucket, path)
        response = self.request("POST", "object/" + location, content=content,
            headers={"Content-Type": mime_type, "x-upsert": "false", "Cache-Control": "31536000"})
        # A previous attempt may have uploaded successfully before its DB transaction rolled back.
        conflict = response.status_code == 409
        if response.status_code == 400:
            conflict = response.json().get("statusCode") in ("409", 409)
        if not conflict:
            self.require_success(response, "upload file")
        stored = self.read(bucket, path)
        if len(stored) != len(content) or hashlib.sha256(stored).hexdigest() != digest:
            logger.error("Supabase upload verification mismatch for tenant %s", company_id)
            raise HTTPException(503, "Uploaded file verification failed. Original file was not removed.")
        return {"bucket": bucket, "file_kind": kind, "object_path": path, "mime_type": mime_type, "file_size": len(content), "sha256": digest}

    def public_url(self, file):
        return self.url + "/storage/v1/object/public/" + self.object_location(file["bucket"], file["object_path"])


class FileStore:
    def __init__(self, db):
        self.db = db

    def save(self, company_id, content, mime_type, public=False, kind="document"):
        storage = ObjectStorage()
        file = storage.put_verified(company_id, content, mime_type, public, kind)
        row = self.db.execute(text("""insert into stored_files(company_id,bucket,file_kind,object_path,mime_type,file_size,sha256)
            values(:company,:bucket,:file_kind,:object_path,:mime_type,:file_size,:sha256)
            on conflict(company_id,bucket,file_kind,sha256) do nothing
            returning *"""), {"company": company_id, **file}).mappings().first()
        if not row:
            row = self.db.execute(text("select * from stored_files where company_id=:company and bucket=:bucket and file_kind=:kind and sha256=:sha256"),
                {"company": company_id, "bucket": file["bucket"], "kind": kind, "sha256": file["sha256"]}).mappings().one()
        return dict(row)

    def image(self, company_id, source, private=False):
        if not source:
            return source
        validate_image_source(source)
        if source.startswith("/api/company/assets/"):
            file_id = source.rsplit("/", 1)[-1]
            try:
                file_id = str(UUID(file_id))
            except ValueError as error:
                raise HTTPException(422, "Invalid private image URL") from error
            row = self.db.execute(text("select id from stored_files where id=:id and company_id=:company and bucket=:bucket and file_kind='signature'"),
                {"id": file_id, "company": company_id, "bucket": PRIVATE_BUCKET}).first()
            if not row or not private:
                raise HTTPException(422, "Private image does not belong to this workspace or cannot be published")
            return source
        parsed = urlsplit(source)
        if parsed.scheme in {"http", "https"}:
            if private:
                raise HTTPException(422, "Upload signature images directly so they remain private")
            return source
        if source.startswith("data:"):
            header, encoded = source.split(",", 1)
            content = base64.b64decode(encoded, validate=True)
            mime_type = header[5:].split(";", 1)[0]
        else:
            root = Path(__file__).resolve().parents[3] / "tenali-v31-exact-prototype" / "assets"
            relative = source
            for prefix in ("/api/catalog-assets/", "/catalog-assets/", "assets/"):
                if relative.startswith(prefix):
                    relative = relative[len(prefix):]
                    break
            path = (root / relative.lstrip("/")).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                raise HTTPException(422, "Image asset is missing. Upload a PNG, JPEG or WebP file.")
            content = path.read_bytes()
            mime_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower())
            if not mime_type:
                raise HTTPException(422, "Unsupported image asset type")
        file = self.save(company_id, content, mime_type, public=not private, kind="signature" if private else "image")
        return f"/api/company/assets/{file['id']}" if private else ObjectStorage().public_url(file)
