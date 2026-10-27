import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.billing import InvoiceLineCreate
from app.schemas.masters import HsnMasterCreate, HsnMasterUpdate
from app.services.masters_service import MastersService


class HsnMasterSchemaTests(unittest.TestCase):
    def test_hsn_and_sac_codes_and_rates(self):
        for code in ["8516", "998599", "85167990"]:
            item = HsnMasterCreate(code=code, description=" Test item ", gst_rate="18.00")
            self.assertEqual(item.description, "Test item")
        self.assertEqual(HsnMasterCreate(code="8516", description="Exempt", gst_rate=0).gst_rate, 0)
        self.assertEqual(HsnMasterCreate(code="8516", description="Special rate", gst_rate=40).gst_rate, 40)

    def test_invalid_master_values(self):
        for values in [dict(code="abc"), dict(code="12345"), dict(description=" "), dict(gst_rate=-1), dict(gst_rate=101)]:
            with self.assertRaises(ValidationError):
                HsnMasterCreate(**{**dict(code="8516", description="Test", gst_rate=18), **values})

    def test_master_code_cannot_be_changed(self):
        with self.assertRaises(ValidationError):
            HsnMasterUpdate(code="9999", description="Test", gst_rate=18, is_active=True)


class HsnRateResolutionTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.service = MastersService(self.db)
        self.line = InvoiceLineCreate(description="Test item", hsn="8516", quantity=2, rate=100, gst_rate=0)

    def test_master_rate_overrides_client_value(self):
        self.db.execute.return_value.mappings.return_value.all.return_value = [{"code": "8516", "gst_rate": Decimal("18.00")}]
        self.service.apply_hsn_rates([self.line], "company-one")
        self.assertEqual(self.line.gst_rate, Decimal("18.00"))
        params = self.db.execute.call_args.args[1]
        self.assertEqual(params["company_id"], "company-one")
        self.assertEqual(params["codes"], ["8516"])

    def test_unknown_or_inactive_code_rejected(self):
        self.db.execute.return_value.mappings.return_value.all.return_value = []
        with self.assertRaises(HTTPException) as error:
            self.service.apply_hsn_rates([self.line], "company-one")
        self.assertEqual(error.exception.status_code, 422)
        self.assertIn("8516", error.exception.detail)

    def test_rate_resolution_is_atomic_for_all_lines(self):
        self.db.execute.return_value.mappings.return_value.all.return_value = [{"code": "8516", "gst_rate": Decimal("18.00")}]
        missing = InvoiceLineCreate(description="Other item", hsn="9999", quantity=1, rate=100)
        with self.assertRaises(HTTPException):
            self.service.apply_hsn_rates([self.line, missing], "company-one")
        self.assertEqual(self.line.gst_rate, Decimal("0"))


if __name__ == "__main__":
    unittest.main()