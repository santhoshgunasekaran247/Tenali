import io
import os
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from dotenv import load_dotenv

from app.services.bulk_workbooks import read_workbook, workbook
from test_tenancy import TenantDatabaseCase


class BulkTenantUrlTests(TenantDatabaseCase):
    def setUp(self):
        load_dotenv("api/.env")
        for name in (
            "apply_customer_migration", "apply_product_minimum_migration",
            "apply_storefront_enabled_migration", "apply_product_draft_migration",
            "apply_feature_controls_migration", "apply_self_shipping_migration",
            "apply_render_domains_migration",
        ):
            migration = patch("schema_support." + name)
            migration.start()
            self.addCleanup(migration.stop)
        worker = patch("app.services.domain_onboarding.custom_domains_enabled", return_value=False)
        worker.start()
        self.addCleanup(worker.stop)
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"TENALI_IMAGE_AI": "0"}))
        from app.services.tenant_auth import TenantAuth
        throttle = TenantAuth.throttle
        prefix = str(uuid4()) + ":"
        self.stack.enter_context(patch.object(
            TenantAuth, "throttle", autospec=True,
            side_effect=lambda auth, bucket, limit=20: throttle(auth, prefix + bucket, limit),
        ))

    def job(self, kind, rows, cookies, success, failure=0):
        headers = self.headers(cookies)
        response = self.client.post(
            f"/bulk/jobs/{kind}?client_key={uuid4()}", content=workbook(kind, rows),
            headers={**headers, "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        job = response.json()
        while not job["completed"]:
            response = self.client.post(f"/bulk/jobs/{job['id']}/advance", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            job = response.json()
        result = self.client.get(f"/bulk/jobs/{job['id']}/results")
        self.assertEqual(result.status_code, 200, result.text)
        with ZipFile(io.BytesIO(result.content)) as archive:
            succeeded = read_workbook(kind, archive.read("success.xlsx"))
            failed = read_workbook(kind, archive.read("failure.xlsx"))
        self.assertEqual(len(succeeded), success, failed)
        self.assertEqual(len(failed), failure, failed)
        self.assertEqual(int(result.headers["x-bulk-success-count"]), success)
        self.assertEqual(int(result.headers["x-bulk-failure-count"]), failure)
        return succeeded, failed

    def export(self, kind, ids, cookies, status=200):
        response = self.client.post(
            f"/bulk/exports/{kind}", json={"ids": ids}, headers=self.headers(cookies),
        )
        self.assertEqual(response.status_code, status, response.text)
        return read_workbook(kind, response.content) if status == 200 else None

    def test_https_urls_create_update_and_selected_export(self):
        _, cookies, _ = self.register("bulk-url-own")
        base = "https://images.example.com/"
        ids = {}
        for kind in ("brands", "categories"):
            initial = base + kind + "-initial.png"
            updated = base + kind + "-updated.png"
            created, _ = self.job(kind, [{"name": kind + self.suffix, "image_url": initial}], cookies, 1)
            ids[kind] = created[0]["id"]
            self.assertEqual(self.export(kind, [ids[kind]], cookies)[0]["image_url"], initial)
            self.job(kind, [{"id": ids[kind], "image_url": updated}], cookies, 1)
            self.assertEqual(self.export(kind, [ids[kind]], cookies)[0]["image_url"], updated)

        product = {
            "name": "URL product " + self.suffix, "hsn_code": "4419",
            "hsn_description": "Synthetic goods", "gst_rate": 0,
            "brand": "brands" + self.suffix, "categories": "categories" + self.suffix,
            "image_url": base + "product-initial.png", "image_background": "white",
            "brand_image_url": base + "brand-from-product.png",
            "category_image_url": base + "category-from-product.png",
        }
        created, _ = self.job("products", [product], cookies, 1)
        product_id = created[0]["id"]
        row = self.export("products", [product_id], cookies)[0]
        self.assertEqual(row["image_url"], product["image_url"])
        self.assertEqual(self.export("brands", [ids["brands"]], cookies)[0]["image_url"], product["brand_image_url"])
        self.assertEqual(self.export("categories", [ids["categories"]], cookies)[0]["image_url"], product["category_image_url"])
        self.assertEqual(self.client.get(f"/inventory/products/{product_id}").json()["image_background"], "#ffffff")

        changes = {
            "id": product_id, "image_url": base + "product-updated.png",
            "brand_image_url": base + "brand-updated-again.png",
            "category_image_url": base + "category-updated-again.png",
        }
        self.job("products", [changes], cookies, 1)
        self.assertEqual(self.export("products", [product_id], cookies)[0]["image_url"], changes["image_url"])
        self.assertEqual(self.export("brands", [ids["brands"]], cookies)[0]["image_url"], changes["brand_image_url"])
        self.assertEqual(self.export("categories", [ids["categories"]], cookies)[0]["image_url"], changes["category_image_url"])

    def test_foreign_product_and_master_ids_are_rejected_without_affecting_own_records(self):
        _, owner, _ = self.register("bulk-url-owner")
        url = "https://images.example.com/original.png"
        ids = {}
        for kind in ("brands", "categories"):
            created, _ = self.job(kind, [{"name": kind + self.suffix, "image_url": url}], owner, 1)
            ids[kind] = created[0]["id"]
        created, _ = self.job("products", [{
            "name": "Private " + self.suffix, "hsn_code": "4419",
            "hsn_description": "Synthetic goods", "gst_rate": 0, "image_url": url,
        }], owner, 1)
        ids["products"] = created[0]["id"]

        _, other, _ = self.register("bulk-url-other")
        other_created, _ = self.job("brands", [{"name": "Own " + self.suffix, "image_url": url}], other, 1)
        other_brand = other_created[0]["id"]
        attack_url = "https://images.example.com/attack.png"
        for kind in ("products", "brands", "categories"):
            self.job(kind, [{"id": ids[kind], "image_url": attack_url}], other, 0, 1)
            self.export(kind, [ids[kind]], other, 404)
        self.export("brands", [other_brand, ids["brands"]], other, 404)
        self.job("variants", [{"product_id": ids["products"], "variant_name": "Foreign"}], other, 0, 1)
        for kind, entity in (("products", "product"), ("brands", "brand"), ("categories", "category")):
            self.job("images", [{"id": ids[kind], "entity": entity, "image_url": attack_url}], other, 0, 1)
        self.assertEqual(self.export("brands", [other_brand], other)[0]["image_url"], url)
        self.use_cookies(owner)
        for kind in ("products", "brands", "categories"):
            self.assertEqual(self.export(kind, [ids[kind]], owner)[0]["image_url"], url)
