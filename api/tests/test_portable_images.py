import hashlib
import io
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.migrate_product_images import copy_images
from app.services.object_storage import FileStore, PUBLIC_BUCKET, S3ImageStorage, image_storage


class PortableImageTests(unittest.TestCase):
    def test_existing_external_url_is_not_rewritten(self):
        self.assertEqual(FileStore(None).product_image(str(uuid4()), "https://example.test/photo.png"),
                         ("https://example.test/photo.png", None))

    def test_portable_reference_is_validated_against_owner(self):
        company, other, image = str(uuid4()), str(uuid4()), str(uuid4())
        db = MagicMock()
        db.execute.return_value.first.return_value = (image,)
        source = f"/api/public-images/{company}/{image}"
        self.assertEqual(FileStore(db).image(company, source), source)
        with self.assertRaises(HTTPException):
            FileStore(db).image(other, source)
        db.execute.return_value.first.return_value = None
        with self.assertRaises(HTTPException):
            FileStore(db).image(company, source)

    def test_s3_put_and_read_verify_content(self):
        storage = S3ImageStorage.__new__(S3ImageStorage)
        storage.bucket = "fixture"
        storage.client = MagicMock()
        content = b"example-image"
        storage.client.get_object.return_value = {"Body": io.BytesIO(content)}
        company = str(uuid4())
        result = storage.put_verified(company, content, "image/png", public=True, kind="image")
        self.assertEqual(result["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(storage.client.put_object.call_args.kwargs["Key"], PUBLIC_BUCKET + "/" + result["object_path"])
        storage.client.get_object.return_value = {"Body": io.BytesIO(b"wrong")}
        with self.assertRaises(HTTPException):
            storage.put_verified(company, content, "image/png", public=True, kind="image")

    def test_copy_verifies_source_and_destination_without_deleting(self):
        content = b"image"
        digest = hashlib.sha256(content).hexdigest()
        company = str(uuid4())
        path = f"{company}/image-{digest}.png"
        row = dict(company_id=company, bucket=PUBLIC_BUCKET, object_path=path,
                   mime_type="image/png", file_size=len(content), sha256=digest)
        db, source, destination = MagicMock(), MagicMock(), MagicMock()
        db.execute.return_value.mappings.return_value = [row]
        source.read.return_value = content
        destination.put_verified.return_value = {"object_path": path, "sha256": digest}
        self.assertEqual(copy_images(db, source, destination), 1)
        source.read.assert_not_called()
        self.assertEqual(copy_images(db, source, destination, apply=True), 1)
        source.read.assert_called_once_with(PUBLIC_BUCKET, path)
        source.read.return_value = b"corrupt"
        with self.assertRaisesRegex(RuntimeError, "Source image verification"):
            copy_images(db, source, destination, apply=True)
        source.read.return_value = content
        destination.put_verified.return_value = {"object_path": "different", "sha256": digest}
        with self.assertRaisesRegex(RuntimeError, "Destination image path or checksum"):
            copy_images(db, source, destination, apply=True)
        source.delete.assert_not_called()
        destination.delete.assert_not_called()

    def test_s3_reports_permission_errors(self):
        from botocore.exceptions import ClientError

        storage = S3ImageStorage.__new__(S3ImageStorage)
        storage.bucket = "fixture"
        storage.client = MagicMock()
        storage.client.get_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GetObject")
        with self.assertRaises(HTTPException) as error:
            storage.read(PUBLIC_BUCKET, f"{uuid4()}/image.png")
        self.assertEqual(error.exception.status_code, 503)

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(HTTPException):
            image_storage("not-a-provider")

    def test_public_route_serves_only_scoped_public_images(self):
        from app.main import app

        route = next(route for route in app.routes if getattr(route, "path", "") == "/api/public-images/{company_id}/{file_id}")
        db, storage = MagicMock(), MagicMock()
        db.info = {}
        db.execute.return_value.mappings.return_value.first.return_value = {
            "bucket": PUBLIC_BUCKET, "object_path": "object", "mime_type": "image/png",
        }
        storage.read.return_value = b"image"
        company, image = uuid4(), uuid4()
        with patch("app.main.SessionLocal") as factory, patch("app.main.image_storage", return_value=storage):
            factory.return_value.__enter__.return_value = db
            response = route.endpoint(company, image)
            self.assertEqual(response.body, b"image")
            self.assertIn("immutable", response.headers["cache-control"])
            self.assertEqual(db.info["tenant_context"]["company_id"], str(company))
            query, params = db.execute.call_args.args
            self.assertIn("f.file_kind='image'", str(query))
            self.assertEqual(params["bucket"], PUBLIC_BUCKET)
            db.execute.return_value.mappings.return_value.first.return_value = None
            storage.reset_mock()
            with self.assertRaises(HTTPException) as error:
                route.endpoint(company, image)
            self.assertEqual(error.exception.status_code, 404)
            storage.read.assert_not_called()

    def test_public_image_request_needs_no_tenant_header(self):
        from fastapi.testclient import TestClient
        from app.main import app

        db, storage = MagicMock(), MagicMock()
        db.info = {}
        db.execute.return_value.mappings.return_value.first.return_value = {
            "bucket": PUBLIC_BUCKET, "object_path": "object", "mime_type": "image/png",
        }
        storage.read.return_value = b"image"
        with patch("app.main.SessionLocal") as factory, patch("app.main.image_storage", return_value=storage):
            factory.return_value.__enter__.return_value = db
            response = TestClient(app).get(f"/api/public-images/{uuid4()}/{uuid4()}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.content, b"image")


if __name__ == "__main__":
    unittest.main()
