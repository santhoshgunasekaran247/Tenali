import io
import os
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from dotenv import load_dotenv
from openpyxl import load_workbook
from PIL import Image
from sqlalchemy import text

from app.services.bulk_workbooks import FIELDS, read_workbook, workbook
from test_tenancy import TenantDatabaseCase


class BulkTenantRecordsTests(TenantDatabaseCase):
    def setUp(self):
        load_dotenv("api/.env")
        worker = patch("app.services.domain_onboarding.custom_domains_enabled", return_value=False)
        worker.start()
        self.addCleanup(worker.stop)
        from app.services.tenant_auth import TenantAuth
        original_throttle = TenantAuth.throttle
        bucket_prefix = str(uuid4()) + ":"
        throttle = patch.object(
            TenantAuth, "throttle", autospec=True,
            side_effect=lambda auth, bucket, limit=20: original_throttle(auth, bucket_prefix + bucket, limit),
        )
        throttle.start()
        self.addCleanup(throttle.stop)
        # This suite must never migrate a shared database.
        for name in (
            "apply_customer_migration", "apply_product_minimum_migration",
            "apply_storefront_enabled_migration", "apply_product_draft_migration",
            "apply_feature_controls_migration", "apply_self_shipping_migration",
            "apply_render_domains_migration",
        ):
            migration = patch("schema_support." + name)
            migration.start()
            self.addCleanup(migration.stop)
        super().setUp()

    def job(self, kind, content, headers, expected):
        response = self.client.post(
            f"/bulk/jobs/{kind}?client_key={uuid4()}", content=content,
            headers={**headers, "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["id"]
        while not response.json()["completed"]:
            response = self.client.post(f"/bulk/jobs/{job_id}/advance", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
        result = self.client.get(f"/bulk/jobs/{job_id}/results")
        self.assertEqual(result.status_code, 200, result.text)
        with ZipFile(io.BytesIO(result.content)) as archive:
            success = read_workbook(kind, archive.read("success.xlsx"))
            failure_book = load_workbook(io.BytesIO(archive.read("failure.xlsx")), read_only=True)
            failures = list(failure_book["Data"].values)
            failure_book.close()
        self.assertEqual(int(result.headers["x-bulk-success-count"]), expected, failures)
        self.assertEqual(int(result.headers["x-bulk-failure-count"]), 0, failures)
        self.assertEqual(len(success), expected)
        deleted = self.client.delete(f"/bulk/jobs/{job_id}", headers=headers)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        return success

    def export(self, kind, ids, headers):
        response = self.client.post(f"/bulk/exports/{kind}", json={"ids": ids}, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        return read_workbook(kind, response.content)

    def test_all_bulk_types_template_upload_retry_export_and_isolation(self):
        self.stack.enter_context(patch.dict(os.environ, {"TENALI_IMAGE_AI": "0"}))
        self.stack.enter_context(patch("app.services.object_storage.httpx.request",
                                       side_effect=AssertionError("unexpected external request")))
        owner, cookies, _ = self.register("bulk-all")
        headers = self.headers(cookies)
        name = "All " + self.suffix
        image = io.BytesIO()
        Image.new("RGB", (16, 16), "navy").save(image, format="PNG")
        image = image.getvalue()
        base = "https://images.example.com/"
        ids = {}
        retained_job = None

        def zip_content(manifest, files, manifest_name="manifest.xlsx"):
            output = io.BytesIO()
            with ZipFile(output, "w", ZIP_DEFLATED) as archive:
                archive.writestr(manifest_name, manifest)
                for filename, content in files.items():
                    archive.writestr("images/" + filename, content)
            return output.getvalue()

        def run_job(kind, content, expected_success, expected_failure, keep=False):
            nonlocal retained_job
            start = self.client.post(f"/bulk/jobs/{kind}?client_key={uuid4()}", content=content, headers=headers)
            self.assertEqual(start.status_code, 200, start.text)
            job = start.json()
            self.assertEqual((job["processed"], job["success"], job["failures"]), (0, 0, 0))
            while not job["completed"]:
                response = self.client.post(f"/bulk/jobs/{job['id']}/advance", headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                job = response.json()
                self.assertEqual(job["success"] + job["failures"], job["processed"])
            self.assertEqual((job["total"], job["success"], job["failures"]),
                             (expected_success + expected_failure, expected_success, expected_failure))
            result = self.client.get(f"/bulk/jobs/{job['id']}/results")
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual((result.headers["x-bulk-success-count"], result.headers["x-bulk-failure-count"]),
                             (str(expected_success), str(expected_failure)))
            with ZipFile(io.BytesIO(result.content)) as archive:
                success = read_workbook(kind, archive.read("success.xlsx"))
                failures = read_workbook(kind, archive.read("failure.xlsx"))
                failure_book = load_workbook(io.BytesIO(archive.read("failure.xlsx")))
                reasons = [row[-1] for row in list(failure_book["Data"].values)[1:] if row[-1]]
                failure_book.close()
                files = {path.removeprefix("images/"): archive.read(path)
                         for path in archive.namelist() if path.startswith("images/")}
            self.assertEqual((len(success), len(failures)), (expected_success, expected_failure), reasons)
            self.assertEqual(len(reasons), expected_failure, reasons)
            if keep:
                retained_job = job["id"]
            else:
                deleted = self.client.delete(f"/bulk/jobs/{job['id']}", headers=headers)
                self.assertEqual(deleted.status_code, 200, deleted.text)
            return success, failures, files

        def from_template(kind, rows):
            response = self.client.get(f"/bulk/templates/{kind}")
            self.assertEqual(response.status_code, 200, response.text)
            book = load_workbook(io.BytesIO(response.content))
            sheet = book["Data"]
            columns = {cell.value: cell.column for cell in sheet[1]}
            for number, row in enumerate(rows, 2):
                for key, value in row.items():
                    sheet.cell(number, columns[key], value)
            output = io.BytesIO()
            book.save(output)
            book.close()
            return output.getvalue()

        cases = (
            ("hsn",
             [{"code": "4419", "description": "Fixture goods", "gst_rate": 5},
              {"code": "123", "description": "Retry goods", "gst_rate": 5}],
             {"code": "4420"}, {"description": "Updated goods"}, False),
            ("parties",
             [{"party_type": "vendor", "legal_name": name + " vendor", "nickname": "Before"},
              {"party_type": "invalid", "legal_name": name + " retry contact"}],
             {"party_type": "customer"}, {"nickname": "After"}, False),
            ("brands",
             [{"name": name + " brand", "image_url": base + "brand.png"},
              {"name": name + " brand file", "image_file": "asset.png"},
              {"name": " ", "image_file": "asset.png"}],
             {"name": name + " retry brand"}, {"description": "Updated brand"}, True),
            ("categories",
             [{"name": name + " category", "image_url": base + "category.png"},
              {"name": name + " category file", "image_file": "asset.png"},
              {"name": " ", "image_file": "asset.png"}],
             {"name": name + " retry category"}, {"description": "Updated category"}, True),
        )
        for kind, rows, correction, update, with_image in cases:
            with self.subTest(kind=kind):
                content = from_template(kind, rows)
                if with_image:
                    content = zip_content(content, {"asset.png": image})
                success, failures, files = run_job(kind, content, len(rows) - 1, 1, keep=kind == "hsn")
                ids[kind] = success[0]["id"]
                if with_image:
                    self.assertEqual(files, {"asset.png": image})
                    exported_images = self.export(kind, [row["id"] for row in success], headers)
                    urls = {row["name"]: row["image_url"] for row in exported_images}
                    self.assertEqual(urls[rows[0]["name"]], rows[0]["image_url"])
                    self.assertTrue(urls[rows[1]["name"]].startswith("/api/public-images/"))
                exported = self.export(kind, [ids[kind]], headers)[0]
                exported.update(update)
                failures[0].update(correction)
                retry = workbook(kind, [exported, failures[0]])
                if with_image:
                    retry = zip_content(retry, files, "failure.xlsx")
                run_job(kind, retry, 2, 0)
                updated = self.export(kind, [ids[kind]], headers)[0]
                for field, value in update.items():
                    self.assertEqual(updated[field], value)
                print(f"bulk matrix {kind}: initial {len(rows)-1}/1, retry 2/0", flush=True)

        product_rows = [
            {"name": name + " parent", "sku": "ALL-" + self.suffix, "brand": name + " brand",
             "categories": name + " category", "hsn_code": "4419", "vendor": name + " vendor",
             "selling_price": 100, "vendor_mrp": 150, "vendor_buying_price": 70, "image_file": "asset.png"},
            {"record_type": "child", "parent_sku": "ALL-" + self.suffix, "variant_name": "Child",
             "vendor": name + " vendor", "vendor_buying_price": 40, "image_url": base + "child.png"},
            {"name": name + " url product", "hsn_code": "4419", "image_url": base + "product.png"},
            {"name": name + " retry product", "hsn_code": "4419", "selling_price": -1, "image_file": "asset.png"},
        ]
        content = zip_content(from_template("products", product_rows), {"asset.png": image})
        success, failures, files = run_job("products", content, 3, 1)
        ids["products"] = success[0]["id"]
        product = self.client.get(f"/inventory/products/{ids['products']}")
        self.assertEqual(product.status_code, 200, product.text)
        self.assertEqual((len(product.json()["variants"]), float(product.json()["offers"][0]["buying_price"])), (1, 70))
        self.assertEqual(float(product.json()["variants"][0]["offers"][0]["buying_price"]), 40)
        self.assertTrue(product.json()["image_url"].startswith("/api/public-images/"))
        url_product = self.export("products", [success[2]["id"]], headers)[0]
        self.assertEqual(url_product["image_url"], base + "product.png")
        selected = self.export("products", [ids["products"]], headers)
        self.assertEqual([row["record_type"] for row in selected], ["product", "child"])
        self.assertEqual(selected[1]["parent_product_id"], ids["products"])
        selected[0]["description"] = "Updated parent"
        failures[0]["selling_price"] = 25
        run_job("products", zip_content(workbook("products", [*selected, failures[0]]), files, "failure.xlsx"), 3, 0)
        self.assertEqual(self.export("products", [ids["products"]], headers)[0]["description"], "Updated parent")
        print("bulk matrix products: initial 3/1, retry 3/0", flush=True)

        variant_rows = [
            {"product_id": ids["products"], "variant_name": "File variant", "image_file": "asset.png"},
            {"product_id": ids["products"], "variant_name": "URL variant", "image_url": base + "variant.png"},
            {"product_id": ids["products"], "variant_name": "Retry variant", "selling_price": -1},
        ]
        success, failures, files = run_job("variants", zip_content(from_template("variants", variant_rows),
                                                                    {"asset.png": image}), 2, 1)
        ids["variants"] = success[0]["id"]
        exported = self.export("variants", [row["id"] for row in success], headers)
        images = {row["variant_name"]: row["image_url"] for row in exported}
        self.assertTrue(images["File variant"].startswith("/api/public-images/"))
        self.assertEqual(images["URL variant"], base + "variant.png")
        selected = next(row for row in exported if row["id"] == ids["variants"])
        selected["variant_name"] = "Updated variant"
        failures[0]["selling_price"] = 25
        run_job("variants", workbook("variants", [selected, failures[0]]), 2, 0)
        self.assertEqual(self.export("variants", [ids["variants"]], headers)[0]["variant_name"], "Updated variant")
        print("bulk matrix variants: initial 2/1, retry 2/0", flush=True)

        entities = {"product": ids["products"], "brand": ids["brands"], "category": ids["categories"]}
        url_rows = [{"id": record_id, "entity": entity, "image_url": base + entity + "-new.png"}
                    for entity, record_id in entities.items()]
        run_job("images", from_template("images", url_rows), 3, 0)
        for kind, entity in (("products", "product"), ("brands", "brand"), ("categories", "category")):
            row = self.export(kind, [ids[kind]], headers)[0]
            self.assertEqual(row["image_url"], base + entity + "-new.png")
        image_rows = ([{"id": record_id, "entity": entity, "image_file": "asset.png"}
                       for entity, record_id in entities.items()] +
                      [{"id": ids["brands"], "entity": "brand", "image_file": "asset.png",
                        "image_background": "white"}])
        success, failures, files = run_job("images", zip_content(workbook("images", image_rows),
                                                                  {"asset.png": image}), 3, 1)
        self.assertEqual(files, {"asset.png": image})
        failures[0]["image_background"] = None
        run_job("images", zip_content(workbook("images", failures), files, "failure.xlsx"), 1, 0)
        for kind in ("products", "brands", "categories"):
            row = self.export(kind, [ids[kind]], headers)[0]
            self.assertTrue(row["image_url"].startswith("/api/public-images/"))
        print("bulk matrix images: URLs 3/0, ZIP 3/1, retry 1/0", flush=True)

        self.client.cookies.clear()
        _, other, _ = self.register("bulk-all-other")
        self.assertEqual(self.client.get(f"/bulk/jobs/{retained_job}/results").status_code, 404)
        foreign = self.client.post("/bulk/exports/products", json={"ids": [ids["products"]]},
                                   headers=self.headers(other))
        self.assertEqual(foreign.status_code, 404, foreign.text)
        self.use_cookies(cookies)
        self.assertEqual(self.client.get(f"/bulk/jobs/{retained_job}/results").status_code, 200)
        print("bulk matrix tenant isolation: passed", flush=True)

    def test_create_export_update_and_live_product_dependencies(self):
        identity, cookies, _ = self.register("bulk-matrix")
        headers = self.headers(cookies)
        prefix = "Matrix " + self.suffix
        brand = prefix + " brand"
        category = prefix + " category"
        vendor = prefix + " vendor"

        initial = {
            "hsn": {"code": "4419", "description": "Snapshot goods", "gst_rate": 5},
            "brands": {"name": brand, "description": "Snapshot brand"},
            "categories": {"name": category, "description": "Keep category"},
            "parties": {"party_type": "vendor", "legal_name": vendor,
                        "nickname": "Keep nickname", "phone": "9876543210"},
        }
        ids = {}
        for kind, row in initial.items():
            with self.subTest(stage="create", kind=kind):
                created = self.job(kind, workbook(kind, [row]), headers, 1)
                ids[kind] = created[0]["id"]
                exported = self.export(kind, [ids[kind]], headers)
                self.assertEqual(exported[0]["id"], ids[kind])
                for field, value in row.items():
                    self.assertEqual(exported[0][field], value)

        template = self.client.get("/bulk/templates/products")
        self.assertEqual(template.status_code, 200, template.text)
        book = load_workbook(io.BytesIO(template.content))
        references = book["References"]
        hsn_ref = next(row for row in references.iter_rows(min_row=2, values_only=True) if row[3] == "4419")
        brand_ref = next(row for row in references.iter_rows(min_row=2, values_only=True) if row[0] == brand)
        self.assertEqual((hsn_ref[4], hsn_ref[5], brand_ref[1]), ("Snapshot goods", 5, "Snapshot brand"))

        updates = {
            "hsn": {"description": "Live goods", "gst_rate": 18},
            "brands": {"description": "Live brand"},
            "categories": {"name": category + " updated"},
            "parties": {"phone": "<clear>"},
        }
        for kind, changes in updates.items():
            with self.subTest(stage="update", kind=kind):
                self.job(kind, workbook(kind, [{"id": ids[kind], **changes}]), headers, 1)
                row = self.export(kind, [ids[kind]], headers)[0]
                if kind == "hsn":
                    self.assertEqual((row["code"], row["description"], row["gst_rate"]), ("4419", "Live goods", 18))
                elif kind == "brands":
                    self.assertEqual((row["name"], row["description"]), (brand, "Live brand"))
                elif kind == "categories":
                    self.assertEqual((row["name"], row["description"]), (category + " updated", "Keep category"))
                else:
                    self.assertEqual((row["nickname"], row["phone"]), ("Keep nickname", None))

        data = book["Data"]
        columns = {field: FIELDS["products"].index(field) + 1 for field in FIELDS["products"]}
        existing = {
            "name": prefix + " existing", "description": "Keep product", "sku": "EXIST-" + self.suffix,
            "brand": brand, "categories": category + " updated", "hsn_code": "4419",
            "vendor": vendor, "labels": "One|Two", "selling_price": 100,
        }
        new = {
            "name": prefix + " new", "brand": prefix + " new brand", "brand_description": "New brand description",
            "categories": prefix + " new category|" + category + " updated",
            "hsn_code": "4420", "hsn_description": "New goods", "gst_rate": 12,
            "vendor": prefix + " new vendor", "selling_price": 50,
        }
        for row_number, values in ((2, existing), (3, new)):
            for field, value in values.items():
                data.cell(row_number, columns[field], value)
        for field in ("brand_description", "hsn_description", "gst_rate"):
            self.assertEqual(data.cell(2, columns[field]).data_type, "f")
        stream = io.BytesIO()
        book.save(stream)
        book.close()
        products = self.job("products", stream.getvalue(), headers, 2)
        product_ids = {row["name"]: row["id"] for row in products}
        existing_id, new_id = product_ids[existing["name"]], product_ids[new["name"]]
        selected = {row["id"]: row for row in self.export("products", [existing_id, new_id], headers)}
        self.assertEqual(selected[existing_id]["brand"], brand)
        self.assertEqual(selected[existing_id]["vendor"], vendor)
        self.assertEqual(selected[new_id]["categories"], new["categories"])
        self.assertEqual(selected[new_id]["vendor"], new["vendor"])

        with self.factory() as db:
            db.info["tenant_context"] = identity["user"]
            rows = db.execute(text("""
                select p.id, b.description as brand_description, h.description as hsn_description,
                       h.gst_rate, p.preferred_vendor_id
                from products p join brands b on b.id=p.brand_id
                join hsn_masters h on h.company_id=p.company_id and h.code=p.hsn_code
                where p.company_id=:company and p.id in (:first, :second)
            """), {"company": identity["user"]["company_id"], "first": existing_id, "second": new_id}).mappings().all()
            by_id = {str(row["id"]): row for row in rows}
            self.assertEqual((by_id[existing_id]["brand_description"], by_id[existing_id]["hsn_description"],
                              float(by_id[existing_id]["gst_rate"])), ("Live brand", "Live goods", 18))
            self.assertEqual((by_id[new_id]["brand_description"], by_id[new_id]["hsn_description"],
                              float(by_id[new_id]["gst_rate"])), ("New brand description", "New goods", 12))
            self.assertEqual(str(by_id[existing_id]["preferred_vendor_id"]), ids["parties"])

        self.job("products", workbook("products", [{"id": existing_id, "name": prefix + " renamed",
                                                     "sku": "<clear>"}]), headers, 1)
        updated = self.export("products", [existing_id], headers)[0]
        self.assertEqual((updated["name"], updated["sku"], updated["description"]),
                         (prefix + " renamed", None, "Keep product"))
        self.assertEqual((updated["brand"], updated["vendor"]), (brand, vendor))

        variant = {"product_id": existing_id, "variant_name": "Large", "sku": "VAR-" + self.suffix,
                   "size": "Large", "colour": "Blue", "pricing_mode": "inherit"}
        variant_id = self.job("variants", workbook("variants", [variant]), headers, 1)[0]["id"]
        exported = self.export("variants", [variant_id], headers)[0]
        self.assertEqual((exported["product_id"], exported["size"], exported["colour"]), (existing_id, "Large", "Blue"))
        self.job("variants", workbook("variants", [{"id": variant_id, "product_id": existing_id,
                                                     "variant_name": "Extra large", "colour": "<clear>"}]), headers, 1)
        updated_variant = self.export("variants", [variant_id], headers)[0]
        self.assertEqual((updated_variant["variant_name"], updated_variant["size"], updated_variant["colour"]),
                         ("Extra large", "Large", None))
