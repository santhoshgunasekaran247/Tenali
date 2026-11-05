import unittest
from datetime import date
from unittest.mock import MagicMock

from fastapi import HTTPException
from app.services.document_numbers import next_document_number


class DocumentNumberTests(unittest.TestCase):
    def test_invoice_uses_store_full_date_and_five_digit_monthly_counter(self):
        db = MagicMock()
        db.execute.return_value.scalar_one.return_value = 23
        number = next_document_number(db, "company", {"id": "store-id", "code": "MAIN", "invoice_code": "01"}, "invoice", date(2026, 11, 6))
        self.assertEqual(number, "I012026110600023")
        self.assertEqual(len(number), 16)
        self.assertNotIn("-", number)
        self.assertEqual(db.execute.call_args.args[1], {
            "company": "company", "store": "store-id", "kind": "invoice", "year": 2026, "month": 11,
        })

    def test_purchase_format_and_large_counters_are_preserved(self):
        db = MagicMock()
        db.execute.return_value.scalar_one.return_value = 100000
        store = {"id": "store-id", "code": "T2", "invoice_code": "02"}
        self.assertEqual(next_document_number(db, "company", store, "purchase", date(2026, 11, 6)), "PUR-T2-202611-100000")
        with self.assertRaises(HTTPException) as error:
            next_document_number(db, "company", store, "invoice", date(2026, 11, 6))
        self.assertEqual(error.exception.status_code, 422)

    def test_invoice_maximum_fits_without_truncating_the_counter(self):
        db = MagicMock()
        db.execute.return_value.scalar_one.return_value = 99999
        self.assertEqual(next_document_number(db, "company", {"id": "store-id", "invoice_code": "AZ"}, "invoice", date(2026, 1, 2)),
                         "IAZ2026010299999")
