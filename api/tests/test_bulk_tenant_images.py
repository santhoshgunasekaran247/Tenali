import io
import os
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from dotenv import load_dotenv
from openpyxl import load_workbook
from PIL import Image

from app.services.bulk_workbooks import read_workbook, workbook
from test_tenancy import TenantDatabaseCase


def image_bytes(format, color):
    output = io.BytesIO()
    Image.new("RGB", (24, 24), color).save(output, format=format)
    return output.getvalue()


def package(kind, rows, images):
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.xlsx", workbook(kind, rows))
        for name, content in images.items():
            archive.writestr("images/" + name, content)
    return output.getvalue()


def report_rows(content, name, kind):
    with ZipFile(io.BytesIO(content)) as archive:
        return read_workbook(kind, archive.read(name))


class BulkTenantImageTests(TenantDatabaseCase):
    def setUp(self):
        load_dotenv("api/.env")
        worker = patch("app.services.domain_onboarding.custom_domains_enabled", return_value=False)
        worker.start()
        self.addCleanup(worker.stop)
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"TENALI_IMAGE_AI": "0"}))
        from app.services.tenant_auth import TenantAuth
        throttle = TenantAuth.throttle
        prefix = str(uuid4())
        self.stack.enter_context(patch.object(
            TenantAuth, "throttle", autospec=True,
            side_effect=lambda auth, bucket, limit=20: throttle(auth, prefix + bucket, limit),
        ))

    def run_job(self, kind, content, cookies, success, failure):
        headers = self.headers(cookies)
        created = self.client.post(
            f"/bulk/jobs/{kind}?client_key={uuid4()}", content=content,
            headers={**headers, "Content-Type": "application/octet-stream"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        job = created.json()
        while not job["completed"]:
            advanced = self.client.post(f"/bulk/jobs/{job['id']}/advance", headers=headers)
            self.assertEqual(advanced.status_code, 200, advanced.text)
            job = advanced.json()
        result = self.client.get(f"/bulk/jobs/{job['id']}/results")
        self.assertEqual(result.status_code, 200, result.text)
        if result.headers["x-bulk-success-count"] != str(success):
            with ZipFile(io.BytesIO(result.content)) as archive:
                sheet = load_workbook(io.BytesIO(archive.read("failure.xlsx")))["Data"]
                details = list(sheet.values)[:5]
        else:
            details = None
        self.assertEqual(result.headers["x-bulk-success-count"], str(success), details)
        self.assertEqual(result.headers["x-bulk-failure-count"], str(failure))
        return result.content

    def assert_public_image(self, url, expected=None):
        self.assertTrue(url.startswith("/api/public-images/"), url)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.text)
        if expected is not None:
            self.assertEqual(response.content, expected)
        else:
            with Image.open(io.BytesIO(response.content)) as image:
                self.assertEqual(image.format, "WEBP")

    def lookup_image(self, user, entity, record_id):
        from sqlalchemy import text
        table = {"brand": "brands", "category": "product_categories"}[entity]
        with self.factory() as db:
            db.info["tenant_context"] = user
            return db.execute(text(f"select image_url from {table} where id=:id"),
                              {"id": record_id}).scalar_one()

    def test_file_packages_retry_urls_and_failures(self):
        registration, cookies, _ = self.register("bulk-images")
        png = image_bytes("PNG", "red")
        jpeg = image_bytes("JPEG", "green")
        webp = image_bytes("WEBP", "blue")
        rows = [
            {"name": "Image product", "brand": "Image brand", "categories": "Image category",
             "hsn_code": "4419", "hsn_description": "Goods", "gst_rate": 12,
             "image_file": "photo.png"},
            {"name": "Retry product", "hsn_code": "4419", "image_file": "retry.jpg", "selling_price": -1},
        ]
        result = self.run_job("products", package("products", rows, {"photo.png": png, "retry.jpg": jpeg}),
                              cookies, 1, 1)
        success = report_rows(result, "success.xlsx", "products")[0]
        product_id = success["id"]
        product = self.client.get(f"/inventory/products/{product_id}").json()
        self.assert_public_image(product["image_url"])
        self.assert_public_image(product["image_originals"][product["image_url"]], png)
        with ZipFile(io.BytesIO(result)) as archive:
            self.assertEqual(archive.read("images/retry.jpg"), jpeg)
            self.assertNotIn("images/photo.png", archive.namelist())
            book = load_workbook(io.BytesIO(archive.read("failure.xlsx")))
            sheet = book["Data"]
            columns = {cell.value: cell.column for cell in sheet[1]}
            sheet.cell(2, columns["selling_price"], 25)
            corrected = io.BytesIO()
            book.save(corrected)
            retry_zip = io.BytesIO()
            with ZipFile(retry_zip, "w", ZIP_DEFLATED) as retry:
                retry.writestr("failure.xlsx", corrected.getvalue())
                retry.writestr("images/retry.jpg", archive.read("images/retry.jpg"))
        retried = self.run_job("products", retry_zip.getvalue(), cookies, 1, 0)
        retry_id = report_rows(retried, "success.xlsx", "products")[0]["id"]
        retry_product = self.client.get(f"/inventory/products/{retry_id}").json()
        self.assert_public_image(retry_product["image_originals"][retry_product["image_url"]], jpeg)

        lookups = self.client.get("/inventory/lookups").json()
        brand_id = next(item["id"] for item in lookups["brands"] if item["name"] == "Image brand")
        category_id = next(item["id"] for item in lookups["categories"] if item["name"] == "Image category")
        entities = {"product": product_id, "brand": brand_id, "category": category_id}
        files = {"product.webp": webp, "brand.jpg": jpeg, "category.png": png}
        manifest = [{"id": record_id, "entity": entity, "image_file": filename}
                    for (entity, record_id), filename in zip(entities.items(), files)]
        manifest.append({"id": brand_id, "entity": "brand", "image_file": "category.png",
                         "image_background": "#ffffff"})
        image_result = self.run_job("images", package("images", manifest, files), cookies, 3, 1)
        product = self.client.get(f"/inventory/products/{product_id}").json()
        self.assert_public_image(product["image_originals"][product["image_url"]], webp)
        for entity, record_id, expected in (("brand", brand_id, jpeg), ("category", category_id, png)):
            self.assert_public_image(self.lookup_image(registration["user"], entity, record_id), expected)
        with ZipFile(io.BytesIO(image_result)) as archive:
            self.assertEqual(archive.read("images/category.png"), png)
            book = load_workbook(io.BytesIO(archive.read("failure.xlsx")))
            sheet = book["Data"]
            columns = {cell.value: cell.column for cell in sheet[1]}
            sheet.cell(2, columns["image_background"]).value = None
            corrected = io.BytesIO()
            book.save(corrected)
            retry_zip = io.BytesIO()
            with ZipFile(retry_zip, "w", ZIP_DEFLATED) as retry:
                retry.writestr("failure.xlsx", corrected.getvalue())
                retry.writestr("images/category.png", archive.read("images/category.png"))
        self.run_job("images", retry_zip.getvalue(), cookies, 1, 0)
        self.assert_public_image(self.lookup_image(registration["user"], "brand", brand_id), png)

        # External HTTPS sources are stored as links; no remote image retrieval is necessary.
        urls = {entity: f"https://images.example.test/{entity}.png" for entity in entities}
        url_rows = [{"id": record_id, "entity": entity, "image_url": urls[entity]}
                    for entity, record_id in entities.items()]
        with patch("app.services.object_storage.httpx.request", side_effect=AssertionError("unexpected network")):
            self.run_job("images", workbook("images", url_rows), cookies, 3, 0)
            self.run_job("products", workbook("products", [{
                "id": retry_id, "image_url": "https://images.example.test/product-workbook.png",
            }]), cookies, 1, 0)
            self.run_job("variants", workbook("variants", [{
                "product_id": product_id, "variant_name": "Blue", "image_url": "https://images.example.test/variant.png",
            }]), cookies, 1, 0)
        self.assertEqual(self.client.get(f"/inventory/products/{retry_id}").json()["image_url"],
                         "https://images.example.test/product-workbook.png")
        product = self.client.get(f"/inventory/products/{product_id}").json()
        self.assertEqual(product["image_url"], urls["product"])
        self.assertEqual(product["variants"][0]["image_url"], "https://images.example.test/variant.png")
        for entity in ("brand", "category"):
            self.assertEqual(self.lookup_image(registration["user"], entity, entities[entity]), urls[entity])

        bad_rows = [
            {"name": "Conflict", "image_file": "photo.png", "image_url": "https://images.example.test/a.png"},
            {"name": "Missing", "image_file": "missing.png"},
            {"name": "Corrupt", "image_file": "corrupt.png"},
        ]
        failed = self.run_job("products", package("products", bad_rows, {"photo.png": png, "corrupt.png": b"not an image"}),
                              cookies, 0, 3)
        with ZipFile(io.BytesIO(failed)) as archive:
            sheet = load_workbook(io.BytesIO(archive.read("failure.xlsx")))["Data"]
            headings = [cell.value for cell in sheet[1]]
            reasons = {row[headings.index("name")]: row[headings.index("failure_reason")]
                       for row in list(sheet.values)[1:]}
            self.assertIn("either", reasons["Conflict"])
            self.assertIn("missing", reasons["Missing"])
            self.assertIn("could not be read", reasons["Corrupt"])
            self.assertEqual(archive.read("images/corrupt.png"), b"not an image")
        image_errors = [
            {"id": brand_id, "entity": "brand", "image_file": "photo.png",
             "image_url": "https://images.example.test/a.png"},
            {"id": category_id, "entity": "category", "image_file": "missing.png"},
            {"id": product_id, "entity": "product", "image_file": "corrupt.png"},
        ]
        failed_images = self.run_job("images", package("images", image_errors, {
            "photo.png": png, "corrupt.png": b"not an image",
        }), cookies, 0, 3)
        with ZipFile(io.BytesIO(failed_images)) as archive:
            sheet = load_workbook(io.BytesIO(archive.read("failure.xlsx")))["Data"]
            headings = [cell.value for cell in sheet[1]]
            reasons = {row[headings.index("entity")]: row[headings.index("failure_reason")]
                       for row in list(sheet.values)[1:] if row[headings.index("entity")]}
            self.assertIn("exactly one", reasons["brand"])
            self.assertIn("missing", reasons["category"])
            self.assertIn("could not be read", reasons["product"])
            self.assertEqual(archive.read("images/corrupt.png"), b"not an image")
        oversized = package("products", [{"name": "Too large", "image_file": "huge.png"}],
                            {"huge.png": b"x" * (1024 * 1024 + 1)})
        response = self.client.post(f"/bulk/jobs/products?client_key={uuid4()}", content=oversized,
                                    headers=self.headers(cookies))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("exceeds 1 MiB", response.text)

    def test_private_and_non_https_urls_are_rejected(self):
        _, cookies, _ = self.register("bulk-url-safety")
        created = self.run_job("products", workbook("products", [{
            "name": "URL target", "brand": "URL brand", "categories": "URL category",
            "hsn_code": "4419", "hsn_description": "Goods", "gst_rate": 12,
        }]), cookies, 1, 0)
        product_id = report_rows(created, "success.xlsx", "products")[0]["id"]
        lookups = self.client.get("/inventory/lookups").json()
        entities = {
            "product": product_id,
            "brand": next(item["id"] for item in lookups["brands"] if item["name"] == "URL brand"),
            "category": next(item["id"] for item in lookups["categories"] if item["name"] == "URL category"),
        }
        sources = ["http://images.example.test/p.png", "https://127.0.0.1/private.png",
                   "https://192.168.1.1/private.png"]
        rows = [{"id": record_id, "entity": entity, "image_url": source}
                for entity, record_id in entities.items() for source in sources]
        self.run_job("images", workbook("images", rows), cookies, 0, len(rows))


if __name__ == "__main__":
    unittest.main()
