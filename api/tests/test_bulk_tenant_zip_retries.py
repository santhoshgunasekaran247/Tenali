import io
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from dotenv import load_dotenv
from openpyxl import load_workbook
from PIL import Image
from sqlalchemy import text

from app.services.bulk_workbooks import read_workbook, workbook
from test_tenancy import TenantDatabaseCase


def png_bytes(color):
    output = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(output, format="PNG")
    return output.getvalue()


def image_package(kind, rows, images):
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.xlsx", workbook(kind, rows))
        for name, content in images.items():
            archive.writestr(f"images/{name}", content)
    return output.getvalue()


def result_rows(content, name, kind):
    with ZipFile(io.BytesIO(content)) as archive:
        return read_workbook(kind, archive.read(name))


class BulkTenantZipRetryTests(TenantDatabaseCase):
    def setUp(self):
        load_dotenv("api/.env")
        worker = patch("app.services.domain_onboarding.custom_domains_enabled", return_value=False)
        worker.start()
        self.addCleanup(worker.stop)
        super().setUp()
        from app.services.tenant_auth import TenantAuth
        from app.services.tenant_security import token_digest

        throttle = TenantAuth.throttle
        prefix = f"bulk-zip-{self.suffix}:"
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

    def start_job(self, cookies, kind, content):
        response = self.client.post(
            f"/bulk/jobs/{kind}?client_key={uuid4()}",
            content=content,
            headers={**self.headers(cookies), "Content-Type": "application/zip"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def finish_job(self, cookies, job):
        headers = self.headers(cookies)
        while not job["completed"]:
            response = self.client.post(f"/bulk/jobs/{job['id']}/advance", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            job = response.json()
        result = self.client.get(f"/bulk/jobs/{job['id']}/results", headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        return job, result

    def master_image(self, user, entity, name):
        table = {"brand": "brands", "category": "product_categories"}[entity]
        with self.factory() as db:
            db.info["tenant_context"] = user
            return db.execute(
                text(f"select image_url from {table} where company_id=:company and name=:name"),
                {"company": user["company_id"], "name": name},
            ).scalar_one()

    def test_brand_and_category_master_zip_images(self):
        owner, cookies, _ = self.register("bulk-master-zip")
        fixtures = (
            ("brands", "brand", "Tenant ZIP brand", "brand.png", png_bytes("navy")),
            ("categories", "category", "Tenant ZIP category", "category.png", png_bytes("teal")),
        )

        for kind, entity, name, filename, content in fixtures:
            with self.subTest(kind=kind):
                job = self.start_job(cookies, kind, image_package(
                    kind, [{"name": name, "image_file": filename}], {filename: content},
                ))
                final, result = self.finish_job(cookies, job)
                self.assertEqual((final["success"], final["failures"]), (1, 0))
                self.assertEqual(result.headers["x-bulk-success-count"], "1")
                imported = result_rows(result.content, "success.xlsx", kind)[0]
                self.assertEqual(imported["name"], name)
                self.assertTrue(self.master_image(
                    owner["user"], entity, name,
                ).startswith("/api/public-images/"))

    def test_failed_product_rolls_back_master_images_and_failure_zip_retries(self):
        owner, cookies, _ = self.register("bulk-zip-retry")
        brand_name = f"ZIP brand {self.suffix}"
        category_name = f"ZIP category {self.suffix}"
        original_brand = png_bytes("navy")
        original_category = png_bytes("teal")
        for kind, name, filename, content in (
            ("brands", brand_name, "brand-original.png", original_brand),
            ("categories", category_name, "category-original.png", original_category),
        ):
            _, result = self.finish_job(cookies, self.start_job(
                cookies, kind, image_package(kind, [{"name": name, "image_file": filename}], {filename: content}),
            ))
            self.assertEqual(result.headers["x-bulk-failure-count"], "0")

        brand_before = self.master_image(owner["user"], "brand", brand_name)
        category_before = self.master_image(owner["user"], "category", category_name)
        failing_images = {
            "failed-product.png": png_bytes("red"),
            "failed-brand.png": png_bytes("orange"),
            "failed-category.png": png_bytes("purple"),
        }
        rows = [
            {"name": f"ZIP product {index} {self.suffix}", "brand": brand_name,
             "categories": category_name, "hsn_code": "1234", "hsn_description": "Sample goods",
             "gst_rate": 0, "selling_price": 10}
            for index in (1, 3, 4)
        ]
        rows.insert(1, {
            "name": f"Retry me {self.suffix}", "brand": brand_name, "categories": category_name,
            "brand_image_file": "failed-brand.png", "category_image_file": "failed-category.png",
            "image_file": "failed-product.png", "hsn_code": "1234",
            "hsn_description": "Sample goods", "gst_rate": 0, "selling_price": -1,
        })
        job = self.start_job(cookies, "products", image_package("products", rows, failing_images))

        first = self.client.post(f"/bulk/jobs/{job['id']}/advance", headers=self.headers(cookies))
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(
            (first.json()["processed"], first.json()["success"], first.json()["failures"], first.json()["completed"]),
            (3, 2, 1, False),
        )
        final, result = self.finish_job(cookies, first.json())
        self.assertEqual((final["processed"], final["success"], final["failures"], final["completed"]),
                         (4, 3, 1, True))
        repeated = self.client.post(f"/bulk/jobs/{job['id']}/advance", headers=self.headers(cookies))
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual((repeated.json()["processed"], repeated.json()["success"], repeated.json()["failures"]),
                         (4, 3, 1))
        self.assertEqual((result.headers["x-bulk-success-count"], result.headers["x-bulk-failure-count"]),
                         ("3", "1"))

        self.assertEqual(self.master_image(owner["user"], "brand", brand_name), brand_before)
        self.assertEqual(self.master_image(owner["user"], "category", category_name), category_before)
        with ZipFile(io.BytesIO(result.content)) as archive:
            self.assertEqual(
                {name for name in archive.namelist() if name.startswith("images/")},
                {f"images/{name}" for name in failing_images},
            )
            for name, content in failing_images.items():
                self.assertEqual(archive.read(f"images/{name}"), content)
            failure_book = load_workbook(io.BytesIO(archive.read("failure.xlsx")))
            columns = {cell.value: cell.column for cell in failure_book["Data"][1]}
            failure_book["Data"].cell(2, columns["selling_price"], 25)
            corrected = io.BytesIO()
            failure_book.save(corrected)
            retry_zip = io.BytesIO()
            with ZipFile(retry_zip, "w", ZIP_DEFLATED) as retry:
                retry.writestr("failure.xlsx", corrected.getvalue())
                for name, content in failing_images.items():
                    retry.writestr(f"images/{name}", content)

        retry_job = self.start_job(cookies, "products", retry_zip.getvalue())
        retried, retry_result = self.finish_job(cookies, retry_job)
        self.assertEqual((retried["success"], retried["failures"]), (1, 0))
        self.assertEqual((retry_result.headers["x-bulk-success-count"], retry_result.headers["x-bulk-failure-count"]),
                         ("1", "0"))
        row = result_rows(retry_result.content, "success.xlsx", "products")[0]
        product = self.client.get(f"/inventory/products/{row['id']}")
        self.assertEqual(product.status_code, 200, product.text)
        product = product.json()
        self.assertTrue(product["image_url"].startswith("/api/public-images/"), product["image_url"])
        self.assertEqual(self.client.get(product["image_originals"][product["image_url"]]).content,
                         failing_images["failed-product.png"])
        for entity, name, filename in (
            ("brand", brand_name, "failed-brand.png"),
            ("category", category_name, "failed-category.png"),
        ):
            image_url = self.master_image(owner["user"], entity, name)
            self.assertTrue(image_url.startswith("/api/public-images/"), image_url)
            self.assertEqual(self.client.get(image_url).content, failing_images[filename])


if __name__ == "__main__":
    unittest.main()
