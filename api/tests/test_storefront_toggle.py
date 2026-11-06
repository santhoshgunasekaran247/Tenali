import os
import unittest

from test_tenancy import TenantDatabaseCase


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Set TENALI_TEST_DB=1 for rollback-only tenant HTTP/database tests")
class StorefrontToggleTests(TenantDatabaseCase):
    def save_company(self, cookies, **changes):
        self.use_cookies(cookies)
        current = self.client.get("/company")
        self.assertEqual(current.status_code, 200, current.text)
        body = current.json()
        payload = {key: body[key] for key in ["company_name", "tenant_slug", "gst_registered", "social_links", "invoice_settings", "site_theme", "storefront_content"]}
        payload.update(changes)
        return self.client.put("/company", json=payload, headers=self.headers(cookies))

    def test_owner_can_disable_and_reenable_public_storefront(self):
        owner, cookies, _ = self.register("shop-toggle")
        slug = owner["user"]["tenant_slug"]
        public = {"X-Tenant-Slug": slug}
        self.assertTrue(self.client.get("/company").json()["storefront_enabled"])
        self.assertTrue(self.client.get("/catalog/company", headers=public).json()["storefront_enabled"])

        disabled = self.save_company(cookies, storefront_enabled=False)
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertFalse(disabled.json()["storefront_enabled"])

        self.client.cookies.clear()
        company = self.client.get("/catalog/company", headers=public)
        self.assertEqual(company.status_code, 200, company.text)
        self.assertFalse(company.json()["storefront_enabled"])
        for path in ["/catalog/home", "/catalog/list", "/catalog/products/00000000-0000-0000-0000-000000000000", "/shop/availability"]:
            response = self.client.get(path, headers=public)
            self.assertEqual(response.status_code, 403, path + " " + response.text)
            self.assertEqual(response.json()["detail"], "This storefront is currently unavailable")
        enquiry = self.client.post("/shop/enquiries", json={}, headers={**public, "Origin": "http://localhost"})
        self.assertEqual(enquiry.status_code, 403, enquiry.text)
        self.assertEqual(self.client.get("/shop/auth-config", headers=public).status_code, 200)

        omitted = self.save_company(cookies)
        self.assertEqual(omitted.status_code, 200, omitted.text)
        self.assertFalse(omitted.json()["storefront_enabled"], "Omitting the flag must keep the current setting")

        enabled = self.save_company(cookies, storefront_enabled=True)
        self.assertTrue(enabled.json()["storefront_enabled"])
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/catalog/home", headers=public).status_code, 200)
        self.assertEqual(self.client.get("/shop/availability", headers=public).status_code, 200)

    def test_workflow_guidance_toggle_is_kept_unless_sent(self):
        _, cookies, _ = self.register("guide-toggle")
        self.use_cookies(cookies)
        self.assertTrue(self.client.get("/company").json()["workflow_guidance_enabled"])
        off = self.save_company(cookies, workflow_guidance_enabled=False)
        self.assertEqual(off.status_code, 200, off.text)
        self.assertFalse(off.json()["workflow_guidance_enabled"])
        omitted = self.save_company(cookies)
        self.assertFalse(omitted.json()["workflow_guidance_enabled"], "Omitting the flag must keep the current setting")
        self.assertTrue(self.save_company(cookies, workflow_guidance_enabled=True).json()["workflow_guidance_enabled"])

    def test_staff_cannot_toggle_storefront(self):
        from sqlalchemy import text
        owner, cookies, _ = self.register("shop-staff")
        with self.factory() as db:
            db.execute(text("update tenant_memberships set role='staff' where user_id=:user and company_id=:company"),
                       {"user": owner["user"]["user_id"], "company": owner["user"]["company_id"]})
            db.commit()
        response = self.save_company(cookies, storefront_enabled=False)
        self.assertEqual(response.status_code, 403, response.text)


if __name__ == "__main__":
    unittest.main()
