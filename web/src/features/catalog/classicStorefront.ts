import type { CSSProperties } from "react";
import type { CatalogHomeResponse, StorefrontSection } from "../../types";
import { contrastingText } from "../siteTheme";

export function prioritizedItems<T extends { id: string }>(selected: T[], available: T[], selectedOnly = false): T[] {
  const ids = new Set(selected.map(item => item.id));
  return selectedOnly ? selected : [...selected, ...available.filter(item => !ids.has(item.id))];
}

export function storefrontSectionStyle(configuration: StorefrontSection["configuration"]): CSSProperties & {
  "--site-accent"?: string; "--site-on-accent"?: string;
} {
  const accent = typeof configuration.accent_color === "string" ? configuration.accent_color : undefined;
  return {
    backgroundColor: typeof configuration.background_color === "string" ? configuration.background_color : undefined,
    color: typeof configuration.text_color === "string" ? configuration.text_color : undefined,
    borderColor: accent,
    "--site-accent": accent,
    "--site-on-accent": accent ? contrastingText(accent) : undefined,
  };
}

export const CLASSIC_COPY_FIELDS: Record<string, Array<[string, string, number]>> = {
  hero: [
    ["hero_eyebrow", "Eyebrow", 140],
    ["hero_heading_first", "Heading", 140],
    ["hero_heading_second", "Heading second line", 140],
    ["hero_description", "Description", 600],
    ["hero_primary_action", "Primary action", 100],
    ["hero_secondary_action", "Secondary action", 100],
    ["hero_service_one", "Panel first line", 40],
    ["hero_service_two", "Panel second line", 40],
    ["hero_service_three", "Panel third line", 40],
  ],
  categories: [
    ["categories_eyebrow", "Eyebrow", 80],
    ["categories_heading_first", "Heading", 120],
    ["categories_heading_second", "Heading second line", 120],
    ["categories_description", "Description", 400],
    ["category_card_eyebrow", "Category card eyebrow", 120],
    ["category_action", "Category action", 100],
    ["categories_more_action", "More categories action", 100],
  ],
  "best-sellers": [
    ["best_sellers_eyebrow", "Eyebrow", 80],
    ["best_sellers_heading_first", "Heading", 120],
    ["best_sellers_heading_second", "Heading second line", 120],
    ["best_sellers_description", "Description", 500],
    ["bulk_title", "Bulk pricing heading", 140],
    ["bulk_description", "Bulk pricing description", 400],
  ],
  specials: [
    ["specials_eyebrow", "Eyebrow", 80],
    ["specials_heading_first", "Heading", 120],
    ["specials_heading_second", "Heading second line", 120],
    ["specials_description", "Description", 500],
  ],
  brands: [
    ["brands_eyebrow", "Eyebrow", 80],
    ["brands_heading_first", "Heading", 120],
    ["brands_heading_second", "Heading second line", 120],
    ["brands_description", "Description", 500],
    ["brand_catalog_label", "Brand catalogue label", 100],
    ["brand_action", "Brand action", 100],
  ],
  why: [
    ["why_eyebrow", "Eyebrow", 100],
    ["why_heading_first", "Heading", 120],
    ["why_heading_second", "Heading second line", 120],
    ["why_description", "Description", 600],
  ],
  contact: [
    ["contact_eyebrow", "Eyebrow", 100],
    ["contact_heading_first", "Heading", 120],
    ["contact_heading_second", "Heading second line", 120],
    ["contact_description", "Description", 400],
    ["contact_whatsapp_label", "WhatsApp label", 100],
  ],
  about: [
    ["collection_eyebrow", "Eyebrow", 120],
    ["collection_heading_first", "Heading", 120],
    ["collection_heading_second", "Heading second line", 140],
    ["collection_description", "Description", 600],
    ["collection_point_one_title", "First point title", 60],
    ["collection_point_one_body", "First point description", 300],
    ["collection_point_two_title", "Second point title", 60],
    ["collection_point_two_body", "Second point description", 300],
    ["collection_point_three_title", "Third point title", 60],
    ["collection_point_three_body", "Third point description", 300],
  ],
};

export function classicSections(data: CatalogHomeResponse): StorefrontSection[] {
  const section = (
    slot: string, section_type: StorefrontSection["section_type"], title: string,
    items: Partial<StorefrontSection> = {},
  ): StorefrontSection => ({
    section_key: `classic-${slot}`, section_type, title, eyebrow: "", description: "",
    sort_order: 0, is_enabled: true, configuration: { classic_slot: slot },
    product_ids: [], category_ids: [], brand_ids: [], ...items,
  });
  return [
    section("hero", "hero", "Hero"),
    section("categories", "categories", "Categories", {
      categories: data.categories, category_ids: data.categories.map(item => item.id),
    }),
    section("best-sellers", "products", "Best sellers", {
      products: prioritizedItems(data.best_sellers, data.catalog_products || []), product_ids: data.best_sellers.map(item => item.id),
    }),
    section("specials", "products", "Specials", {
      products: prioritizedItems(data.sru_specials, data.catalog_products || []), product_ids: data.sru_specials.map(item => item.id),
    }),
    section("brands", "brands", "Brands", {
      brands: data.brands, brand_ids: data.brands.map(item => item.id),
    }),
  ].map((item, sort_order) => ({ ...item, sort_order }));
}
