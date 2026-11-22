import base64
import hashlib
import io
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import text

from app.migrate_storage import StorageMigration
from app.services.object_storage import ObjectStorage, FileStore, PUBLIC_BUCKET, PRIVATE_BUCKET
from app.services import product_images
from app.services.product_images import display_image
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


class ProductImageTests(unittest.TestCase):
    @staticmethod
    def encode(image, kind="PNG"):
        output = io.BytesIO()
        image.save(output, format=kind)
        return output.getvalue()

    def setUp(self):
        # Display tests are deterministic: the local AI models are mocked unless a test opts in.
        for name, value in (("product_mask", None), ("upscale", None)):
            patcher = patch(f"app.services.vision_models.{name}", return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        product_images._rendered.clear()
        self.addCleanup(product_images._rendered.clear)

    def test_rendered_display_images_are_reused_by_photo_content(self):
        content = self.encode(Image.new("RGB", (60, 40), (200, 50, 50)))
        first = display_image(content)
        self.product_mask.reset_mock()
        self.assertEqual(display_image(content), first)
        self.product_mask.assert_not_called()
        self.assertNotEqual(display_image(content, 500), first)
        for index in range(product_images.RENDER_CACHE_SIZE + 1):
            display_image(self.encode(Image.new("RGB", (8, 8), (index, 0, 0))), 50)
        self.assertEqual(len(product_images._rendered), product_images.RENDER_CACHE_SIZE)

    def test_display_image_keeps_only_the_segmented_product_on_white(self):
        photo = Image.new("RGB", (400, 300), (110, 120, 130))
        photo.paste((180, 90, 30), (150, 100, 250, 200))
        mask = Image.new("L", photo.size, 0)
        mask.paste(255, (150, 100, 250, 200))
        self.product_mask.return_value = mask
        with Image.open(io.BytesIO(display_image(self.encode(photo)))) as result:
            self.assertEqual((result.format, result.size), ("WEBP", (1000, 1000)))
            result = result.convert("RGB")
            # The grey backdrop is removed entirely; the product fills ~84% of a white canvas.
            self.assertGreater(result.getpixel((500, 500))[0], 150)
            self.assertLess(result.getpixel((500, 500))[2], 80)
            for point in ((10, 10), (500, 40), (40, 500), (960, 500)):
                self.assertTrue(min(result.getpixel(point)) > 245, point)
        self.assertEqual(self.product_mask.call_args.args[0].size, (400, 300))

    def test_display_image_uses_transparency_as_the_product_cutout(self):
        clear = Image.new("RGBA", (30, 60), (0, 0, 0, 0))
        clear.paste((20, 120, 200, 255), (5, 10, 25, 50))
        with Image.open(io.BytesIO(display_image(self.encode(clear)))) as result:
            self.assertEqual(result.size, (1000, 1000))
            self.assertEqual(result.convert("RGB").getpixel((5, 5)), (255, 255, 255))
            self.assertLess(result.convert("RGB").getpixel((500, 500))[0], 60)
        self.product_mask.assert_not_called()

    def test_without_a_clear_product_the_full_photo_fills_the_square(self):
        photo = Image.new("RGB", (400, 300), "white")
        photo.paste((180, 90, 30), (150, 100, 250, 200))
        photo.paste((150, 150, 150), (390, 0, 391, 300))
        with Image.open(io.BytesIO(display_image(self.encode(photo)))) as result:
            # Bill margins and table rules are trimmed, so the photo itself fills the frame.
            self.assertGreater(result.convert("RGB").getpixel((10, 10))[0], 150)
        with Image.open(io.BytesIO(display_image(self.encode(Image.new("RGB", (40, 20), (90, 140, 60)), "JPEG")))) as result:
            self.assertEqual(result.size, (1000, 1000))
            # A wide photo is extended by a soft blur of itself rather than partial white bands.
            red, green, blue = result.convert("RGB").getpixel((500, 20))
            self.assertTrue(green > red and green > blue and green < 245)
        with self.assertRaises(HTTPException) as error:
            display_image(PNG)
        self.assertEqual(error.exception.status_code, 422)

    def test_product_image_uploads_original_and_display_versions(self):
        content = self.encode(Image.new("RGB", (50, 50), (200, 50, 50)))
        source = "data:image/png;base64," + base64.b64encode(content).decode()
        saved = []

        def save(store, company, data, mime_type, public=False, kind="document", *, portable=False):
            saved.append((data, mime_type, public, kind))
            return {"company_id": company, "id": str(len(saved))}

        company = str(uuid4())
        with patch.dict(os.environ, {"TENALI_SUPABASE_URL": "https://abcdefghijklmnopqrst.supabase.co",
                                     "TENALI_SUPABASE_STORAGE_KEY": "server-fixture-secret"}), \
                patch.object(FileStore, "save", save):
            display, original = FileStore(None).product_image(company, source)
            self.assertEqual(FileStore(None).product_image(company, "https://cdn.test/a.png"), ("https://cdn.test/a.png", None))
        self.assertEqual([(item[1], item[2], item[3]) for item in saved], [("image/png", True, "image"), ("image/webp", True, "image")])
        self.assertEqual(saved[0][0], content)
        self.assertEqual(original, f"/api/public-images/{company}/1")
        self.assertEqual(display, f"/api/public-images/{company}/2")

    def test_bill_photo_reference_publishes_full_resolution_original_and_display(self):
        reference = f"ai-photo:{uuid4()}/100,200,300,400"
        content = self.encode(Image.new("RGB", (120, 90), (180, 90, 30)))
        saved = []
        company = str(uuid4())

        def save(store, company, data, mime_type, public=False, kind="document", *, portable=False):
            saved.append((data, mime_type))
            return {"company_id": company, "id": str(len(saved))}

        with patch.dict(os.environ, {"TENALI_SUPABASE_URL": "https://abcdefghijklmnopqrst.supabase.co",
                                     "TENALI_SUPABASE_STORAGE_KEY": "server-fixture-secret"}), \
                patch.object(FileStore, "save", save), \
                patch("app.ai.media.referenced_photo", return_value=content) as resolved:
            FileStore("db").product_image(company, reference)
        resolved.assert_called_once_with("db", company, reference)
        self.assertEqual([item[1] for item in saved], ["image/png", "image/webp"])
        self.assertEqual(saved[0][0], content)
        self.assertEqual(ProductInput(name="Plate", image_url=reference).image_url, reference)
        for bad in ("ai-photo:not-a-uuid/1,2,3,4", "ftp://example.test/a.png"):
            with self.assertRaises(ValueError):
                ProductInput(name="Plate", image_url=bad)

    def test_small_photos_are_super_resolved_before_display(self):
        small = Image.new("RGB", (60, 40), "white")
        small.paste((180, 90, 30), (10, 8, 50, 32))
        self.upscale.side_effect = lambda image: image.resize((image.width * 4, image.height * 4))
        display_image(self.encode(small))
        self.assertEqual(self.upscale.call_args.args[0].size, (40, 24))
        mask = Image.new("L", small.size, 0)
        mask.paste(255, (10, 8, 50, 32))
        self.product_mask.return_value = mask
        product_images._rendered.clear()
        display_image(self.encode(small))
        self.assertEqual(self.upscale.call_args.args[0].size, (44, 28))
        # Large photos skip it, and a missing model falls back to a plain resize.
        self.upscale.reset_mock()
        self.product_mask.return_value = None
        display_image(self.encode(Image.new("RGB", (1200, 900), (90, 140, 60))))
        self.upscale.assert_not_called()


class VisionModelTests(unittest.TestCase):
    def setUp(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("OpenCV is not installed")
        switch = patch.dict(os.environ, {"TENALI_IMAGE_AI": "1"})
        switch.start()
        self.addCleanup(switch.stop)

    def test_models_stay_unloaded_unless_enabled(self):
        from app.services import vision_models
        photo = Image.new("RGB", (30, 20), (180, 90, 30))
        for value in ("", "0", "off"):
            with patch.dict(os.environ, {"TENALI_IMAGE_AI": value}), patch.object(vision_models, "_net") as net:
                self.assertIsNone(vision_models.upscale(photo))
                self.assertIsNone(vision_models.product_mask(photo))
                net.assert_not_called()
        with patch.dict(os.environ, {"TENALI_IMAGE_AI": "0"}), patch.object(vision_models, "_net") as net:
            with Image.open(io.BytesIO(display_image(ProductImageTests.encode(photo)))) as result:
                self.assertEqual((result.format, result.size), ("WEBP", (1000, 1000)))
            net.assert_not_called()

    def test_bundled_models_are_verified_and_upscale(self):
        from app.services import vision_models
        self.assertIsNotNone(vision_models.model_path("fsrcnn", download=False))
        self.assertIsNotNone(vision_models.model_path("u2netp", download=False))
        with patch.object(vision_models, "EDSR_MAX_PIXELS", 0):
            result = vision_models.upscale(Image.new("RGB", (30, 20), (180, 90, 30)))
        self.assertEqual(result.size, (120, 80))
        self.assertIsNone(vision_models.upscale(Image.new("RGB", (1000, 1000))))

    def test_bundled_segmenter_finds_a_product_and_rejects_a_featureless_photo(self):
        from PIL import ImageDraw
        from app.services import vision_models
        photo = Image.new("RGB", (320, 240), "white")
        draw = ImageDraw.Draw(photo)
        for radius in range(80, 0, -2):
            shade = 120 + radius
            draw.ellipse((160 - radius, 120 - radius * 0.8, 160 + radius, 120 + radius * 0.8), fill=(shade, 70, 30))
        with patch.object(vision_models, "SEGMENTERS", vision_models.SEGMENTERS[1:]):
            mask = vision_models.product_mask(photo)
            self.assertEqual(mask.size, photo.size)
            self.assertGreater(mask.getpixel((160, 120)), 200)
            self.assertLess(mask.getpixel((5, 5)), 40)
            self.assertIsNone(vision_models.product_mask(Image.new("RGB", (200, 150), (180, 120, 60))))


class ProductImageFixTests(unittest.TestCase):
    BASE = "https://abcdefghijklmnopqrst.supabase.co/storage/v1/object/public/" + PUBLIC_BUCKET + "/"

    def setUp(self):
        self.env = patch.dict(os.environ, {"TENALI_SUPABASE_URL": "https://abcdefghijklmnopqrst.supabase.co",
                                         "TENALI_SUPABASE_STORAGE_KEY": "server-fixture-secret"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.company = str(uuid4())

    def db(self, known=True):
        from unittest.mock import MagicMock
        db = MagicMock()
        db.execute.return_value.first.return_value = (1,) if known else None
        return db

    def test_only_this_workspaces_stored_photos_are_read(self):
        other = str(uuid4())
        for url in ["https://cdn.example.com/a.png", self.BASE + other + "/image-a.webp", "", self.BASE + "../x.png"]:
            with patch.object(ObjectStorage, "read") as read, self.assertRaises(HTTPException) as error:
                FileStore(self.db()).stored_product_image(self.company, url)
            self.assertEqual(error.exception.status_code, 422, url)
            read.assert_not_called()
        with patch.object(ObjectStorage, "read") as read, self.assertRaisesRegex(HTTPException, "not stored"):
            FileStore(self.db(known=False)).stored_product_image(self.company, self.BASE + self.company + "/image-a.webp")
        read.assert_not_called()
        with patch.object(ObjectStorage, "read", return_value=PNG) as read:
            self.assertEqual(FileStore(self.db()).stored_product_image(self.company, self.BASE + self.company + "/image-a.webp"), PNG)
        read.assert_called_once_with(PUBLIC_BUCKET, self.company + "/image-a.webp")

    def test_fix_rerenders_from_the_original_and_swaps_every_use(self):
        old, original, other = (self.BASE + self.company + f"/image-{name}.webp" for name in ("old", "original", "other"))
        product = {"id": "p", "image_url": old, "image_urls": f"{old}|{other}",
                   "image_originals": {old: original, other: self.BASE + self.company + "/image-o2.png"}}
        service = InventoryService.__new__(InventoryService)
        service.db, service.company_id = self.db(), self.company
        writes = []
        with patch.object(InventoryService, "_product", side_effect=lambda *args, **kwargs: dict(product)), \
                patch.object(InventoryService, "_write", side_effect=lambda table, values, row: writes.append(values)), \
                patch.object(InventoryService, "detail", return_value={"id": "p"}), \
                patch.object(FileStore, "stored_product_image", return_value=PNG) as stored, \
                patch("app.services.product_images.display_image", return_value=b"webp") as render, \
                patch.object(FileStore, "save", return_value={"company_id": self.company, "id": "new"}) as save:
            result = service.enhance_product_image("p", old)
            with self.assertRaises(HTTPException) as error:
                service.enhance_product_image("p", "https://cdn.example.com/not-on-product.png")
        self.assertEqual(error.exception.status_code, 422)
        new = f"/api/public-images/{self.company}/new"
        self.assertEqual(stored.call_args.args, (self.company, original))
        render.assert_called_once_with(PNG)
        self.assertEqual(save.call_args.args[1:3], (b"webp", "image/webp"))
        self.assertEqual(result["image_url"], new)
        self.assertEqual(writes, [{"image_url": new, "image_urls": f"{new}|{other}",
                                   "image_originals": {other: product["image_originals"][other], new: original}}])


class AIBillPhotoTests(unittest.TestCase):
    def test_bill_is_stored_sharp_and_sent_to_the_model_at_bounded_size(self):
        from app.ai.media import model_image
        bill = io.BytesIO()
        Image.new("RGB", (2048, 1365), "white").save(bill, format="JPEG")
        with Image.open(io.BytesIO(model_image(bill.getvalue()))) as sent:
            self.assertEqual(sent.size, (1024, 683))
        small = ProductImageTests.encode(Image.new("RGB", (300, 200)), "JPEG")
        self.assertEqual(model_image(small), small)

    def test_photo_references_crop_full_resolution_regions_within_the_company(self):
        from app.ai.media import crop_region, photo_preview, photo_reference, referenced_photo
        bill = ProductImageTests.encode(Image.new("RGB", (2000, 1000), (200, 100, 50)))
        self.assertEqual(crop_region(bill, "100,200,300,600").size, (400, 400))
        for box in ("0,0,10,10", "300,200,100,600", "a,b,c,d"):
            self.assertIsNone(crop_region(bill, box))
        with Image.open(io.BytesIO(photo_preview(bill, "0,0,1000,1000"))) as preview:
            self.assertEqual(preview.size, (480, 240))
        attachment = uuid4()

        class Rows:
            def __init__(self, value): self.value, self.params = value, None
            def execute(self, statement, params): self.params = params; return self
            def scalar_one_or_none(self): return self.value

        db = Rows(bill)
        with Image.open(io.BytesIO(referenced_photo(db, "company", photo_reference(attachment, "100,200,300,600"), "user"))) as photo:
            self.assertEqual((photo.format, photo.size), ("PNG", (400, 400)))
        self.assertEqual(db.params, {"id": str(attachment), "company": "company", "user": "user"})
        for db, reference in ((Rows(None), photo_reference(attachment, "100,200,300,600")), (Rows(bill), "ai-photo:x/1,2,3,4")):
            with self.assertRaises(HTTPException) as error:
                referenced_photo(db, "company", reference)
            self.assertEqual(error.exception.status_code, 422)


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
            photo = io.BytesIO()
            Image.new("RGB", (60, 40), (200, 120, 40)).save(photo, format="PNG")
            source = "data:image/png;base64," + base64.b64encode(photo.getvalue()).decode()
            product = InventoryService(db, self.company).save_product(ProductInput(name="Stored product", image_url=source, image_urls=[source]))
            self.assertTrue(product["image_url"].startswith(f"/api/public-images/{self.company}/"))
            self.assertEqual(product["image_urls"], product["image_url"])
            original = product["image_originals"][product["image_url"]]
            self.assertNotEqual(original, product["image_url"])
            stored = {row["sha256"]: row["mime_type"] for row in db.execute(text(
                "select sha256,mime_type from stored_files where company_id=:company and file_kind='image'"), {"company": self.company}).mappings()}
            self.assertEqual(stored[hashlib.sha256(photo.getvalue()).hexdigest()], "image/png")
            self.assertIn("image/webp", stored.values())
            self.assertEqual(db.execute(text("select count(*) from stored_files where company_id=:company"),
                                        {"company": self.company}).scalar_one(), 4)
            # A later edit that keeps the display image keeps its original; dropping it drops the pairing.
            kept = InventoryService(db, self.company).save_product(ProductInput(
                name="Stored product", image_url=product["image_url"], image_urls=[product["image_url"]]), str(product["id"]))
            self.assertEqual(kept["image_originals"], {product["image_url"]: original})
            cleared = InventoryService(db, self.company).save_product(ProductInput(name="Stored product"), str(product["id"]))
            self.assertEqual(cleared["image_originals"], {})
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
