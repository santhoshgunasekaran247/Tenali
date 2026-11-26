import io
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from dotenv import load_dotenv
from openpyxl import load_workbook
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
