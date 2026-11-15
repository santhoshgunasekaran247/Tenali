import unittest
from datetime import date
from unittest.mock import MagicMock

from fastapi import HTTPException
from app.services.document_numbers import next_document_number


class DocumentNumberTests(unittest.TestCase):
    def test_invoice_uses_date_free_store_series_and_lifetime_counter(self):
        db = MagicMock()
        db.execute.return_value.scalar_one.return_value = 23
        number = next_document_number(db, "company", {"id": "store-id", "code": "MAIN", "invoice_code": "01"}, "invoice", date(2026, 11, 6))
        self.assertEqual(number, "I01-000000000023")
        self.assertEqual(len(number), 16)
        self.assertNotIn("2026", number)
        self.assertEqual(db.execute.call_args.args[1], {
            "company": "company", "store": "store-id", "kind": "invoice", "series_prefix": "I01-",
        })
        self.assertIn("sum(last_number)", str(db.execute.call_args.args[0]))
        self.assertIn("count(*)", str(db.execute.call_args.args[0]))
        self.assertIn("series_prefix", str(db.execute.call_args.args[0]))
        self.assertIn("on conflict", str(db.execute.call_args.args[0]))
        self.assertEqual(
            next_document_number(db, "company", {"id": "other-store", "invoice_code": "02"}, "invoice", date(2027, 4, 1)),
            "I02-000000000023",
        )

    def test_purchase_format_and_large_counters_are_preserved(self):
        db = MagicMock()
        db.execute.return_value.scalar_one.return_value = 1000000000000
        store = {"id": "store-id", "code": "T2", "invoice_code": "02"}
        self.assertEqual(next_document_number(db, "company", store, "purchase", date(2026, 11, 6)), "PUR-T2-202611-1000000000000")
        with self.assertRaises(HTTPException) as error:
            next_document_number(db, "company", store, "invoice", date(2026, 11, 6))
        self.assertEqual(error.exception.status_code, 422)

    def test_invoice_maximum_fits_the_gst_length_limit_without_truncating(self):
        db = MagicMock()
        db.execute.return_value.scalar_one.return_value = 999999999999
        number = next_document_number(db, "company", {"id": "store-id", "invoice_code": "AZ"}, "invoice", date(2026, 1, 2))
        self.assertEqual(number, "IAZ-999999999999")
        self.assertEqual(len(number), 16)
