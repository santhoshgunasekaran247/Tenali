import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.billing import QuotationCreate
from app.services.quotation_service import QuotationService


class QuotationTests(unittest.TestCase):
    def payload(self, **overrides):
        values = {"idempotency_key": "quotation-key", "store_id": str(uuid4()),
                  "customer_party_id": str(uuid4()), "billing_address": "Customer address",
                  "place_of_supply": "33 - Tamil Nadu", "lines": [
                      {"description": "Widget", "hsn": "1234", "quantity": "2", "rate": "100"}]}
        return QuotationCreate(**{**values, **overrides})

    def test_payment_and_invoice_fields_are_rejected(self):
        for field in ("account_id", "amount_received", "payment_mode", "auto_create_receivable"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.payload(**{field: "1"})

    @patch("app.services.quotation_service.finish_posting")
    @patch("app.services.quotation_service.replay_posting", return_value=None)
    @patch("app.services.quotation_service.MastersService")
    @patch("app.services.quotation_service.resolve_product_lines")
    @patch("app.services.quotation_service.get_store")
    def test_creation_saves_only_quotation_and_does_not_change_product_or_stock(
            self, get_store, resolve, masters, replay, finish):
        db = MagicMock()
        db.info = {"tenant_context": {"role": "owner"}}
        payload = self.payload()
        store = {"id": payload.store_id, "code": "MAIN", "address": "Seller address",
                 "gst_number": "33ABCDE1234F1Z5", "state_code": "33"}
        get_store.return_value = store
        customer = {"id": payload.customer_party_id, "legal_name": "Customer", "address": "Customer address", "gst_number": None}
        company = {"company_name": "Seller", "address": "Seller address", "gst_number": "33ABCDE1234F1Z5",
                   "gst_registered": True, "prices_include_gst": True}
        row = {"id": uuid4(), "store_id": payload.store_id, "company_id": uuid4()}
        db.execute.side_effect = [
            MagicMock(mappings=MagicMock(return_value=MagicMock(first=MagicMock(return_value=customer)))),
            MagicMock(mappings=MagicMock(return_value=MagicMock(one=MagicMock(return_value=company)))),
            MagicMock(mappings=MagicMock(return_value=MagicMock(one=MagicMock(return_value=row)))),
        ]
        result = QuotationService(db).create(str(uuid4()), payload)
        resolve.assert_called_once()
        self.assertIs(resolve.call_args.kwargs["persist_hsn"], False)
        masters.return_value.apply_hsn_rates.assert_called_once()
        statements = [str(call.args[0]).lower() for call in db.execute.call_args_list]
        self.assertEqual(len(statements), 3)
        self.assertTrue(statements[-1].lstrip().startswith("insert into quotations"))
        self.assertNotIn("invoice", statements[-1])
        self.assertEqual(result["store_code"], "MAIN")
        self.assertEqual(finish.call_args.args[2], "quotation")
        db.commit.assert_called_once()

    @patch("app.services.quotation_service.replay_posting")
    @patch("app.services.quotation_service.get_store")
    def test_retry_rechecks_store_access_without_writes(self, get_store, replay):
        db = MagicMock()
        payload = self.payload()
        replay.return_value = {"id": str(uuid4()), "store_id": str(payload.store_id)}
        result = QuotationService(db).create(str(uuid4()), payload)
        self.assertEqual(result, replay.return_value)
        self.assertEqual(get_store.call_count, 2)
        db.execute.assert_not_called()
        db.commit.assert_not_called()

    @patch("app.services.quotation_service.replay_posting", return_value=None)
    @patch("app.services.quotation_service.get_store")
    def test_vendor_cannot_be_used_as_customer(self, get_store, replay):
        db = MagicMock()
        db.execute.return_value.mappings.return_value.first.return_value = None
        with self.assertRaises(HTTPException) as error:
            QuotationService(db).create(str(uuid4()), self.payload())
        self.assertEqual(error.exception.status_code, 422)
        db.commit.assert_not_called()

    @patch("app.services.quotation_service.MastersService")
    @patch("app.services.quotation_service.resolve_product_lines")
    @patch("app.services.quotation_service.get_store")
    def test_unregistered_quotation_does_not_require_hsn_or_charge_gst(self, get_store, resolve, masters):
        db = MagicMock()
        payload = self.payload(lines=[{"description": "Widget", "quantity": "2", "rate": "100", "gst_rate": "18"}])
        get_store.return_value = {"id": payload.store_id, "address": "Seller address"}
        customer = {"legal_name": "Customer", "address": "Customer address", "gst_number": None}
        company = {"company_name": "Seller", "address": "Seller address", "gst_number": None,
                   "gst_registered": False, "prices_include_gst": True}
        db.execute.side_effect = [
            MagicMock(mappings=MagicMock(return_value=MagicMock(first=MagicMock(return_value=customer)))),
            MagicMock(mappings=MagicMock(return_value=MagicMock(one=MagicMock(return_value=company)))),
        ]
        _, document = QuotationService(db).prepare("company", payload)
        self.assertFalse(resolve.call_args.kwargs["require_hsn"])
        masters.assert_not_called()
        self.assertEqual((document["lines"][0]["hsn"], document["gst_total"], document["total"]),
                         ("", "0.00", "200.00"))

    @patch("app.services.quotation_service.QuotationService")
    def test_ai_preview_and_post_use_quotation_service_without_committing(self, service):
        from app.ai.business_writes import apply_action, operational_preview
        payload = self.payload(quotation_date="2026-11-15")
        doc = {"subtotal": "200.00", "gst_total": "0.00", "total": "200.00", "lines": []}
        service.return_value.prepare.return_value = ({}, doc)
        db = MagicMock()
        values = payload.model_dump(mode="json", exclude={"idempotency_key"})
        preview = operational_preview(db, "company", "quotation_create", None, values)
        self.assertEqual(preview["document"], doc)
        self.assertEqual(preview["stock_change"], "0")
        self.assertEqual(preview["payment"], "None")
        apply_action(db, "company", "quotation_create", None, values, "ai-test-key")
        self.assertIs(service.return_value.create.call_args.kwargs["commit"], False)
        self.assertEqual(service.return_value.create.call_args.args[1].idempotency_key, "ai-test-key")



if __name__ == "__main__":
    unittest.main()
