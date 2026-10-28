import unittest
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.billing import InvoiceCreate
from app.schemas.company import CompanySetupOut, CompanyUpdate, InvoiceSettings, SiteTheme, StorefrontContent
from app.services.invoice_document import build_invoice_document


class InvoiceDocumentTests(unittest.TestCase):
    def setUp(self):
        self.company = {"company_name": "SRU Global", "address": "Chennai", "gst_number": "33ABCDE1234F1Z5"}
        self.customer = {"legal_name": "Example Customer", "address": "Madurai", "gst_number": None}
        self.payload = InvoiceCreate(
            customer_party_id="00000000-0000-0000-0000-000000000001",
            place_of_supply="33 - Tamil Nadu",
            lines=[{"description": "Kettle", "hsn": "8516", "quantity": "2", "rate": "100.00", "gst_rate": "18"}],
        )

    def test_equal_split_and_shipping_default(self):
        document = build_invoice_document(self.payload, self.company, self.customer)
        self.assertEqual(document["subtotal"], "200.00")
        self.assertEqual(document["total"], "236.00")
        self.assertEqual(document["lines"][0]["cgst"], "18.00")
        self.assertEqual(document["lines"][0]["sgst"], "18.00")
        self.assertEqual(document["ship_to"]["address"], "Madurai")

    def test_interstate_igst(self):
        self.payload.place_of_supply = "29 - Karnataka"
        document = build_invoice_document(self.payload, self.company, self.customer)
        self.assertTrue(document["interstate"])
        self.assertEqual(document["lines"][0]["igst"], "36.00")
        self.assertEqual(document["lines"][0]["cgst"], "0")

    def test_odd_paise_preserves_total(self):
        self.payload.lines[0].quantity = Decimal("1")
        self.payload.lines[0].rate = Decimal("0.05")
        document = build_invoice_document(self.payload, self.company, self.customer)
        line = document["lines"][0]
        self.assertEqual(Decimal(line["cgst"]) + Decimal(line["sgst"]), Decimal(document["gst_total"]))
        self.assertEqual(document["total"], "0.06")

    def test_snapshot_is_independent_of_master_data(self):
        self.company["invoice_settings"] = {"thank_you_note": "Original thanks", "signatory_name": "Original signer"}
        self.payload.shipping_name = "Warehouse"
        self.payload.shipping_address = "Coimbatore"
        document = build_invoice_document(self.payload, self.company, self.customer)
        self.company["company_name"] = "Changed"
        self.customer["address"] = "Changed"
        self.company["invoice_settings"]["thank_you_note"] = "Changed"
        self.assertEqual(document["seller"]["company_name"], "SRU Global")
        self.assertEqual(document["bill_to"]["address"], "Madurai")
        self.assertEqual(document["ship_to"]["address"], "Coimbatore")
        self.assertEqual(document["seller"]["invoice_settings"]["thank_you_note"], "Original thanks")

    def test_missing_company_gst_rejected(self):
        self.company["gst_number"] = None
        with self.assertRaises(HTTPException):
            build_invoice_document(self.payload, self.company, self.customer)

    def test_invalid_line_rejected(self):
        with self.assertRaises(ValidationError):
            InvoiceCreate(customer_party_id=self.payload.customer_party_id, lines=[{
                "description": "Kettle", "hsn": "invalid", "quantity": 0, "rate": -1, "gst_rate": 99,
            }])

    def test_company_invoice_settings_validation(self):
        settings = InvoiceSettings()
        self.assertEqual(settings.thank_you_note, "Thank you for letting us be a part of your celebration.")
        self.assertEqual(settings.signatory_label, "Authorized Signatory")
        for invalid in [{"primary_color": "red"}, {"signature_image": "javascript:alert(1)"}, {"signature_image": "data:image/svg+xml;base64,abc"}]:
            with self.assertRaises(ValidationError):
                InvoiceSettings(**invalid)
        with self.assertRaises(ValidationError):
            CompanyUpdate(company_name=" ")

    def test_existing_company_gst_can_be_read_but_must_be_corrected_on_save(self):
        company = CompanySetupOut(id="00000000-0000-0000-0000-000000000001", is_active=True,
                                  company_name="Legacy Company", gst_number="LEGACY-GST")
        self.assertEqual(company.gst_number, "LEGACY-GST")
        with self.assertRaises(ValidationError):
            CompanyUpdate(company_name=company.company_name, gst_number=company.gst_number)

    def test_site_theme_defaults_and_color_validation(self):
        self.assertEqual(SiteTheme().primary_color, "#142b4a")
        self.assertEqual(SiteTheme().surface_color, "#ffffff")
        self.assertEqual(SiteTheme(primary_color="#19A273").primary_color, "#19A273")
        for invalid in ["red", "#fff", "#1234567", "rgb(1,2,3)", "url(javascript:alert(1))"]:
            with self.assertRaises(ValidationError):
                SiteTheme(primary_color=invalid)

    def test_site_theme_is_independent_of_invoice_colors(self):
        company = CompanyUpdate(company_name="Example", site_theme={"primary_color": "#006644"})
        self.assertEqual(company.site_theme.primary_color, "#006644")
        self.assertEqual(company.invoice_settings.primary_color, "#142b4a")
        self.assertIsNone(CompanyUpdate(company_name="Older client").site_theme)

    def test_storefront_copy_defaults_and_workspace_slug_validation(self):
        content = StorefrontContent()
        self.assertEqual(content.home.hero_heading_first, "Corporate gifting,")
        self.assertEqual(content.home.hero_heading_second, "curated the {nickname} way.")
        self.assertEqual(content.home.specials_heading_second, "Chosen by {nickname}.")
        self.assertEqual(CompanyUpdate(company_name="SRU Global", tenant_slug="sourcebysru").tenant_slug, "sourcebysru")
        for value in ["admin", "../sru", "SourceBySru"]:
            with self.assertRaises(ValidationError):
                CompanyUpdate(company_name="SRU Global", tenant_slug=value)


if __name__ == "__main__":
    unittest.main()