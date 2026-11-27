import sqlite3
import unittest
from contextlib import closing
from unittest.mock import Mock, patch
from uuid import uuid4

from pydantic import ValidationError

from app.schemas.storefront import ProductTagsUpdate, StorefrontSectionInput
from app.schemas.inventory import ProductInput
from app.schemas.company import StorefrontContent
from app.services.catalog_service import CatalogService, _catalog_categories_query, _catalog_brands_query
from app.services.storefront_sections import StorefrontSectionsService


class StorefrontSectionSchemaTests(unittest.TestCase):
    def test_public_catalog_preserves_images_and_available_products(self):
        from app.schemas.catalog import CatalogHomeResponse
        product = {"id": uuid4(), "name": "Cup", "minimum_order_quantity": 1, "image_background": "#fff0f5"}
        response = CatalogHomeResponse.model_validate({
            "company": {"id": uuid4(), "company_name": "Example"},
            "brands": [{"id": uuid4(), "name": "Example", "code": "EXAMPLE", "image_url": "https://example.com/logo.png"}],
            "categories": [], "best_sellers": [], "sru_specials": [], "catalog_products": [product],
        }).model_dump()
        self.assertEqual(response["brands"][0]["image_url"], "https://example.com/logo.png")
        self.assertEqual(response["catalog_products"][0]["image_background"], "#fff0f5")

    def test_saved_sections_prioritise_selected_items_or_explicitly_restrict_them(self):
        def mapped(rows):
            result = Mock()
            result.mappings.return_value.all.return_value = rows
            result.mappings.return_value.first.return_value = rows[0] if rows else None
            return result

        for selected_only in (False, True):
            with self.subTest(selected_only=selected_only):
                db = Mock()
                sections = [{"id": kind, "section_type": kind, "is_enabled": True, "configuration": {"selected_only": selected_only}}
                            for kind in ("products", "categories", "brands")]
                choices = [mapped([]) for _ in sections]
                for choice in choices:
                    choice.scalars.return_value.all.return_value = ["2", "foreign", "inactive"]
                items = [{"id": str(index), "name": f"Item {index}"} for index in (1, 2, 3)]
                db.execute.side_effect = [mapped([{"id": "tenant"}]), mapped(items), mapped(items), mapped(items),
                                          mapped(sections), *choices]
                result = CatalogService(db).home("tenant")
                for section in result["sections"]:
                    self.assertEqual([item["id"] for item in section[section["section_type"]]],
                                     ["2"] if selected_only else ["2", "1", "3"])

    def section(self, **overrides):
        values = {
            "section_key": "custom-section",
            "section_type": "products",
            "title": "New collection",
            "sort_order": 0,
        }
        values.update(overrides)
        return StorefrontSectionInput.model_validate(values)

    def test_hero_sections_allow_image_and_presentation_without_catalog_mapping(self):
        section = self.section(
            section_type="hero",
            title="Welcome",
            image_url="https://example.com/banner.jpg",
            configuration={"image_ratio": "landscape", "background_color": "#ffffff"},
        )

        self.assertEqual(section.section_type, "hero")
        self.assertEqual(section.image_url, "https://example.com/banner.jpg")

    def test_hero_sections_cannot_be_mapped_to_catalog_items(self):
        with self.assertRaises(ValidationError):
            self.section(section_type="hero", product_ids=[uuid4()])

    def test_sections_reject_cross_type_items_and_unsupported_style_values(self):
        with self.assertRaises(ValidationError):
            self.section(section_type="products", category_ids=[uuid4()])
        with self.assertRaises(ValidationError):
            self.section(configuration={"background_color": "red"})
        with self.assertRaises(ValidationError):
            self.section(configuration={"html": "<script>alert(1)</script>"})

    def test_selected_only_is_explicit_and_boolean(self):
        self.assertNotIn("selected_only", self.section().configuration)
        self.assertIs(self.section(configuration={"selected_only": True}).configuration["selected_only"], True)
        with self.assertRaises(ValidationError):
            self.section(configuration={"selected_only": "yes"})

    def test_classic_defaults_keep_native_layout_and_validate_matching_catalog_type(self):
        for slot, section_type in {
            "hero": "hero", "categories": "categories", "best-sellers": "products",
            "specials": "products", "brands": "brands",
        }.items():
            section = self.section(section_type=section_type, configuration={"classic_slot": slot})
            self.assertEqual(section.configuration["classic_slot"], slot)
        for slot in ("hero", "unknown", True):
            with self.assertRaises(ValidationError):
                self.section(section_type="products", configuration={"classic_slot": slot})

    def test_footer_override_round_trips_without_changing_existing_copy(self):
        original = StorefrontContent()
        self.assertIsNone(original.footer.contact_text)
        content = StorefrontContent.model_validate({
            "footer": {"contact_text": "Contact our store", "catalogue_label": "Catalogue"},
            "home": {"hero_heading_first": "Our original heading"},
        })
        restored = StorefrontContent.model_validate(content.model_dump())
        self.assertEqual(restored.footer.contact_text, "Contact our store")
        self.assertEqual(restored.home.hero_heading_first, "Our original heading")

    def test_homepage_link_settings_round_trip_without_changing_existing_content(self):
        content = StorefrontContent.model_validate({
            "home": {"hero_heading_first": "Our collection"},
            "links": {
                "hero.primary": {"label": "Shop new arrivals", "href": "/#section-new-arrivals"},
                "section.custom-hero.hero.secondary": {"label": "Our story", "href": "https://example.com/story"},
            },
            "product": {"choose_options": "Select your size", "add_to_enquiry": "Ask about this"},
        })
        restored = StorefrontContent.model_validate(content.model_dump())
        self.assertEqual(restored.links["hero.primary"].href, "/#section-new-arrivals")
        self.assertEqual(restored.links["section.custom-hero.hero.secondary"].label, "Our story")
        self.assertEqual(restored.home.hero_heading_first, "Our collection")
        self.assertEqual(restored.product.choose_options, "Select your size")
        self.assertEqual(StorefrontContent().links, {})

    def test_homepage_links_reject_unsafe_destinations_and_accept_supported_links(self):
        for href in ("", "#why", "/brand?q=gifts", "https://example.com/gifts", "mailto:hello@example.com", "tel:+919999999999"):
            with self.subTest(href=href):
                content = StorefrontContent.model_validate({"links": {"hero.primary": {"href": href}}})
                self.assertEqual(content.links["hero.primary"].href, href)
        for href in ("javascript:alert(1)", "data:text/html,test", "//example.com", "/\\example.com", "#", "not a link", "https://example.com/\npath"):
            with self.subTest(href=href):
                with self.assertRaises(ValidationError):
                    StorefrontContent.model_validate({"links": {"hero.primary": {"href": href}}})

    def test_header_menu_round_trip_preserves_hidden_and_empty_menus_and_limits_items(self):
        items = [{"key": f"menu-{index}", "label": f"Menu {index}", "href": "/#contact", "is_enabled": index != 2}
                 for index in range(9)]
        restored = StorefrontContent.model_validate(StorefrontContent(header_menu=items).model_dump())
        self.assertEqual(len(restored.header_menu), 9)
        self.assertFalse(restored.header_menu[2].is_enabled)
        self.assertEqual(StorefrontContent.model_validate({"header_menu": []}).header_menu, [])
        for invalid in (
            items + [{"key": "extra", "label": "Extra", "href": "/"}],
            [items[0], items[0]],
            [{"key": "unsafe", "label": "Unsafe", "href": "javascript:alert(1)"}],
            [{"key": "empty", "label": " ", "href": "/"}],
            [{"key": "empty", "label": "Menu", "href": ""}],
        ):
            with self.subTest(items=invalid):
                with self.assertRaises(ValidationError):
                    StorefrontContent.model_validate({"header_menu": invalid})

    def test_product_tags_keep_assignments_distinct_and_unique(self):
        product_id = uuid4()
        payload = ProductTagsUpdate.model_validate({
            "tags": [
                {"code": "new-collection", "name": "New Collection", "product_ids": [product_id]},
                {"code": "fast-selling", "name": "Fast Selling", "product_ids": [product_id]},
            ]
        })

        self.assertEqual(len(payload.tags), 2)
        with self.assertRaises(ValidationError):
            ProductTagsUpdate.model_validate({
                "tags": [
                    {"code": "new-collection", "name": "New Collection"},
                    {"code": "new-collection", "name": "Featured"},
                ]
            })

    def test_editorial_images_round_trip_and_reject_invalid_image_sources(self):
        images = {"why_left": "https://example.com/makers.jpg", "why_right": None}
        content = StorefrontContent.model_validate({"images": images})
        restored = StorefrontContent.model_validate(content.model_dump())
        self.assertEqual(restored.images, images)
        for source in ("javascript:alert(1)", "data:text/html,test"):
            with self.subTest(source=source):
                with self.assertRaises(ValidationError):
                    StorefrontContent.model_validate({"images": {"why_left": source}})


class ProductTagInputTests(unittest.TestCase):
    def test_omitted_tags_preserve_existing_assignments_for_legacy_updates(self):
        payload = ProductInput.model_validate({"name": "Cotton Kurta"})

        self.assertIsNone(payload.tags)

    def test_product_tags_are_trimmed_and_empty_tags_are_rejected(self):
        payload = ProductInput.model_validate({"name": "Cotton Kurta", "tags": [" Festive ", "New arrivals"]})

        self.assertEqual(payload.tags, ["Festive", "New arrivals"])
        with self.assertRaises(ValidationError):
            ProductInput.model_validate({"name": "Cotton Kurta", "tags": [" "]})

class ClassicSectionVisibilityTests(unittest.TestCase):
    def test_master_photo_fallback_uses_public_tenant_products_and_keeps_explicit_images(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.create_function("split_part", 3, lambda value, delimiter, part: value.split(delimiter)[part - 1] if value else None)
            db.executescript("""
                create table product_categories(id text, company_id text, code text, name text, display_title text,
                    description text, image_url text, home_order integer, is_active boolean);
                create table brands(id text, company_id text, code text, name text, description text, image_url text, is_active boolean);
                create table products(id text, company_id text, category_id text, brand_id text, name text,
                    image_url text, image_urls text, home_order integer, is_active boolean, catalog_visible boolean);
                create table product_category_products(company_id text, product_id text, category_id text);
                insert into product_categories values('cat','tenant','cat','Category',null,null,null,0,true);
                insert into brands values('brand','tenant','brand','Brand',null,null,true);
                insert into products values('foreign','other','cat','brand','Foreign','foreign.png',null,0,true,true);
                insert into products values('hidden','tenant','cat','brand','Hidden','hidden.png',null,0,true,false);
                insert into products values('inactive','tenant','cat','brand','Inactive','inactive.png',null,0,false,true);
                insert into products values('first','tenant',null,'brand','First',null,'first.png|second.png',1,true,true);
                insert into products values('later','tenant','cat','brand','Later','later.png',null,2,true,true);
                insert into product_category_products values('tenant','first','cat');
            """)
            category = db.execute(_catalog_categories_query(), {"company_id": "tenant"}).fetchone()
            brand = db.execute(_catalog_brands_query(), {"company_id": "tenant"}).fetchone()
            self.assertEqual(category[5], "first.png")
            self.assertEqual(brand[4], "first.png")
            db.execute("update product_categories set image_url='category.png'")
            db.execute("update brands set image_url='brand.png'")
            self.assertEqual(db.execute(_catalog_categories_query(), {"company_id": "tenant"}).fetchone()[5], "category.png")
            self.assertEqual(db.execute(_catalog_brands_query(), {"company_id": "tenant"}).fetchone()[4], "brand.png")

    def test_all_active_categories_are_visible_without_exposing_other_tenants_or_inactive_categories(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.create_function("split_part", 3, lambda value, delimiter, part: value.split(delimiter)[part - 1] if value else None)
            db.executescript("""
                create table product_categories(id text, company_id text, code text, name text,
                    display_title text, description text, image_url text, home_order integer, is_active boolean);
                create table products(id text, company_id text, category_id text, is_active boolean, catalog_visible boolean,
                    image_url text, image_urls text, home_order integer, name text);
                create table product_category_products(company_id text, product_id text, category_id text);
                create table storefront_sections(id text, company_id text, section_type text, is_enabled boolean);
                create table storefront_section_categories(company_id text, section_id text, category_id text);
            """)
            for category_id, active, company_id in (
                ("diya", True, "tenant"), ("unselected", True, "tenant"), ("inactive", False, "tenant"),
                ("disabled", True, "tenant"), ("populated", True, "tenant"),
                ("hidden-product", True, "tenant"), ("foreign", True, "other"),
                ("cross-tenant", True, "tenant"), ("secondary", True, "tenant"),
                ("foreign-assignment", True, "tenant"),
            ):
                db.execute("insert into product_categories values(?,?,?,?,?,?,?,?,?)",
                           (category_id, company_id, category_id, category_id, None, None, None, 0, active))
            db.executemany("insert into products(id,company_id,category_id,is_active,catalog_visible) values(?,?,?,?,?)", [
                ("visible", "tenant", "populated", True, True),
                ("hidden", "tenant", "hidden-product", True, False),
            ])
            db.executemany("insert into product_category_products values(?,?,?)", [
                ("tenant", "visible", "secondary"), ("other", "visible", "foreign-assignment"),
            ])
            db.executemany("insert into storefront_sections values(?,?,?,?)", [
                ("enabled", "tenant", "categories", True), ("disabled", "tenant", "categories", False),
                ("other", "other", "categories", True),
            ])
            db.executemany("insert into storefront_section_categories values(?,?,?)", [
                ("tenant", "enabled", "diya"), ("tenant", "enabled", "inactive"),
                ("tenant", "disabled", "disabled"), ("other", "other", "foreign"),
                ("tenant", "other", "cross-tenant"),
            ])
            rows = db.execute(_catalog_categories_query(), {"company_id": "tenant"}).fetchall()
            self.assertEqual([row[0] for row in rows],
                             ["cross-tenant", "disabled", "diya", "foreign-assignment", "hidden-product", "populated", "secondary", "unselected"])

    def test_saved_section_mappings_reload_with_the_same_input_field_names_and_order(self):
        company_id = str(uuid4())
        ids = [uuid4(), uuid4()]
        for section_type, column, field in (
            ("products", "product_id", "product_ids"),
            ("categories", "category_id", "category_ids"),
            ("brands", "brand_id", "brand_ids"),
        ):
            with self.subTest(section_type=section_type):
                section_result = Mock()
                section_result.mappings.return_value.all.return_value = [{
                    "id": uuid4(), "section_key": "selected-items", "section_type": section_type,
                    "title": "Selected items", "sort_order": 0, "configuration": {},
                }]
                items_result = Mock()
                items_result.mappings.return_value.all.return_value = [{column: item_id} for item_id in ids]
                db = Mock()
                db.execute.side_effect = [section_result, items_result]
                with patch("app.services.storefront_sections.CompanyService") as service:
                    service.return_value.get.return_value = {"id": company_id}
                    restored = StorefrontSectionsService(db).list(company_id)[0]
                self.assertEqual(restored[field], [str(item_id) for item_id in ids])
                payload = {key: value for key, value in restored.items() if key != "id"}
                self.assertEqual(getattr(StorefrontSectionInput.model_validate(payload), field), ids)

    def test_hidden_sections_remain_configured_without_exposing_their_items(self):
        company_result = Mock()
        company_result.mappings.return_value.first.return_value = {"id": "company"}
        empty_result = Mock()
        empty_result.mappings.return_value.all.return_value = []
        section_result = Mock()
        for configuration in ({"classic_slot": "best-sellers"}, {}):
            with self.subTest(configuration=configuration):
                section_result.mappings.return_value.all.return_value = [{
                    "id": "hidden-section", "section_type": "products",
                    "is_enabled": False, "configuration": configuration,
                }]
                db = Mock()
                db.execute.side_effect = [company_result, empty_result, empty_result, empty_result, section_result]

                result = CatalogService(db).home("company")

                self.assertTrue(result["classic_sections_configured"])
                self.assertEqual(result["sections"], [])
                self.assertEqual(db.execute.call_count, 5)


if __name__ == "__main__":
    unittest.main()
