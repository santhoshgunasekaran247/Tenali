import io
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4
from zipfile import ZipFile

from fastapi import HTTPException
from openpyxl import load_workbook
from PIL import Image, ImageDraw
from sqlalchemy import text

from app.services.bulk_workbooks import read_workbook
from test_tenancy import TenantDatabaseCase


def catalog_row(name="Sample product", **values):
    row = dict.fromkeys((
        "sku", "description", "brand", "categories", "hsn_code", "hsn_description",
        "gst_rate", "vendor", "labels", "selling_price", "image_background",
        "brand_image_url", "category_image_url",
    ))
    return {
        **row,
        "name": name,
        "image_index": None,
        "image_box": None,
        "product_box": None,
        **values,
    }


def catalog_reply(*products):
    from app.ai.catalog_workbook import CatalogOutput, catalog_answer

    return catalog_answer(CatalogOutput.model_validate({
        "reply": "Review these products before importing.",
        "clarification": None,
        "products": products,
    }))


def download_package(content, *products, regions=None):
    from app.ai.catalog_workbook import download_catalog

    assistant = MagicMock()
    assistant.scope = {"company": str(uuid4()), "user": str(uuid4())}
    assistant.identity = {"role": "owner"}
    assistant.db.execute.return_value.mappings.return_value.first.return_value = {
        "content": catalog_reply(*products),
        "attachment_ids": [uuid4()],
    }
    attachment = {"mime_type": "image/png", "content": content}
    with patch("app.ai.capabilities.current_identity", return_value={"role": "owner"}), \
            patch("app.ai.catalog_workbook.MediaService") as media, \
            patch("app.ai.catalog_workbook.BulkImport") as bulk, \
            patch("app.ai.catalog_workbook.catalog_photo_regions", return_value=regions or []):
        media.return_value.attachments.return_value = [attachment]
        bulk.return_value.suggestions.return_value = {}
        return download_catalog(assistant, uuid4(), uuid4())


class AICatalogProductCropTests(unittest.TestCase):
    def test_product_box_excludes_advertising_text_and_preserves_shape_and_alpha(self):
        source = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        draw = ImageDraw.Draw(source)
        draw.text((10, 10), "TOP SALE", fill=(0, 0, 0, 255))
        draw.rectangle((80, 70, 120, 130), fill=(220, 30, 40, 255))
        draw.text((10, 165), "BOTTOM OFFER", fill=(0, 0, 0, 255))
        content = io.BytesIO()
        source.save(content, format="PNG")

        package = download_package(
            content.getvalue(),
            catalog_row(name="Red item", image_index=0, image_box="region:1",
                        product_box="350,300,650,700"),
            regions=["0,0,1000,1000"],
        )
        with ZipFile(io.BytesIO(package)) as archive:
            row = read_workbook("products", archive.read("manifest.xlsx"))[0]
            with Image.open(io.BytesIO(archive.read("images/" + row["image_file"]))) as crop:
                self.assertEqual(row["image_file"], "product-1.png")
                self.assertEqual(crop.size, (60, 80))
                self.assertEqual(crop.mode, "RGBA")
                self.assertEqual(crop.getpixel((0, 0))[3], 0)
                self.assertEqual(crop.getpixel((30, 40)), (220, 30, 40, 255))
                self.assertEqual(crop.getpixel((5, 5))[3], 0)
                self.assertFalse(any(
                    crop.getpixel((x, y)) == (0, 0, 0, 255)
                    for x in range(crop.width) for y in range(crop.height)
                ))

    def test_missing_and_invalid_product_crops_return_explicit_422(self):
        source = io.BytesIO()
        Image.new("RGB", (100, 100), "white").save(source, format="PNG")
        base = catalog_row(image_index=0, image_box="region:1")
        cases = (
            (base, "whole advert panel"),
            ({**base, "product_box": "900,100,100,900"}, "invalid product-only rectangle"),
            ({**base, "product_box": "100,100,900,900", "image_box": "region:2"},
             "unavailable photo panel"),
        )
        for row, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(HTTPException, message):
                download_package(source.getvalue(), row, regions=["0,0,1000,1000"])

    def test_generated_skus_avoid_explicit_codes_and_blank_brand_is_not_described(self):
        source = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(source, format="PNG")
        package = download_package(
            source.getvalue(),
            catalog_row(name="Cup", brand="   "),
            catalog_row(name="Cup", sku="cup-001"),
        )
        with ZipFile(io.BytesIO(package)) as archive:
            rows = read_workbook("products", archive.read("manifest.xlsx"))
        self.assertEqual(rows[0]["sku"], "CUP-001-2")
        self.assertEqual(rows[0]["description"], "Cup.")
        self.assertEqual(rows[1]["sku"], "cup-001")


class AICatalogProductCropImportTests(TenantDatabaseCase):
    def setUp(self):
        from dotenv import load_dotenv

        load_dotenv("api/.env")
        worker = patch("app.services.domain_onboarding.custom_domains_enabled", return_value=False)
        worker.start()
        self.addCleanup(worker.stop)
        super().setUp()
        from app.services.tenant_auth import TenantAuth
        from app.services.tenant_security import token_digest

        throttle = TenantAuth.throttle
        prefix = f"catalog-import-{self.suffix}:"
        self.stack.enter_context(patch.object(
            TenantAuth,
            "throttle",
            autospec=True,
            side_effect=lambda auth, bucket, limit=20: throttle(auth, prefix + bucket, limit),
        ))

        def issue_fixture_session(auth, user_id, company_id):
            token = secrets.token_urlsafe(48)
            auth.db.execute(
                text("insert into tenant_sessions(token_hash,user_id,company_id,expires_at) "
                     "values(:token,:user,:company,:expires)"),
                {"token": token_digest(token), "user": user_id, "company": company_id,
                 "expires": datetime.now(timezone.utc) + timedelta(hours=12)},
            )
            auth.db.commit()
            return token

        self.stack.enter_context(patch.object(TenantAuth, "session", issue_fixture_session))

    def test_generated_catalog_zip_imports_as_a_tenant_product(self):
        from app.ai.catalog_workbook import download_catalog

        account, cookies, _ = self.register("catalog-import")
        source = io.BytesIO()
        Image.new("RGB", (40, 30), "orange").save(source, format="PNG")
        assistant = MagicMock()
        assistant.scope = {
            "company": account["user"]["company_id"],
            "user": account["user"]["user_id"],
        }
        assistant.identity = {"role": "owner"}
        assistant.db.execute.return_value.mappings.return_value.first.return_value = {
            "content": catalog_reply(catalog_row(
                name="Synthetic catalog item", image_index=0, image_box="0,0,1000,1000",
                hsn_code="1234", hsn_description="Synthetic goods", gst_rate="0",
            )),
            "attachment_ids": [uuid4()],
        }
        with patch("app.ai.capabilities.current_identity", return_value={"role": "owner"}), \
                patch("app.ai.catalog_workbook.MediaService") as media, \
                patch("app.ai.catalog_workbook.BulkImport") as bulk, \
                patch("app.ai.catalog_workbook.catalog_photo_regions", return_value=[]):
            media.return_value.attachments.return_value = [{
                "mime_type": "image/png", "content": source.getvalue(),
            }]
            bulk.return_value.suggestions.return_value = {}
            package = download_catalog(assistant, uuid4(), uuid4())

        headers = {**self.headers(cookies), "Content-Type": "application/zip"}
        started = self.client.post(
            f"/bulk/jobs/products?client_key={uuid4()}",
            content=package,
            headers=headers,
        )
        self.assertEqual(started.status_code, 200, started.text)
        job_id = started.json()["id"]
        advanced = self.client.post(f"/bulk/jobs/{job_id}/advance", headers=self.headers(cookies))
        self.assertEqual(advanced.status_code, 200, advanced.text)
        report = self.client.get(f"/bulk/jobs/{job_id}/results", headers=self.headers(cookies))
        self.assertEqual(report.status_code, 200, report.text)
        if report.headers["x-bulk-success-count"] != "1":
            with ZipFile(io.BytesIO(report.content)) as archive:
                details = list(load_workbook(io.BytesIO(archive.read("failure.xlsx"))).active.values)[:2]
            self.fail(f"Catalog product import failed: {details}")
        self.assertEqual(report.headers["x-bulk-failure-count"], "0")
        with ZipFile(io.BytesIO(report.content)) as archive:
            rows = read_workbook("products", archive.read("success.xlsx"))
        self.assertEqual(rows[0]["name"], "Synthetic catalog item")
        self.assertEqual(rows[0]["image_background"], "white")
        product = self.client.get(
            f"/inventory/products/{rows[0]['id']}",
            headers=self.headers(cookies),
        )
        self.assertEqual(product.status_code, 200, product.text)
        self.assertTrue(product.json()["image_url"])
