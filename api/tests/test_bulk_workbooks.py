import io
import base64
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4
from zipfile import ZipFile

from fastapi import HTTPException
from openpyxl import load_workbook
from PIL import Image

from app.schemas.inventory import ProductInput
from app.services.bulk_import import BulkImport, _image_url
from app.services.bulk_workbooks import read_workbook, workbook
from test_tenancy import TenantDatabaseCase


class BulkWorkbookTests(unittest.TestCase):
    def test_bulk_image_urls_require_public_https_or_existing_tenali_paths(self):
        for value in ("http://example.com/p.png", "https://127.0.0.1/p.png", "https://192.168.1.1/p.png",
                      "https://[::1]/p.png", "https://224.0.0.1/p.png", "https://localhost/p.png",
                      "https://shop.local/p.png", "https://user:pass@example.com/p.png", "https://",
                      "https://127.1/p.png", "https://example.com:bad/p.png", "//example.com/p.png", 123):
            with self.subTest(value=value), self.assertRaises(HTTPException):
                _image_url(value)
        for value in ("https://images.example.com/p.png", "https://8.8.8.8/p.png",
                      f"/api/public-images/{uuid4()}/{uuid4()}", "/api/catalog-assets/photo.png"):
            self.assertEqual(_image_url(value), value)
        service = object.__new__(BulkImport)
        service.inventory = MagicMock()
        service.inventory.detail.return_value = {"variants": []}
        with self.assertRaises(HTTPException):
            service.product({"name": "Bad URL", "image_url": "http://example.com/p.png"})
        with self.assertRaises(HTTPException):
            service.variant({"product_id": str(uuid4()), "variant_name": "Bad URL",
                             "image_url": "https://127.0.0.1/p.png"})
        service.inventory.save_product.assert_not_called()
        service.inventory.save_variant.assert_not_called()

    def test_product_template_autofills_related_fields_without_importing_empty_rows(self):
        content = workbook("products", lookups={
            "brands": ["Acme"], "brand_descriptions": ["Handmade"],
            "hsn": ["0418"], "hsn_descriptions": ["Goods"], "hsn_gst_rates": [0],
        })
        book = load_workbook(io.BytesIO(content))
        data = book["Data"]
        self.assertEqual(data["I2"].data_type, "f")
        self.assertIn("$H2", data["I2"].value)
        self.assertIn("$H2001", data["J2001"].value)
        self.assertIn("$E2", data["F2"].value)
        self.assertEqual(book["References"]["D2"].value, "0418")
        self.assertEqual(book["References"]["F2"].value, 0)
        self.assertEqual(data["H2"].number_format, "@")
        self.assertNotEqual(data["H1"].fill.fgColor.rgb, data["I1"].fill.fgColor.rgb)
        self.assertEqual(read_workbook("products", content), [])
        data["I2"] = data["I2"].value.replace("References!", "'References'!")
        data["B2"] = "Cup"
        data["H2"] = "0418"
        output = io.BytesIO()
        book.save(output)
        row = read_workbook("products", output.getvalue())[0]
        self.assertEqual(row["hsn_code"], "0418")
        self.assertIsNone(row["gst_rate"])
        self.assertIsNone(row["hsn_description"])

    def test_autofill_allows_literals_but_rejects_modified_and_misplaced_formulas(self):
        book = load_workbook(io.BytesIO(workbook("products")))
        sheet = book["Data"]
        sheet["B2"] = "New HSN product"
        sheet["H2"] = "1234"
        sheet["I2"] = "New goods"
        sheet["J2"] = 18
        output = io.BytesIO()
        book.save(output)
        self.assertEqual(read_workbook("products", output.getvalue())[0]["gst_rate"], 18)
        sheet["I2"] = '=HYPERLINK("https://example.com","bad")'
        output = io.BytesIO()
        book.save(output)
        with self.assertRaisesRegex(HTTPException, "Formulas"):
            read_workbook("products", output.getvalue())
        sheet["I2"] = None
        sheet["B2"] = sheet["F2"].value
        output = io.BytesIO()
        book.save(output)
        with self.assertRaisesRegex(HTTPException, "Formulas"):
            read_workbook("products", output.getvalue())

    def test_template_has_fresh_suggestions_sample_and_free_text_validation(self):
        content = workbook("products", lookups={"brands": ["Acme", "New brand"], "booleans": ["TRUE", "FALSE"]})
        book = load_workbook(io.BytesIO(content))
        self.assertEqual(read_workbook("products", content), [])
        self.assertEqual(book["Suggestions"]["A2"].value, "Acme")
        self.assertTrue(any(cell.value == "Sample product" for row in book["README"] for cell in row))
        self.assertEqual(book["Suggestions"].sheet_state, "hidden")
        rules = book["Data"].data_validations.dataValidation
        self.assertTrue(any("INDIRECT" in rule.formula1 and not rule.showErrorMessage for rule in rules))

    def test_failure_report_round_trips_as_retry_and_keeps_strings_as_text(self):
        content = workbook("parties", [{"legal_name": "=2+2", "party_type": "vendor",
                                        "failure_reason": "Check name"}], reasons=True)
        book = load_workbook(io.BytesIO(content))
        self.assertEqual(book["Data"]["C2"].data_type, "s")
        row = read_workbook("parties", content)[0]
        self.assertEqual(row["legal_name"], "=2+2")
        self.assertNotIn("failure_reason", row)

    def test_rejects_formula_and_invalid_files(self):
        book = load_workbook(io.BytesIO(workbook("hsn")))
        book["Data"]["B2"] = "=1+1"
        stream = io.BytesIO()
        book.save(stream)
        with self.assertRaisesRegex(HTTPException, "Formulas"):
            read_workbook("hsn", stream.getvalue())
        with self.assertRaises(HTTPException):
            read_workbook("hsn", b"not an xlsx")

    def test_rejects_xml_entities_in_uploaded_workbook(self):
        source = io.BytesIO(workbook("hsn", [{"code": "1234"}]))
        poisoned = io.BytesIO()
        with ZipFile(source) as incoming, ZipFile(poisoned, "w") as outgoing:
            for entry in incoming.infolist():
                data = incoming.read(entry)
                if entry.filename == "xl/worksheets/sheet1.xml":
                    data = b'<!DOCTYPE worksheet [<!ENTITY payload "1234">]>' + data.replace(b"1234", b"&payload;")
                outgoing.writestr(entry, data)
        with self.assertRaises(HTTPException):
            read_workbook("hsn", poisoned.getvalue())

    def test_product_creates_dependencies_and_maps_vendor_in_one_row(self):
        service = object.__new__(BulkImport)
        service.company_id = str(uuid4())
        service.inventory = MagicMock()
        brand, category, vendor, product = (str(uuid4()) for _ in range(4))
        service._lookup = MagicMock(side_effect=[brand, category])
        service._hsn = MagicMock()
        service._vendor = MagicMock(return_value=vendor)
        saved = {**ProductInput(name="Sample").model_dump(), "id": product, "image_urls": "", "offers": []}
        service.inventory.save_product.return_value = saved
        service.inventory.save_offer.return_value = saved
        result = service.product({"name": "Sample", "brand": "New", "brand_description": "Details",
                                  "categories": "Home", "hsn_code": "1234", "hsn_description": "Goods",
                                  "gst_rate": 18, "vendor": "Supplier"})
        self.assertEqual(result, product)
        first = service.inventory.save_product.call_args_list[0].args[0]
        self.assertEqual(str(first.brand_id), brand)
        self.assertEqual([str(value) for value in first.category_ids], [category])
        self.assertEqual(first.hsn_code, "1234")
        self.assertEqual(str(service.inventory.save_product.call_args_list[1].args[0].preferred_vendor_id), vendor)
        service._hsn.assert_called_once_with("1234", "Goods", 18)
        service.inventory.save_offer.assert_called_once()

    def test_invalid_nonempty_id_does_not_create_a_record(self):
        service = object.__new__(BulkImport)
        service.inventory = MagicMock()
        with self.assertRaises(HTTPException):
            service.product({"id": 0, "name": "Bad id"})
        service.inventory.save_product.assert_not_called()

    def test_import_response_contains_separate_retryable_workbooks(self):
        from app.api.routes.bulk import result_package
        response = result_package("hsn", [{"id": str(uuid4()), "code": "1234"}],
                                  [{"code": "5678", "failure_reason": "Missing rate"}], {}, {})
        self.assertEqual(response.headers["x-bulk-success-count"], "1")
        with ZipFile(io.BytesIO(response.body)) as archive:
            self.assertEqual(set(archive.namelist()), {"success.xlsx", "failure.xlsx"})
            self.assertEqual(read_workbook("hsn", archive.read("failure.xlsx"))[0]["code"], "5678")

    def test_image_zip_returns_retryable_failures_with_their_files(self):
        from app.api.routes.bulk import image_upload, result_package
        image = io.BytesIO()
        Image.new("RGB", (10, 10), "red").save(image, format="PNG")
        row = {"id": str(uuid4()), "entity": "brand", "image_file": "photo.png"}
        package = io.BytesIO()
        with ZipFile(package, "w") as archive:
            archive.writestr("manifest.xlsx", workbook("images", [row]))
            archive.writestr("images/photo.png", image.getvalue())
        rows, images = image_upload(package.getvalue())
        response = result_package("images", [], [{**rows[0], "failure_reason": "Try again"}], images, {})
        retry_rows, files = image_upload(response.body)
        self.assertEqual(retry_rows[0]["image_file"], "photo.png")
        self.assertEqual(files["photo.png"], image.getvalue())

    def test_product_zip_uses_image_file_and_failure_package_is_retryable(self):
        from app.api.routes.bulk import image_upload, result_package
        image = io.BytesIO()
        Image.new("RGBA", (10, 10), (255, 0, 0, 128)).save(image, format="PNG")
        row = {"name": "Sample", "image_file": "photo.png"}
        package = io.BytesIO()
        with ZipFile(package, "w") as archive:
            archive.writestr("manifest.xlsx", workbook("products", [row]))
            archive.writestr("images/photo.png", image.getvalue())
        service = object.__new__(BulkImport)
        service.inventory = MagicMock()
        service.inventory.save_product.return_value = {"id": str(uuid4())}
        service.product(row, {"photo.png": image.getvalue()})
        self.assertTrue(service.inventory.save_product.call_args.args[0].image_url.startswith("data:image/png;base64,"))
        with self.assertRaisesRegex(HTTPException, "either"):
            service.product({**row, "image_url": "https://example.com/image.png"}, {"photo.png": image.getvalue()})
        rows, images = image_upload(package.getvalue(), "products")
        response = result_package("products", [], [{**rows[0], "failure_reason": "Try again"}], images, {})
        retry_rows, files = image_upload(response.body, "products")
        self.assertEqual(retry_rows[0]["image_file"], "photo.png")
        self.assertEqual(files["photo.png"], image.getvalue())

    def test_image_zip_rejects_unexpected_paths(self):
        from app.api.routes.bulk import image_upload
        package = io.BytesIO()
        with ZipFile(package, "w") as archive:
            archive.writestr("manifest.xlsx", workbook("images"))
            archive.writestr("images/../../outside.png", b"bad")
        with self.assertRaises(HTTPException):
            image_upload(package.getvalue())

    def test_ai_catalog_download_produces_importable_package_with_cropped_image(self):
        from app.ai.catalog_workbook import CatalogOutput, catalog_answer, download_catalog
        image = io.BytesIO()
        Image.new("RGB", (40, 40), "red").save(image, format="JPEG")
        row = dict.fromkeys(("sku", "description", "brand", "categories", "hsn_code", "hsn_description",
                             "gst_rate", "vendor", "labels", "selling_price", "image_background"), None)
        row.update(name="Cup", image_index=0, image_box="0,0,1000,1000")
        reply = CatalogOutput.model_validate({"reply": "Review before upload.", "clarification": None, "products": [row]})
        assistant = MagicMock()
        assistant.scope = {"company": str(uuid4()), "user": str(uuid4())}
        assistant.identity = {"role": "owner"}
        assistant.db.execute.return_value.mappings.return_value.first.return_value = {
            "content": catalog_answer(reply), "attachment_ids": [uuid4()]}
        with patch("app.ai.capabilities.current_identity", return_value={"role": "owner"}), \
                patch("app.ai.catalog_workbook.MediaService") as media, \
                patch("app.ai.catalog_workbook.BulkImport") as bulk:
            media.return_value.attachments.return_value = [{"mime_type": "image/jpeg", "content": image.getvalue()}]
            bulk.return_value.suggestions.return_value = {}
            package = download_catalog(assistant, uuid4(), uuid4())
        with ZipFile(io.BytesIO(package)) as archive:
            readme = load_workbook(io.BytesIO(archive.read("manifest.xlsx")))["README"]
            self.assertTrue(any(cell.value == "Review before upload." for cells in readme for cell in cells))
        from app.api.routes.bulk import image_upload
        rows, images = image_upload(package, "products")
        self.assertEqual(rows[0]["name"], "Cup")
        self.assertEqual(rows[0]["image_file"], "product-1.jpg")
        self.assertIn("product-1.jpg", images)

    def test_ai_catalog_uses_numbered_photo_panels_not_estimated_grid_coordinates(self):
        from PIL import ImageDraw
        from app.ai.catalog_workbook import CATALOG_INSTRUCTIONS, CatalogOutput, catalog_answer, download_catalog
        from app.ai.provider import OpenAIProvider
        source = Image.new("RGB", (1000, 700), "white")
        draw = ImageDraw.Draw(source)
        centers = []
        for index in range(10):
            left, top = 12 + index % 5 * 115, 12 + index // 5 * 260
            for y in range(100):
                draw.line((left, top + y, left + 99, top + y),
                          fill=(40 + 2 * y, 35 + index * 4 + y, 25 + index * 5 + y // 2))
            draw.text((left, top + 115), "Price Rs 1500", fill="black")
            draw.text((left, top + 140), "MRP Rs 2499", fill="gray")
            centers.append(source.getpixel((left + 50, top + 50)))
        image = io.BytesIO()
        source.save(image, format="PNG")
        products = []
        for index in range(10):
            product = dict.fromkeys(("sku", "description", "brand", "categories", "hsn_code", "hsn_description",
                                    "gst_rate", "vendor", "labels", "selling_price", "image_background"), None)
            products.append({**product, "name": f"Product {index + 1}", "image_index": 0,
                             "image_box": f"region:{index + 1}"})
        parsed = CatalogOutput.model_validate({"reply": "Review the images.", "clarification": None, "products": products})
        response = MagicMock(status="completed", id="fixture", output_text=parsed.model_dump_json(),
            usage=MagicMock(input_tokens=100, output_tokens=100, input_tokens_details=MagicMock(cached_tokens=0)))
        with patch("app.ai.provider.OpenAI") as client:
            client.return_value.__enter__.return_value.responses.create.return_value = response
            result = OpenAIProvider().respond(CATALOG_INSTRUCTIONS, "Prepare a product workbook.", {
                "timeout_seconds": 30, "routine_model": "fixture", "max_output_tokens": 2000, "_catalog_mode": True,
                "_attachments": [{"mime_type": "image/png", "content": image.getvalue()}]})
            client.return_value.__enter__.return_value.responses.create.assert_called_once()
            request = client.return_value.__enter__.return_value.responses.create.call_args.kwargs
        blocks = request["input"][0]["content"]
        self.assertTrue(any("region:1" in block.get("text", "") and "region:10" in block.get("text", "")
                            for block in blocks))
        sent_images = [block for block in blocks if block["type"] == "input_image"]
        self.assertEqual(len(sent_images), 1)
        with Image.open(io.BytesIO(base64.b64decode(sent_images[0]["image_url"].split(",", 1)[1]))) as sent:
            self.assertLessEqual(max(sent.size), 1024)
            self.assertNotEqual(sent.getpixel((12, 12)), source.getpixel((12, 12)))
        self.assertIsNone(result.error)
        assistant = MagicMock()
        assistant.scope = {"company": str(uuid4()), "user": str(uuid4())}
        assistant.identity = {"role": "owner"}
        saved = {"content": result.output.reply, "attachment_ids": [uuid4()]}
        assistant.db.execute.return_value.mappings.return_value.first.return_value = saved
        with patch("app.ai.capabilities.current_identity", return_value={"role": "owner"}), \
                patch("app.ai.catalog_workbook.MediaService") as media, \
                patch("app.ai.catalog_workbook.BulkImport") as bulk:
            media.return_value.attachments.return_value = [{"mime_type": "image/png", "content": image.getvalue()}]
            bulk.return_value.suggestions.return_value = {}
            package = download_catalog(assistant, uuid4(), uuid4())
            with ZipFile(io.BytesIO(package)) as archive:
                rows = read_workbook("products", archive.read("manifest.xlsx"))
                self.assertEqual(len(rows), 10)
                self.assertEqual(len([name for name in archive.namelist() if name.startswith("images/")]), 10)
                for index, row in enumerate(rows):
                    self.assertEqual(row["image_file"], f"product-{index + 1}.jpg")
                    with Image.open(io.BytesIO(archive.read("images/" + row["image_file"]))) as crop:
                        self.assertTrue(98 <= crop.width <= 106 and 98 <= crop.height <= 106, crop.size)
                        actual = crop.getpixel((crop.width // 2, crop.height // 2))
                        self.assertLess(max(abs(a - b) for a, b in zip(actual, centers[index])), 8)
            for invalid in ("16,16,140,202", "region:0", "region:11", "region:bad"):
                parsed.products[0].image_box = invalid
                saved["content"] = catalog_answer(parsed)
                with self.subTest(box=invalid), self.assertRaisesRegex(HTTPException, "Regenerate"):
                    download_catalog(assistant, uuid4(), uuid4())

    def test_ai_catalog_rejects_bad_image_reference_and_non_admin(self):
        from app.ai.catalog_workbook import CatalogOutput, catalog_answer, download_catalog
        row = dict.fromkeys(("sku", "description", "brand", "categories", "hsn_code", "hsn_description",
                             "gst_rate", "vendor", "labels", "selling_price", "image_background"), None)
        row.update(name="Cup", image_index=1, image_box="0,0,1000,1000")
        parsed = CatalogOutput.model_validate({"reply": "Review.", "clarification": None, "products": [row]})
        assistant = MagicMock()
        assistant.scope = {"company": str(uuid4()), "user": str(uuid4())}
        assistant.identity = {"role": "owner"}
        assistant.db.execute.return_value.mappings.return_value.first.return_value = {
            "content": catalog_answer(parsed), "attachment_ids": []}
        with patch("app.ai.capabilities.current_identity", return_value={"role": "owner"}), \
                patch("app.ai.catalog_workbook.MediaService") as media:
            media.return_value.attachments.return_value = []
            with self.assertRaisesRegex(HTTPException, "unavailable image"):
                download_catalog(assistant, uuid4(), uuid4())
        with patch("app.ai.capabilities.current_identity", return_value={"role": "staff"}):
            with self.assertRaises(HTTPException) as error:
                download_catalog(assistant, uuid4(), uuid4())
        self.assertEqual(error.exception.status_code, 403)

    def test_ai_catalog_embedded_excel_image_is_metered_and_downloaded(self):
        from openpyxl import Workbook
        from openpyxl.drawing.image import Image as ExcelImage
        from app.ai.catalog_workbook import CatalogOutput, catalog_answer, download_catalog
        from app.ai.media import XLSX_MIME, catalog_assets, normalize_upload
        from app.ai.schemas import AIUpload
        image = io.BytesIO()
        Image.new("RGBA", (30, 30), (255, 0, 0, 128)).save(image, format="PNG")
        image.seek(0)
        book = Workbook()
        book.active["A2"] = "Cup"
        book.active.add_image(ExcelImage(image), "B2")
        data = io.BytesIO()
        book.save(data)
        _, mime, raw, extracted, bound = normalize_upload(AIUpload(file_name="catalog.xlsx", mime_type=XLSX_MIME,
            data_base64=base64.b64encode(data.getvalue()).decode(), catalog_images=True))
        attachment = {"mime_type": mime, "content": raw, "extracted_text": extracted, "input_bound": bound}
        assets = catalog_assets([attachment])
        self.assertEqual(len(assets), 2)
        self.assertIn("row 2, column 2", assets[1]["location"])
        self.assertEqual(bound, len(extracted.encode()) + 512 + 16000)
        row = dict.fromkeys(("sku", "description", "brand", "categories", "hsn_code", "hsn_description",
                             "gst_rate", "vendor", "labels", "selling_price", "image_background"), None)
        row.update(name="Cup", image_index=1, image_box="0,0,1000,1000")
        parsed = CatalogOutput.model_validate({"reply": "Review.", "clarification": None, "products": [row]})
        assistant = MagicMock()
        assistant.scope = {"company": str(uuid4()), "user": str(uuid4())}
        assistant.identity = {"role": "owner"}
        assistant.db.execute.return_value.mappings.return_value.first.return_value = {
            "content": catalog_answer(parsed), "attachment_ids": [uuid4()]}
        with patch("app.ai.capabilities.current_identity", return_value={"role": "owner"}), \
                patch("app.ai.catalog_workbook.MediaService") as media, \
                patch("app.ai.catalog_workbook.BulkImport") as bulk:
            media.return_value.attachments.return_value = [attachment]
            bulk.return_value.suggestions.return_value = {}
            package = download_catalog(assistant, uuid4(), uuid4())
        from app.api.routes.bulk import image_upload
        rows, images = image_upload(package, "products")
        self.assertEqual(rows[0]["image_file"], "product-1.png")
        with Image.open(io.BytesIO(images["product-1.png"])) as result:
            self.assertEqual(result.getpixel((0, 0))[3], 128)
        with self.assertRaisesRegex(HTTPException, "re-upload"):
            catalog_assets([{**attachment, "input_bound": 16000}])

    def test_scanned_pdf_images_can_be_used_as_catalog_assets(self):
        from app.ai.media import catalog_assets, normalize_upload
        from app.ai.schemas import AIUpload
        pdf = io.BytesIO()
        Image.new("RGB", (40, 40), "blue").save(pdf, format="PDF")
        _, mime, raw, extracted, bound = normalize_upload(AIUpload(file_name="catalog.pdf", mime_type="application/pdf",
            data_base64=base64.b64encode(pdf.getvalue()).decode(), catalog_images=True))
        assets = catalog_assets([{"mime_type": mime, "content": raw, "extracted_text": extracted, "input_bound": bound}])
        self.assertEqual(len(assets), 2)
        self.assertEqual(assets[1]["location"], "PDF page 1")
        self.assertIn("no extractable text", extracted)

    def test_bulk_job_commits_record_and_progress_together_and_continues_failures(self):
        from app.api.routes.bulk import advance_job
        job_id = uuid4()
        service = object.__new__(BulkImport)
        service.company_id = str(uuid4())
        service.db = MagicMock()
        service.db.info = {"tenant_context": {"user_id": uuid4()}}
        rows = [{"code": "bad"}, {"code": "1234"}]
        base = {"id": job_id, "kind": "hsn", "rows": rows, "content": b"", "created_at": "now", "expires_at": "later"}
        updates = iter([{**base, "total": 2, "next_row": 1}, {**base, "total": 2, "next_row": 2}])
        service.db.execute.return_value.mappings.return_value.one.side_effect = lambda: next(updates)
        service.hsn = MagicMock(side_effect=[HTTPException(422, "Invalid HSN"), str(uuid4())])
        with patch("app.api.routes.bulk.job_row", side_effect=[{**base, "next_row": 0}, {**base, "next_row": 1}]):
            result = advance_job(job_id, service)
        self.assertTrue(result["completed"])
        self.assertEqual(service.db.commit.call_count, 2)
        service.db.rollback.assert_not_called()
        outcomes = [call.args[1]["outcome"] for call in service.db.execute.call_args_list]
        self.assertIn("Invalid HSN", outcomes[0])
        self.assertIn('"id":', outcomes[1])


class BulkDatabaseTests(TenantDatabaseCase):
    def setUp(self):
        from dotenv import load_dotenv
        load_dotenv("api/.env")
        # The rollback fixture shares one connection; hosting workers must not use it concurrently.
        worker = patch("app.services.domain_onboarding.custom_domains_enabled", return_value=False)
        worker.start()
        self.addCleanup(worker.stop)
        super().setUp()
        from app.services.tenant_auth import TenantAuth
        throttle = TenantAuth.throttle
        prefix = f"bulk-{self.suffix}:"
        isolated = patch.object(TenantAuth, "throttle", autospec=True,
                                side_effect=lambda auth, bucket, limit=20: throttle(auth, prefix + bucket, limit))
        isolated.start()
        self.addCleanup(isolated.stop)

    def test_resumable_jobs_are_idempotent_private_and_return_retryable_rows(self):
        _, cookies, _ = self.register("bulk-a")
        key = str(uuid4())
        content = workbook("brands", [{"name": "First"}, {"name": " "}, {"name": "Second"}, {"name": "Third"}])
        headers = {**self.headers(cookies), "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
        start = self.client.post(f"/bulk/jobs/brands?client_key={key}", content=content, headers=headers)
        self.assertEqual(start.status_code, 200, start.text)
        job_id = start.json()["id"]
        repeat = self.client.post(f"/bulk/jobs/brands?client_key={key}", content=content, headers=headers)
        self.assertEqual(repeat.json()["id"], job_id)
        conflict = self.client.post(f"/bulk/jobs/brands?client_key={key}",
                                    content=workbook("brands", [{"name": "Other"}]), headers=headers)
        self.assertEqual(conflict.status_code, 409)
        first = self.client.post(f"/bulk/jobs/{job_id}/advance", headers=self.headers(cookies))
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["processed"], 3)
        self.assertEqual(self.client.get(f"/bulk/jobs/{job_id}/results").status_code, 409)
        second = self.client.post(f"/bulk/jobs/{job_id}/advance", headers=self.headers(cookies))
        self.assertTrue(second.json()["completed"])
        repeated = self.client.post(f"/bulk/jobs/{job_id}/advance", headers=self.headers(cookies))
        self.assertTrue(repeated.json()["completed"])
        result = self.client.get(f"/bulk/jobs/{job_id}/results")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.headers["x-bulk-success-count"], "3")
        self.assertEqual(result.headers["x-bulk-failure-count"], "1")
        with ZipFile(io.BytesIO(result.content)) as archive:
            self.assertEqual(len(read_workbook("brands", archive.read("success.xlsx"))), 3)
            self.assertEqual(len(read_workbook("brands", archive.read("failure.xlsx"))), 1)
        _, other_cookies, _ = self.register("bulk-b")
        self.assertEqual(self.client.get(f"/bulk/jobs/{job_id}/results").status_code, 404)
        self.assertEqual(self.client.post(f"/bulk/jobs/{job_id}/advance", headers=self.headers(other_cookies)).status_code, 404)
        self.use_cookies(cookies)
        self.assertEqual(self.client.delete(f"/bulk/jobs/{job_id}", headers=self.headers(cookies)).status_code, 200)

    def test_product_dependencies_and_selected_export_round_trip(self):
        _, cookies, _ = self.register("bulk-products")
        headers = self.headers(cookies)
        rows = [
            {"name": "Wooden Cup", "sku": "CUP-1", "brand": "New brand", "brand_description": "Handmade",
             "categories": "Kitchen|Gifts", "hsn_code": "4419", "hsn_description": "Wooden articles",
             "gst_rate": 12, "vendor": "Workshop", "labels": "Featured|New", "selling_price": 100},
            {"name": "Bad", "categories": "Must rollback", "selling_price": -1},
        ]
        response = self.client.post(f"/bulk/jobs/products?client_key={uuid4()}", content=workbook("products", rows),
            headers={**headers, "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["id"]
        processed = self.client.post(f"/bulk/jobs/{job_id}/advance", headers=headers)
        self.assertEqual(processed.status_code, 200, processed.text)
        report = self.client.get(f"/bulk/jobs/{job_id}/results")
        self.assertEqual(report.headers["x-bulk-success-count"], "1", report.content)
        self.assertEqual(report.headers["x-bulk-failure-count"], "1")
        with ZipFile(io.BytesIO(report.content)) as archive:
            success = read_workbook("products", archive.read("success.xlsx"))[0]
            failures = read_workbook("products", archive.read("failure.xlsx"))
        product_id = success["id"]
        self.assertEqual(failures[0]["name"], "Bad")
        lookups = self.client.get("/inventory/lookups").json()
        self.assertNotIn("Must rollback", [row["name"] for row in lookups["categories"]])
        product = self.client.get(f"/inventory/products/{product_id}")
        self.assertEqual(product.status_code, 200, product.text)
        self.assertEqual(len(product.json()["category_ids"]), 2)
        self.assertEqual(set(product.json()["tags"]), {"Featured", "New"})
        self.assertTrue(product.json()["preferred_vendor_id"])
        exported = self.client.post("/bulk/exports/products", json={"ids": [product_id]}, headers=headers)
        self.assertEqual(exported.status_code, 200, exported.text)
        record = read_workbook("products", exported.content)[0]
        self.assertEqual(record["brand"], "New brand")
        self.assertEqual(record["categories"], "Kitchen|Gifts")
        self.assertEqual(record["vendor"], "Workshop")
        self.assertEqual(record["hsn_code"], "4419")
        record["name"] = "Updated cup"
        failures[0]["selling_price"] = 25
        failures[0]["hsn_code"] = "4419"
        retry = self.client.post(f"/bulk/jobs/products?client_key={uuid4()}",
            content=workbook("products", [record, failures[0]]),
            headers={**headers, "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
        self.assertEqual(retry.status_code, 200, retry.text)
        retried = self.client.post(f"/bulk/jobs/{retry.json()['id']}/advance", headers=headers)
        self.assertTrue(retried.json()["completed"], retried.text)
        retry_report = self.client.get(f"/bulk/jobs/{retry.json()['id']}/results")
        with ZipFile(io.BytesIO(retry_report.content)) as archive:
            failures_book = load_workbook(io.BytesIO(archive.read("failure.xlsx")))
            failure_details = list(failures_book["Data"].values)
        self.assertEqual(retry_report.headers["x-bulk-success-count"], "2", failure_details)
        self.assertEqual(retry_report.headers["x-bulk-failure-count"], "0")
        updated = self.client.get(f"/inventory/products/{product_id}").json()
        self.assertEqual(updated["name"], "Updated cup")
        self.assertEqual(len(updated["category_ids"]), 2)


if __name__ == "__main__":
    unittest.main()
