import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.api.routes.billing import get_invoice, get_quotation
from app.services.access import check_module
from app.services.billing_service import BillingService
from app.services.quotation_service import QuotationService


class BillingDocumentReadTests(unittest.TestCase):
    def test_exact_queries_keep_company_and_store_filters(self):
        company, document, store = (str(uuid4()) for _ in range(3))
        for kind in ("invoice", "quotation"):
            with self.subTest(kind=kind):
                db = MagicMock()
                db.info = {"tenant_context": {"role": "viewer", "store_ids": [store]}}
                db.execute.return_value.mappings.return_value.all.return_value = []
                if kind == "invoice":
                    service = BillingService(db)
                    with patch.object(service, "_ensure_tables"):
                        result = service.list_invoices(company, invoice_id=document, limit=1)
                else:
                    result = QuotationService(db).list(company, quotation_id=document)
                self.assertEqual(result, {"items": []})
                statement, params = db.execute.call_args.args
                sql = str(statement).lower()
                self.assertIn("company_id", sql)
                self.assertIn("store_id", sql)
                self.assertIn(":permitted", sql)
                self.assertIn(":invoice_id" if kind == "invoice" else ":quotation", sql)
                self.assertEqual(params["company_id" if kind == "invoice" else "company"], company)
                self.assertEqual(params["invoice_id" if kind == "invoice" else "quotation"], document)
                self.assertEqual(params["permitted"], [store])
                db.commit.assert_not_called()

    def test_detail_routes_return_record_or_404(self):
        document, company, db = uuid4(), str(uuid4()), MagicMock()
        for kind, handler in (("invoice", get_invoice), ("quotation", get_quotation)):
            with self.subTest(kind=kind), patch(
                f"app.api.routes.billing.{'BillingService' if kind == 'invoice' else 'QuotationService'}"
            ) as service:
                listing = service.return_value.list_invoices if kind == "invoice" else service.return_value.list
                listing.return_value = {"items": [{"id": document}]}
                self.assertEqual(handler(document, company, db), {"id": document})
                self.assertEqual(listing.call_args.kwargs[f"{kind}_id"], str(document))
                listing.return_value = {"items": []}
                with self.assertRaises(HTTPException) as error:
                    handler(document, company, db)
                self.assertEqual(error.exception.status_code, 404)

    def test_billing_access_is_required_for_both_detail_paths(self):
        identity = {"role": "viewer", "modules": ["inventory"]}
        for kind in ("invoices", "quotations"):
            with self.subTest(kind=kind), self.assertRaises(HTTPException) as error:
                check_module(identity, f"/billing/{kind}/{uuid4()}")
            self.assertEqual(error.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
