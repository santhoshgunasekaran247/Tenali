import asyncio
import io
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from dotenv import load_dotenv
from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import bindparam, text

from app.api.routes.bulk import upload
from app.services.bulk_workbooks import read_workbook, workbook
from test_tenancy import TenantDatabaseCase


def save_book(book):
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


class WorkbookBoundaryTests(unittest.TestCase):
    def test_product_autofill_position_and_tampering(self):
        source = workbook("products")
        book = load_workbook(io.BytesIO(source))
        data = book["Data"]
        data["B2"] = "Valid generated formulas"
        data["E2"] = "Existing"
        valid = save_book(book)
        row = read_workbook("products", valid)[0]
        self.assertEqual(row["name"], "Valid generated formulas")
        self.assertIsNone(row["brand_description"])
        formula = data["F2"].value
        data["F2"] = formula.replace("$E2", "$E3")
        with self.assertRaises(HTTPException) as modified:
            read_workbook("products", save_book(book))
        self.assertEqual(modified.exception.status_code, 422)
        data["F2"] = None
        data["F3"] = formula
        with self.assertRaises(HTTPException) as moved:
            read_workbook("products", save_book(book))
        self.assertEqual(moved.exception.status_code, 422)
        data["F3"] = None
        data["C2"] = "=1+1"
        with self.assertRaises(HTTPException):
            read_workbook("products", save_book(book))

    def test_workbook_limits_and_invalid_structure(self):
        with patch("app.services.bulk_workbooks.MAX_ROWS", 2):
            content = workbook("brands", [{"name": "One"}, {"name": "Two"}])
            self.assertEqual(len(read_workbook("brands", content)), 2)
            too_many = workbook("brands", [{"name": str(i)} for i in range(3)])
            with self.assertRaises(HTTPException) as error:
                read_workbook("brands", too_many)
            self.assertEqual(error.exception.status_code, 422)
        book = load_workbook(io.BytesIO(content))
        book["Data"]["B1"] = "id"
        with self.assertRaises(HTTPException) as duplicate:
            read_workbook("brands", save_book(book))
        self.assertEqual(duplicate.exception.status_code, 422)
        with patch("app.services.bulk_workbooks.MAX_UPLOAD_BYTES", 8):
            with self.assertRaises(HTTPException) as size:
                read_workbook("brands", b"x" * 9)
            self.assertEqual(size.exception.status_code, 413)
        with patch("app.services.bulk_workbooks.MAX_EXPANDED_BYTES", 8):
            archive = io.BytesIO()
            with ZipFile(archive, "w", ZIP_DEFLATED) as zipped:
                zipped.writestr("payload", b"x" * 9)
            with self.assertRaises(HTTPException) as expanded:
                read_workbook("brands", archive.getvalue())
            self.assertEqual(expanded.exception.status_code, 413)

    def test_stream_upload_limits_apply_to_both_workbook_and_image_kinds(self):
        class Request:
            async def stream(self):
                yield b"1234"
                yield b"56789"

        for kind, setting in (("brands", "MAX_IMAGE_UPLOAD_BYTES"), ("parties", "MAX_UPLOAD_BYTES")):
            with self.subTest(kind=kind), patch("app.api.routes.bulk." + setting, 8):
                with self.assertRaises(HTTPException) as error:
                    asyncio.run(upload(kind, Request(), uuid4(), MagicMock()))
                self.assertEqual(error.exception.status_code, 413)


class BulkTenantRecoveryTests(TenantDatabaseCase):
    def setUp(self):
        load_dotenv("api/.env")
        worker = patch("app.services.domain_onboarding.custom_domains_enabled", return_value=False)
        worker.start()
        self.addCleanup(worker.stop)
        super().setUp()
        from app.services.tenant_auth import TenantAuth
        throttle = TenantAuth.throttle
        prefix = f"bulk-test:{uuid4()}:"

        def isolated_throttle(auth, bucket, limit=20):
            return throttle(auth, prefix + bucket, limit)

        self.stack.enter_context(patch.object(TenantAuth, "throttle", autospec=True, side_effect=isolated_throttle))

    def start_job(self, cookies, kind, content, key=None):
        return self.client.post(
            f"/bulk/jobs/{kind}?client_key={key or uuid4()}",
            content=content,
            headers={**self.headers(cookies), "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        )

    def team_login(self, owner, cookies, role):
        email = f"bulk-{role}-{self.suffix}@example.com"
        password = "Team test password 123!"
        self.use_cookies(cookies)
        created = self.client.post("/auth/team", json={
            "display_name": role, "email": email, "password": password, "role": role,
        }, headers=self.headers(cookies))
        self.assertEqual(created.status_code, 201, created.text)
        self.client.cookies.clear()
        login = self.client.post("/auth/login", json={"email": email, "password": password}, headers={
            "Origin": "http://localhost", "X-Tenant-Slug": owner["user"]["tenant_slug"],
        })
        self.assertEqual(login.status_code, 200, login.text)
        return dict(self.client.cookies)

    def test_tenant_user_scope_roles_templates_exports_and_jobs(self):
        owner, cookies_a, _ = self.register("bulk-scope-a")
        admin_cookies = self.team_login(owner, cookies_a, "admin")
        staff_cookies = self.team_login(owner, cookies_a, "staff")
        viewer_cookies = self.team_login(owner, cookies_a, "viewer")
        self.use_cookies(cookies_a)
        source = workbook("brands", [{"name": "Scoped Alpha " + self.suffix}])
        key = uuid4()
        started = self.start_job(cookies_a, "brands", source, key)
        self.assertEqual(started.status_code, 200, started.text)
        job_a = started.json()["id"]
        done = self.client.post(f"/bulk/jobs/{job_a}/advance", headers=self.headers(cookies_a))
        self.assertEqual(done.status_code, 200, done.text)
        result = self.client.get(f"/bulk/jobs/{job_a}/results")
        self.assertEqual(result.status_code, 200, result.text)
        with ZipFile(io.BytesIO(result.content)) as archive:
            brand = read_workbook("brands", archive.read("success.xlsx"))[0]
        exported = self.client.post("/bulk/exports/brands", json={"ids": [brand["id"]]}, headers=self.headers(cookies_a))
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertEqual(read_workbook("brands", exported.content)[0]["name"], brand["name"])
        template = self.client.get("/bulk/templates/products")
        self.assertEqual(template.status_code, 200, template.text)
        product_book = load_workbook(io.BytesIO(template.content))
        self.assertIn(brand["name"], [cell.value for cell in product_book["Suggestions"]["A"]])
        data = product_book["Data"]
        data["B2"] = "Valid generated formulas"
        data["E2"] = brand["name"]
        generated = self.start_job(cookies_a, "products", save_book(product_book))
        self.assertEqual(generated.status_code, 200, generated.text)
        formula = data["F2"].value
        data["F2"] = formula.replace("$E2", "$E3")
        self.assertEqual(self.start_job(cookies_a, "products", save_book(product_book)).status_code, 422)
        data["F2"] = None
        data["F3"] = formula
        self.assertEqual(self.start_job(cookies_a, "products", save_book(product_book)).status_code, 422)
        self.assertEqual(self.start_job(cookies_a, "brands", b"not a workbook").status_code, 422)

        self.use_cookies(admin_cookies)
        self.assertEqual(self.client.get("/bulk/jobs").json()["items"], [])
        self.assertEqual(self.client.get(f"/bulk/jobs/{job_a}/results").status_code, 404)
        self.assertEqual(self.client.post(f"/bulk/jobs/{job_a}/advance", headers=self.headers(admin_cookies)).status_code, 404)
        self.assertEqual(self.client.delete(f"/bulk/jobs/{job_a}", headers=self.headers(admin_cookies)).status_code, 404)
        admin_job = self.start_job(admin_cookies, "brands", source, key)
        self.assertEqual(admin_job.status_code, 200, admin_job.text)
        self.assertNotEqual(admin_job.json()["id"], job_a)
        self.assertEqual(self.client.post("/bulk/exports/brands", json={"ids": [brand["id"]]}, headers=self.headers(admin_cookies)).status_code, 200)

        for cookies in (staff_cookies, viewer_cookies):
            self.use_cookies(cookies)
            for response in (
                self.client.get("/bulk/templates/brands"),
                self.client.get("/bulk/jobs"),
                self.client.get(f"/bulk/jobs/{job_a}/results"),
                self.client.post("/bulk/exports/brands", json={"ids": [brand["id"]]}, headers=self.headers(cookies)),
                self.start_job(cookies, "brands", source),
                self.client.post(f"/bulk/jobs/{job_a}/advance", headers=self.headers(cookies)),
                self.client.delete(f"/bulk/jobs/{job_a}", headers=self.headers(cookies)),
            ):
                self.assertEqual(response.status_code, 403, response.text)

        self.client.cookies.clear()
        _, cookies_b, _ = self.register("bulk-scope-b")
        self.assertEqual(self.client.get("/bulk/jobs").json()["items"], [])
        template_b = self.client.get("/bulk/templates/products")
        self.assertEqual(template_b.status_code, 200, template_b.text)
        self.assertNotIn(brand["name"], [cell.value for cell in load_workbook(io.BytesIO(template_b.content))["Suggestions"]["A"]])
        foreign = self.client.post("/bulk/exports/brands", json={"ids": [brand["id"]]}, headers=self.headers(cookies_b))
        self.assertEqual(foreign.status_code, 404, foreign.text)
        for response in (
            self.client.get(f"/bulk/jobs/{job_a}/results"),
            self.client.post(f"/bulk/jobs/{job_a}/advance", headers=self.headers(cookies_b)),
            self.client.delete(f"/bulk/jobs/{job_a}", headers=self.headers(cookies_b)),
        ):
            self.assertEqual(response.status_code, 404, response.text)
        other = self.start_job(cookies_b, "brands", source, key)
        self.assertEqual(other.status_code, 200, other.text)
        self.assertNotEqual(other.json()["id"], job_a)

    def test_chunk_recovery_failure_retry_expiry_and_delete(self):
        owner, cookies, _ = self.register("bulk-recover")
        headers = self.headers(cookies)
        key = uuid4()
        names = [f"Recovery {self.suffix} {i}" for i in range(4)]
        content = workbook("brands", [
            {"name": names[0]}, {"name": " "}, {"name": names[1]}, {"name": names[2]}, {"name": names[3]},
        ])
        start = self.start_job(cookies, "brands", content, key)
        self.assertEqual(start.status_code, 200, start.text)
        job = start.json()["id"]
        self.assertEqual(self.start_job(cookies, "brands", content, key).json()["id"], job)
        conflict = self.start_job(cookies, "brands", workbook("brands", [{"name": "Different"}]), key)
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(self.start_job(cookies, "categories", workbook("categories", [{"name": "Different"}]), key).status_code, 409)
        self.assertEqual(self.client.get(f"/bulk/jobs/{job}/results").status_code, 409)
        first = self.client.post(f"/bulk/jobs/{job}/advance", headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual((first.json()["processed"], first.json()["total"], first.json()["completed"]), (3, 5, False))
        self.assertEqual(self.client.get(f"/bulk/jobs/{job}/results").status_code, 409)
        listing = self.client.get("/bulk/jobs").json()["items"]
        self.assertEqual(next(row for row in listing if row["id"] == job)["processed"], 3)
        final = self.client.post(f"/bulk/jobs/{job}/advance", headers=headers)
        self.assertEqual(final.status_code, 200, final.text)
        self.assertEqual((final.json()["processed"], final.json()["completed"]), (5, True))
        repeat = self.client.post(f"/bulk/jobs/{job}/advance", headers=headers)
        self.assertEqual((repeat.status_code, repeat.json()["processed"]), (200, 5))
        report = self.client.get(f"/bulk/jobs/{job}/results")
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual((report.headers["x-bulk-success-count"], report.headers["x-bulk-failure-count"]), ("4", "1"))
        with ZipFile(io.BytesIO(report.content)) as archive:
            success = read_workbook("brands", archive.read("success.xlsx"))
            failure_book = load_workbook(io.BytesIO(archive.read("failure.xlsx")))
        self.assertEqual({row["name"] for row in success}, set(names))
        failure_book["Data"]["B2"] = f"Retry {self.suffix}"
        retry = self.start_job(cookies, "brands", save_book(failure_book))
        self.assertEqual(retry.status_code, 200, retry.text)
        retry_id = retry.json()["id"]
        retried = self.client.post(f"/bulk/jobs/{retry_id}/advance", headers=headers)
        self.assertTrue(retried.json()["completed"], retried.text)
        retry_report = self.client.get(f"/bulk/jobs/{retry_id}/results")
        self.assertEqual((retry_report.headers["x-bulk-success-count"], retry_report.headers["x-bulk-failure-count"]), ("1", "0"))
        with self.factory() as db:
            db.info["tenant_context"] = owner["user"]
            count = db.execute(text("select count(*) from brands where company_id=:company and name in :names")
                               .bindparams(bindparam("names", expanding=True)),
                               {"company": owner["user"]["company_id"], "names": names}).scalar_one()
            self.assertEqual(count, 4)
            db.execute(text("update bulk_import_jobs set expires_at=now()-interval '1 second' where id=:id"), {"id": retry_id})
            db.commit()
        self.assertEqual(self.client.get(f"/bulk/jobs/{retry_id}/results").status_code, 404)
        self.assertEqual(self.client.post(f"/bulk/jobs/{retry_id}/advance", headers=headers).status_code, 404)
        self.assertEqual(self.client.delete(f"/bulk/jobs/{retry_id}", headers=headers).status_code, 404)
        self.assertNotIn(retry_id, [item["id"] for item in self.client.get("/bulk/jobs").json()["items"]])
        self.assertEqual(self.client.delete(f"/bulk/jobs/{job}", headers=headers).status_code, 200)
        self.assertEqual(self.client.get(f"/bulk/jobs/{job}/results").status_code, 404)
        self.assertEqual(self.client.delete(f"/bulk/jobs/{job}", headers=headers).status_code, 404)

