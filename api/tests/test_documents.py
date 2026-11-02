import base64
import unittest
from unittest.mock import MagicMock

from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.documents import AttachmentCreate, AttachmentUpload, MAX_FILE_BYTES
from app.services.documents_service import DocumentsService


def encoded(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


class AttachmentValidationTests(unittest.TestCase):
    def test_allowed_pdf_and_image_types(self):
        for name, mime, content in [
            ("bill.pdf", "application/pdf", b"%PDF-1.4\nexample"),
            ("receipt.jpg", "image/jpeg", b"\xff\xd8\xffexample"),
            ("receipt.png", "image/png", b"\x89PNG\r\n\x1a\nexample"),
            ("receipt.webp", "image/webp", b"RIFF0000WEBPexample"),
        ]:
            self.assertEqual(AttachmentCreate(file_name=name, mime_type=mime, data_base64=encoded(content)).file_name, name)

    def test_filename_is_sanitized(self):
        item = AttachmentCreate(file_name="..\\private\\bill\r\n.pdf", mime_type="application/pdf", data_base64=encoded(b"%PDF-1.4"))
        self.assertEqual(item.file_name, "bill.pdf")

    def test_invalid_or_disguised_files_rejected(self):
        for name, mime, content in [("bill.pdf", "application/pdf", b"<html>not a PDF"),
                                    ("bill.exe", "application/pdf", b"%PDF-1.4"),
                                    ("receipt.webp", "image/webp", b"RIFF0000FAKE")]:
            with self.assertRaises(ValidationError):
                AttachmentCreate(file_name=name, mime_type=mime, data_base64=encoded(content))

    def test_invalid_encoding_and_oversized_file_rejected(self):
        for value in ["not base64!", encoded(b"%PDF-" + b"x" * MAX_FILE_BYTES)]:
            with self.assertRaises(ValidationError):
                AttachmentCreate(file_name="bill.pdf", mime_type="application/pdf", data_base64=value)

    def test_attachment_count_limit(self):
        item = dict(file_name="bill.pdf", mime_type="application/pdf", data_base64=encoded(b"%PDF-1.4"))
        with self.assertRaises(ValidationError):
            AttachmentUpload(items=[item] * 6)


class AttachmentStorageTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.service = DocumentsService(self.db)
        self.service._assert_entity = MagicMock()
        self.file = AttachmentCreate(file_name="bill.pdf", mime_type="application/pdf", data_base64=encoded(b"%PDF-1.4"))

    def test_existing_file_count_limit(self):
        self.service.list_attachments = MagicMock(return_value={"items": [{"file_size": 10}] * 5})
        with self.assertRaises(HTTPException) as error:
            self.service.add_attachments("purchase", "record", "company", [self.file])
        self.assertEqual(error.exception.status_code, 422)
        self.db.execute.assert_not_called()

    def test_total_size_limit(self):
        self.service.list_attachments = MagicMock(return_value={"items": [{"file_size": 20 * 1024 * 1024}]})
        with self.assertRaises(HTTPException):
            self.service.add_attachments("purchase", "record", "company", [self.file])
        self.db.execute.assert_not_called()

    def test_attachment_storage_leaves_commit_to_parent(self):
        self.service.list_attachments = MagicMock(return_value={"items": []})
        self.db.execute.return_value.mappings.return_value.one.return_value = {"id": "document", "file_name": "bill.pdf"}
        result = self.service.add_attachments("business_payment", "record", "company", [self.file])
        self.assertEqual(result[0]["file_name"], "bill.pdf")
        self.db.commit.assert_not_called()
        self.service._assert_entity.assert_called_once_with("business_payment", "record", "company", lock=True)

    def test_unavailable_document_returns_not_found(self):
        self.db.execute.return_value.mappings.return_value.first.return_value = None
        with self.assertRaises(HTTPException) as error:
            self.service.download("document", "other-company")
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(self.db.execute.call_args.args[1]["company_id"], "other-company")


if __name__ == "__main__":
    unittest.main()