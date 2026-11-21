import unittest
from decimal import Decimal
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.inventory import inventory_service, router
from app.schemas.catalog import CatalogVariantOut
from app.schemas.inventory import VariantImageInput, VariantInput
from app.services.inventory_service import InventoryService


class VariantImageTests(unittest.TestCase):
    def service(self):
        service = object.__new__(InventoryService)
        service.company_id = str(uuid4())
        service.db = Mock()
        service.db.execute.return_value.scalar_one_or_none.return_value = None
        service._product = Mock(return_value={})
        service._variant = Mock(return_value={"image_url": "https://example.test/blue.webp",
                                                "image_original_url": "https://example.test/original.png"})
        service._validate_item = Mock()
        service._write = Mock(return_value="variant")
        service._check_price = Mock()
        service.detail = Mock(return_value={})
        return service

    def test_variant_image_validation_and_catalog_projection(self):
        self.assertIsNone(VariantImageInput(variant_name="Blue").image_url)
        with self.assertRaises(ValidationError):
            VariantImageInput(variant_name="Blue", image_url="javascript:alert(1)")
        output = CatalogVariantOut(id=uuid4(), image_url="https://example.test/blue.webp")
        self.assertEqual(output.model_dump()["image_url"], "https://example.test/blue.webp")

    def test_inventory_http_accepts_upload_and_rejects_bad_image(self):
        app = FastAPI()
        app.include_router(router, prefix="/inventory")
        service = Mock()
        service.save_variant.return_value = {"id": "product"}
        app.dependency_overrides[inventory_service] = lambda: service
        client = TestClient(app)
        path = f"/inventory/products/{uuid4()}/variants"
        response = client.post(path, json={"variant_name": "Blue", "image_url": "https://example.test/blue.png"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(service.save_variant.call_args.args[1].image_url, "https://example.test/blue.png")
        self.assertEqual(client.post(path, json={"variant_name": "Blue", "image_url": "javascript:alert(1)"}).status_code, 422)

    def test_omitted_image_preserves_existing_image(self):
        service = self.service()
        with patch("app.services.inventory_service.FileStore") as store:
            service.save_variant("product", VariantInput(variant_name="Blue"), "variant")
        values = service._write.call_args.args[1]
        self.assertNotIn("image_url", values)
        self.assertNotIn("image_original_url", values)
        store.assert_not_called()
        with patch("app.services.inventory_service.FileStore") as store:
            service.save_variant("product", VariantInput(variant_name="New"))
        self.assertNotIn("image_url", service._write.call_args.args[1])
        store.assert_not_called()

    def test_upload_and_switch_to_parent(self):
        service = self.service()
        with patch("app.services.inventory_service.FileStore") as store:
            store.return_value.product_image.return_value = ("display.webp", "original.png")
            service.save_variant("product", VariantImageInput(variant_name="Blue", image_url="https://example.test/new.png"), "variant")
            self.assertEqual(service._write.call_args.args[1]["image_url"], "display.webp")
            self.assertEqual(service._write.call_args.args[1]["image_original_url"], "original.png")
            store.return_value.product_image.return_value = (None, None)
            service.save_variant("product", VariantImageInput(variant_name="Blue", image_url=None), "variant")
            self.assertIsNone(service._write.call_args.args[1]["image_url"])
            self.assertIsNone(service._write.call_args.args[1]["image_original_url"])

    def test_unchanged_image_keeps_original(self):
        service = self.service()
        with patch("app.services.inventory_service.FileStore") as store:
            service.save_variant("product", VariantImageInput(variant_name="Blue", image_url="https://example.test/blue.webp"), "variant")
        self.assertEqual(service._write.call_args.args[1]["image_original_url"], "https://example.test/original.png")
        store.assert_not_called()

    def test_inventory_stock_query_uses_accessible_stores(self):
        service = self.service()
        store_id = str(uuid4())
        service.db.info = {"tenant_context": {"role": "staff", "store_ids": [store_id]}}
        queries = []

        def execute(query, params):
            sql = str(query)
            queries.append((sql, params))
            result = Mock()
            result.mappings.return_value = []
            return result

        service.db.execute.side_effect = execute
        service._data()
        stock_sql, params = next((sql, params) for sql, params in queries if "sum(quantity) as quantity from stock_balances" in sql)
        self.assertIn("store_id=any(cast(:permitted as uuid[]))", stock_sql)
        self.assertEqual(params["permitted"], [store_id])
        service.db.info["tenant_context"]["store_ids"] = []
        service._data()
        self.assertEqual(queries[-2][1]["permitted"], [])


if __name__ == "__main__":
    unittest.main()
