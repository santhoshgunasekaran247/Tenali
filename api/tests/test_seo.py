import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from xml.etree import ElementTree

from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import text

from app.services.seo import SeoPage, absolute_image, build_page, render_document, sitemap
from test_tenancy import TenantDatabaseCase

TEMPLATE = '<html><head><title>Old</title><meta name="description" content="Old"><meta property="og:image" content="/old.png"></head><body><div id="root"></div><script src="/assets/app.js"></script></body></html>'


def request(host="localhost"):
    return Request({"type": "http", "scheme": "http", "server": (host, 80),
                    "path": "/", "headers": [(b"host", host.encode())], "query_string": b""})


class SeoTests(unittest.TestCase):
    def test_html_escapes_catalogue_text_and_json_and_retains_application(self):
        malicious = '</script><img src=x onerror="bad()">'
        page = SeoPage(title=malicious, description='" & description', canonical="https://shop.test/",
                       image="https://shop.test/photo.jpg", indexable=True,
                       body="<main><h1>Real content</h1></main>",
                       structured_data=[{"@type": "Product", "name": malicious}])
        html = render_document(page, TEMPLATE)
        self.assertNotIn(malicious, html)
        self.assertEqual(html.count("<title>"), 1)
        self.assertEqual(html.count('name="description"'), 1)
        self.assertEqual(html.count('property="og:image"'), 1)
        self.assertIn('content="index,follow"', html)
        self.assertIn("<h1>Real content</h1>", html)
        self.assertIn('src="/assets/app.js"', html)
        schema = re.search(r'data-tenali-seo>(.*?)</script>', html)[1]
        self.assertEqual(json.loads(schema)["name"], malicious)

    def test_private_preview_and_unknown_pages_cannot_be_indexed(self):
        with patch("app.services.seo.context", return_value=(None, "https://tenali.test", "/")):
            page = build_page(None, request(), "/?storefrontPreview=fixture")
            self.assertFalse(page.indexable)
            self.assertEqual(page.canonical, "https://tenali.test/")
        for path, status in [("/portal/reports", 200), ("/login", 200), ("/cart", 200), ("/missing", 404)]:
            with self.subTest(path=path), patch("app.services.seo.context", return_value=(None, "https://tenali.test", path)):
                page = build_page(None, request(), path)
                self.assertFalse(page.indexable)
                self.assertEqual(page.status, status)
                self.assertIsNone(page.canonical)

    def test_empty_preview_parameter_is_not_indexed(self):
        company = {"company_name": "Example store", "nickname": "Example", "storefront_content": {}}
        data = {"company": company, "products": [], "categories": [], "brands": [],
                "selected_brand": None, "selected_category": None}
        with patch("app.services.seo.context", return_value=("company", "https://shop.test", "/")), \
                patch("app.services.seo.scope_catalog"), patch("app.services.seo.ensure_storefront_enabled"), \
                patch("app.services.seo.CatalogService") as service:
            service.return_value.list.return_value = data
            page = build_page(None, request(), "/?storefrontPreview=")
        self.assertFalse(page.indexable)

    def test_product_metadata_uses_public_product_not_shop_title(self):
        product_id = str(uuid4())
        company = {"company_name": "Example store", "nickname": "Example"}
        image_company, image_file = uuid4(), uuid4()
        image_path = f"/api/public-images/{image_company}/{image_file}"
        product = {"id": product_id, "name": "Steel bottle", "description": "A reusable bottle.",
                   "selling_price_display": "250.00", "image_url": image_path, "brand_name": "Maker"}
        with patch("app.services.seo.context", return_value=("company", "https://shop.test", "/products/" + product_id)), \
                patch("app.services.seo.scope_catalog"), patch("app.services.seo.ensure_storefront_enabled"), \
                patch("app.services.seo.CatalogService") as service:
            service.return_value.product_detail.return_value = {"company": company, "product": product}
            page = build_page(None, request(), "/products/" + product_id + "?variant=one")
        self.assertEqual(page.title, "Steel bottle | Example")
        self.assertEqual(page.canonical, "https://shop.test/products/" + product_id)
        self.assertEqual(page.image, "https://shop.test" + image_path)
        self.assertFalse(page.indexable)
        self.assertEqual(page.structured_data[0]["@type"], "Product")
        self.assertNotIn("offers", page.structured_data[0])

    def test_sitemap_splits_large_catalogues_and_rejects_invalid_pages(self):
        from unittest.mock import MagicMock
        db = MagicMock()
        db.execute.return_value.scalar_one.return_value = 1001
        db.execute.return_value.scalars.return_value = ["last-product"]
        with patch("app.services.seo.context", return_value=("company", "https://shop.test", "/")), \
                patch("app.services.seo.scope_catalog"), patch("app.services.seo.ensure_storefront_enabled"), \
                patch("app.services.seo.policies.published_list", return_value={"items": []}):
            index = ElementTree.fromstring(sitemap(db, request(), "/sitemap.xml"))
            self.assertTrue(index.tag.endswith("sitemapindex"))
            self.assertEqual(len(index), 2)
            page = sitemap(db, request(), "/sitemap.xml?page=2")
            self.assertIn("https://shop.test/products/last-product", page)
            for value in ["0", "-1", "abc", "999999999", "3"]:
                with self.subTest(value=value), self.assertRaises(HTTPException):
                    sitemap(db, request(), "/sitemap.xml?page=" + value)

    def test_social_images_reject_unsafe_urls(self):
        for value in ["javascript:alert(1)", "//untrusted.test/image.jpg", "https://user:pass@shop.test/a.jpg"]:
            self.assertIsNone(absolute_image(value, "https://shop.test"))
        for value in ["assets/brand-logos/box.png", "/assets/brand-logos/box.png", "brand-logos/box.png"]:
            self.assertEqual(absolute_image(value, "https://shop.test"), "https://shop.test/api/catalog-assets/brand-logos/box.png")


class SeoDatabaseTests(TenantDatabaseCase):
    def setUp(self):
        background = patch("app.services.domain_onboarding.custom_domains_enabled", return_value=False)
        background.start()
        self.addCleanup(background.stop)
        super().setUp()

    def test_public_documents_enforce_tenants_visibility_domains_and_real_statuses(self):
        self.stack.enter_context(patch("app.api.routes.seo.SessionLocal", self.factory))
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        Path(directory, "index.html").write_text(TEMPLATE, encoding="utf-8")
        self.stack.enter_context(patch.dict(os.environ, {"TENALI_WEB_ROOT": directory}))
        first, _, _ = self.register("seo-a")
        second, _, _ = self.register("seo-b")
        company_a, company_b = first["user"]["company_id"], second["user"]["company_id"]
        slug = first["user"]["tenant_slug"]
        with self.factory() as db:
            public_id = db.execute(text("""insert into products(company_id,portal_product_id,name,description,image_url)
                values(:company,'seo-public','Public bottle','A useful bottle.','assets/brand-logos/box.png') returning id"""),
                {"company": company_a}).scalar_one()
            hidden_id = db.execute(text("""insert into products(company_id,portal_product_id,name,catalog_visible)
                values(:company,'seo-hidden','Hidden bottle',false) returning id"""), {"company": company_a}).scalar_one()
            foreign_id = db.execute(text("""insert into products(company_id,portal_product_id,name)
                values(:company,'seo-foreign','Other tenant bottle') returning id"""), {"company": company_b}).scalar_one()
            db.execute(text("""insert into tenant_domains(company_id,hostname,verification_token,verified_at,hosting_status)
                values(:company,:host,'seo-fixture',now(),'active')"""), {"company": company_a, "host": "seo-" + self.suffix + ".example.com"})
            db.commit()
        # A logged-in user from another tenant must not affect public HTML.
        root = self.client.get("/seo/pages/c/" + slug)
        self.assertEqual(root.status_code, 200, root.text)
        self.assertIn("Public bottle", root.text)
        self.assertNotIn("Hidden bottle", root.text)
        self.assertNotIn("Other tenant bottle", root.text)
        canonical = "https://seo-" + self.suffix + ".example.com"
        self.assertIn(f'href="{canonical}/"', root.text)
        custom_home = self.client.get("/seo/pages/", headers={"Host": "seo-" + self.suffix + ".example.com"})
        self.assertEqual(custom_home.status_code, 200, custom_home.text)
        cross_domain = self.client.get("/seo/pages/c/" + second["user"]["tenant_slug"],
                                      headers={"Host": "seo-" + self.suffix + ".example.com"})
        self.assertEqual(cross_domain.status_code, 404, cross_domain.text)
        product_path = f"/c/{slug}/products/{public_id}"
        product = self.client.get("/seo/pages" + product_path)
        self.assertEqual(product.status_code, 200, product.text)
        self.assertIn("Public bottle |", product.text)
        meta = self.client.get("/api/seo/metadata", params={"path": product_path})
        self.assertEqual(meta.status_code, 200, meta.text)
        self.assertEqual(meta.json()["canonical"], canonical + "/products/" + str(public_id))
        self.assertEqual(meta.json()["image"], canonical + "/api/catalog-assets/brand-logos/box.png")
        for product_id in [hidden_id, foreign_id, uuid4(), "invalid"]:
            denied = self.client.get(f"/seo/pages/c/{slug}/products/{product_id}")
            self.assertEqual(denied.status_code, 404, denied.text)
            self.assertIn("noindex", denied.headers["x-robots-tag"])
        private = self.client.get(f"/seo/pages/c/{slug}/portal/reports")
        self.assertEqual(private.status_code, 200)
        self.assertIn("noindex", private.headers["x-robots-tag"])
        self.assertNotIn("Public bottle", private.text)
        sitemap_response = self.client.get(f"/seo/pages/c/{slug}/sitemap.xml")
        self.assertEqual(sitemap_response.status_code, 200, sitemap_response.text)
        self.assertIn("application/xml", sitemap_response.headers["content-type"])
        ElementTree.fromstring(sitemap_response.text)
        self.assertIn(str(public_id), sitemap_response.text)
        self.assertNotIn(str(hidden_id), sitemap_response.text)
        self.assertNotIn(str(foreign_id), sitemap_response.text)
        robots = self.client.get("/seo/pages/robots.txt")
        self.assertEqual(robots.status_code, 200)
        self.assertIn("text/plain", robots.headers["content-type"])
        self.assertIn("Sitemap:", robots.text)
        self.assertEqual(self.client.head("/seo/pages" + product_path).content, b"")
        self.assertEqual(self.client.get("/seo/pages/missing").status_code, 404)
        self.assertEqual(self.client.get("/seo/pages/c/missing-workspace").status_code, 404)
        self.assertEqual(self.client.get("/seo/pages/", headers={"Host": "unconfigured.example.com"}).status_code, 404)
        # Public SEO bypasses must not change the existing protected API boundary.
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/accounts").status_code, 401)
        with self.factory() as db:
            db.execute(text("update companies set storefront_enabled=false where id=:company"), {"company": company_a})
            db.commit()
        disabled = self.client.get("/seo/pages" + product_path)
        self.assertEqual(disabled.status_code, 404, disabled.text)
        self.assertNotIn("Public bottle", disabled.text)
        closed_home = self.client.get(f"/seo/pages/c/{slug}")
        self.assertEqual(closed_home.status_code, 200, closed_home.text)
        self.assertIn("noindex", closed_home.headers["x-robots-tag"])
        self.assertEqual(self.client.get(f"/seo/pages/c/{slug}/sitemap.xml").status_code, 404)
