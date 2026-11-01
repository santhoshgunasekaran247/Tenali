import base64
import hashlib
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import text

from app.migrate_storage import StorageMigration
from app.services.object_storage import ObjectStorage, FileStore, PUBLIC_BUCKET, PRIVATE_BUCKET
from app.schemas.company import CompanyUpdate
from app.services.company_service import CompanyService
from app.schemas.inventory import ProductInput
from app.services.inventory_service import InventoryService
from test_tenancy import TenantDatabaseCase

PNG = b"\x89PNG\r\n\x1a\nstorage-test"
IMAGE = "data:image/png;base64," + base64.b64encode(PNG).decode()


class StorageTransportTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"TENALI_SUPABASE_URL": "https://abcdefghijklmnopqrst.supabase.co",
                                         "TENALI_SUPABASE_STORAGE_KEY": "server-fixture-secret"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_upload_verification_and_duplicate_retry(self):
        company = str(uuid4())
        for status in (200, 409, 400):
            conflict = {"statusCode": "409"} if status == 400 else {}
            with patch("app.services.object_storage.httpx.request", side_effect=[
                    httpx.Response(status, json=conflict), httpx.Response(200, content=PNG)]) as transport:
                file = ObjectStorage().put_verified(company, PNG, "image/png", public=True, kind="image")
            self.assertEqual(file["bucket"], PUBLIC_BUCKET)
            self.assertEqual(file["sha256"], hashlib.sha256(PNG).hexdigest())
            self.assertTrue(file["object_path"].startswith(company + "/"))
            self.assertFalse(transport.call_args_list[0].kwargs["follow_redirects"])
            self.assertEqual(transport.call_args_list[0].kwargs["headers"]["x-upsert"], "false")

    def test_upload_errors_and_corruption_fail_explicitly(self):
        for responses in [[httpx.Response(500)], [httpx.Response(200), httpx.Response(200, content=b"corrupt")]]:
            with patch("app.services.object_storage.httpx.request", side_effect=responses):
                with self.assertRaises(HTTPException) as error:
                    ObjectStorage().put_verified(str(uuid4()), PNG, "image/png")
                self.assertEqual(error.exception.status_code, 503)
        with patch("app.services.object_storage.httpx.request", side_effect=httpx.ConnectError("offline")):
            with self.assertRaises(HTTPException):
                ObjectStorage().read(PRIVATE_BUCKET, str(uuid4()) + "/test.png")

    def test_private_bucket_privacy_and_missing_config(self):
        with patch("app.services.object_storage.httpx.request", side_effect=[
                httpx.Response(200, json={"public": True}), httpx.Response(200, json={"public": True})]):
            with self.assertRaisesRegex(HTTPException, "privacy"):
                ObjectStorage().ensure_buckets()
        with patch.dict(os.environ, {"TENALI_SUPABASE_STORAGE_KEY": ""}):
            with self.assertRaises(HTTPException) as error:
                ObjectStorage()
            self.assertEqual(error.exception.status_code, 503)


class StoredFileDatabaseTests(TenantDatabaseCase):
    def setUp(self):
        super().setUp()
        self.tenant, self.cookies, _ = self.register("storage")
        self.company = self.tenant["user"]["company_id"]
        self.objects = {}

        def put(storage, company_id, content, mime_type, public=False, kind="document"):
            digest = hashlib.sha256(content).hexdigest()
            path = f"{company_id}/{kind}-{digest}.png"
            bucket = PUBLIC_BUCKET if public else PRIVATE_BUCKET
            self.objects[(bucket, path)] = content
            return {"bucket": bucket, "file_kind": kind, "object_path": path, "mime_type": mime_type,
                    "file_size": len(content), "sha256": digest}

        self.stack.enter_context(patch.object(ObjectStorage, "put_verified", put))
        self.stack.enter_context(patch.object(ObjectStorage, "read", lambda storage, bucket, path: self.objects[(bucket, path)]))
        self.stack.enter_context(patch.object(ObjectStorage, "ensure_buckets"))

    def test_company_product_images_are_urls_and_private_signature_is_tenant_scoped(self):
        with self.factory() as db:
            company = CompanyService(db).update(CompanyUpdate(company_name="Storage Tenant", logo_url=IMAGE,
                invoice_settings={"signature_image": IMAGE}), self.company)
            self.assertIn("/storage/v1/object/public/tenali-public/", company["logo_url"])
            signature = company["invoice_settings"]["signature_image"]
            self.assertTrue(signature.startswith("/api/company/assets/"))
            product = InventoryService(db, self.company).save_product(ProductInput(name="Stored product", image_url=IMAGE, image_urls=[IMAGE]))
            self.assertEqual(product["image_url"], company["logo_url"])
            self.assertNotIn("data:", product["image_urls"])
            self.assertEqual(db.execute(text("select count(*) from stored_files where company_id=:company"),
                                        {"company": self.company}).scalar_one(), 2)
        headers = {"X-Tenant-Slug": self.tenant["user"]["tenant_slug"]}
        downloaded = self.client.get(signature, headers=headers)
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.content, PNG)
        self.assertIn("no-store", downloaded.headers["Cache-Control"])
        self.client.cookies.clear()
        self.assertEqual(self.client.get(signature).status_code, 401)
        other, _, _ = self.register("other-storage")
        self.assertEqual(self.client.get(signature, headers={"X-Tenant-Slug": other["user"]["tenant_slug"]}).status_code, 404)
        with self.factory() as db:
            with self.assertRaises(HTTPException):
                FileStore(db).image(other["user"]["company_id"], signature, private=True)

    def test_legacy_inline_and_snapshot_migration_is_verified_and_idempotent(self):
        with self.factory() as db:
            db.execute(text("update companies set logo_url=:logo,invoice_settings=cast(:settings as jsonb) where id=:company"),
                {"logo": IMAGE, "settings": '{"signature_image":"' + IMAGE + '"}', "company": self.company})
            db.commit()
            migration = StorageMigration(db, apply=True)
            migration.migrate_table("companies", ["logo_url"])
            migration.migrate_table("companies", ["invoice_settings"], json_columns=True)
            before = len(self.objects)
            migration.migrate_table("companies", ["logo_url"])
            migration.migrate_table("companies", ["invoice_settings"], json_columns=True)
            self.assertEqual(len(self.objects), before)
            company = CompanyService(db).get(self.company)
            self.assertNotIn("data:", company["logo_url"])
            self.assertNotIn("data:", company["invoice_settings"]["signature_image"])
            nested = {"seller": {"invoice_settings": {"signature_image": IMAGE}}, "total": "118.00"}
            converted = migration.transform(self.company, nested)
            self.assertEqual(converted["total"], "118.00")
            self.assertTrue(converted["seller"]["invoice_settings"]["signature_image"].startswith("/api/company/assets/"))

    def test_failed_migration_retains_original_inline_data(self):
        with self.factory() as db:
            db.execute(text("update companies set logo_url=:image where id=:company"), {"image": IMAGE, "company": self.company})
            db.commit()
            with patch.object(ObjectStorage, "put_verified", side_effect=HTTPException(503, "Fixture verification failed")):
                with self.assertRaises(HTTPException):
                    StorageMigration(db, apply=True).migrate_table("companies", ["logo_url"])
            self.assertEqual(CompanyService(db).get(self.company)["logo_url"], IMAGE)

    def test_attachment_upload_download_module_store_and_tenant_boundaries(self):
        headers = {**self.headers(self.cookies), "X-Tenant-Slug": self.tenant["user"]["tenant_slug"]}
        vendor = self.client.post("/parties", json={"party_type": "vendor", "legal_name": "Storage Vendor"}, headers=headers)
        self.assertEqual(vendor.status_code, 201, vendor.text)
        purchase = self.client.post("/purchases", json={"vendor_party_id": vendor.json()["id"], "subtotal": "10",
            "gst_total": "0", "total": "10", "attachments": [{"file_name": "receipt.png", "mime_type": "image/png",
                "data_base64": base64.b64encode(PNG).decode()}]}, headers=headers)
        self.assertEqual(purchase.status_code, 201, purchase.text)
        endpoint = "/documents/purchase/" + purchase.json()["id"]
        listed = self.client.get(endpoint, headers=headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        document = listed.json()["items"][0]
        downloaded = self.client.get(document["download_url"], headers=headers)
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.content, PNG)
        self.assertIn("attachment;", downloaded.headers["Content-Disposition"])
        with self.factory() as db:
            row = db.execute(text("select file_content,stored_file_id,storage_path from documents where id=:id"),
                             {"id": document["id"]}).one()
            self.assertIsNone(row.file_content)
            self.assertIsNotNone(row.stored_file_id)
            self.assertEqual(row.storage_path, document["download_url"])
            private_file_id = str(row.stored_file_id)
        self.assertEqual(self.client.get("/api/company/assets/" + private_file_id, headers=headers).status_code, 404)
        member_email = "limited-" + self.suffix + "@example.com"
        created = self.client.post("/auth/team", json={"display_name": "Limited", "email": member_email,
            "password": "Limited staff password 123!", "role": "staff"}, headers=headers)
        self.assertEqual(created.status_code, 201, created.text)
        member_id = next(item["id"] for item in created.json()["items"] if item["email"] == member_email)
        updated = self.client.put("/auth/team/" + member_id,
            json={"role": "staff", "is_active": True, "modules": ["inventory"]}, headers=headers)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.client.cookies.clear()
        login = self.client.post("/auth/login", json={"email": member_email, "password": "Limited staff password 123!"},
                                headers={"Origin": "http://localhost", "X-Tenant-Slug": self.tenant["user"]["tenant_slug"]})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(self.client.get(document["download_url"]).status_code, 403)
        with self.factory() as db:
            db.execute(text("update tenant_memberships set modules=array['purchases'],store_ids=cast(:stores as uuid[]) where user_id=:id"),
                       {"stores": [str(uuid4())], "id": login.json()["user"]["user_id"]})
            db.commit()
        self.assertEqual(self.client.get(document["download_url"]).status_code, 403)
        self.client.cookies.clear()
        self.register("attachment-other")
        self.assertEqual(self.client.get(document["download_url"]).status_code, 404)

    def test_document_blob_migration_removes_bytes_only_after_verified_upload(self):
        with self.factory() as db:
            document = db.execute(text("""insert into documents(company_id,document_type,file_name,storage_path,mime_type,file_size,file_content)
                values(:company,'purchase_receipt','legacy.png','database://legacy','image/png',:size,:content) returning id"""),
                {"company": self.company, "size": len(PNG), "content": PNG}).scalar_one()
            db.commit()
            migration = StorageMigration(db, apply=True)
            with patch.object(ObjectStorage, "put_verified", side_effect=HTTPException(503, "Fixture verification failed")):
                with self.assertRaises(HTTPException):
                    migration.migrate_documents()
            self.assertEqual(bytes(db.execute(text("select file_content from documents where id=:id"),
                                              {"id": document}).scalar_one()), PNG)
            migration.migrate_documents()
            row = db.execute(text("select file_content,stored_file_id from documents where id=:id"), {"id": document}).one()
            self.assertIsNone(row.file_content)
            self.assertIsNotNone(row.stored_file_id)
            self.assertEqual(self.objects[(PRIVATE_BUCKET, next(path for bucket, path in self.objects if bucket == PRIVATE_BUCKET))], PNG)


if __name__ == "__main__":
    unittest.main()
