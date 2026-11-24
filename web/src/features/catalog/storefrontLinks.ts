import type { Company, StorefrontMenuItem, StorefrontSection, StorefrontTemplate } from "../../types";
import { storefrontText } from "./storefrontText";

type LinkCompany = Pick<Company, "company_name" | "nickname" | "storefront_content">;
export type StorefrontLinkSetting = { label?: string; href?: string };
export type StorefrontLinkDefinition = { key: string; title: string; label: string; href: string; group: string };
export const MAX_STOREFRONT_MENU_ITEMS = 9;

const defaultHeaderMenu = [
  ["all_departments", "All departments", "/brand?category=all"],
  ["collection", "Collection", "/#collection-special"],
  ["categories", "Categories", "/#categories"],
  ["best_sellers", "Best Sellers", "/#best-sellers"],
  ["specials", "Specials", "/#sru-specials"],
  ["brands", "Brands", "/#brands"],
  ["contact", "Contact", "/#contact"],
] as const;

export function storefrontHeaderMenu(company: LinkCompany & Pick<Company, "storefront_template">): StorefrontMenuItem[] {
  if (company.storefront_content?.header_menu != null) return company.storefront_content.header_menu;
  return defaultHeaderMenu.filter(([key]) => key !== "all_departments" || company.storefront_template === "marketplace")
    .map(([key, fallback, href]) => {
      const link = storefrontLink(company, `nav.${key}`, href, company.storefront_content?.navigation[key] || fallback);
      return { key, label: link.children, href: link.to, is_enabled: true };
    });
}

export function isStorefrontHref(value: string): boolean {
  if (!value) return true;
  if (value.length > 2048 || /[\u0000-\u0020\u007f\\]/.test(value)) return false;
  if (value.startsWith("#")) return value.length > 1;
  if (value.startsWith("/")) return !value.startsWith("//");
  try {
    const url = new URL(value);
    return (/^https?:\/\/[^/]/i.test(value) && ["http:", "https:"].includes(url.protocol) && !!url.hostname) ||
      (["mailto:", "tel:"].includes(url.protocol) && !!url.pathname);
  } catch {
    return false;
  }
}

export function storefrontLink(company: LinkCompany | null | undefined, key: string, href: string, label: string, sectionKey?: string) {
  const links = company?.storefront_content?.links;
  const base = links?.[key];
  const override = sectionKey ? links?.[`section.${sectionKey}.${key}`] : undefined;
  const destination = override?.href || base?.href || href;
  const safeHref = isStorefrontHref(destination) ? destination : href;
  return {
    to: safeHref.startsWith("#") ? `/${safeHref}` : safeHref,
    children: storefrontText(override?.label?.trim() || base?.label?.trim() || label, company || { company_name: "Tenali" }),
  };
}

export function hasStorefrontLinkOverride(company: LinkCompany, key: string, sectionKey?: string): boolean {
  const links = company.storefront_content?.links;
  const base = links?.[key];
  const scoped = sectionKey ? links?.[`section.${sectionKey}.${key}`] : undefined;
  return !!(scoped?.label?.trim() || scoped?.href?.trim() || base?.label?.trim() || base?.href?.trim());
}

export function storefrontSectionId(section: StorefrontSection, sections: StorefrontSection[]): string {
  if (section.section_type === "hero") return `section-${section.section_key}`;
  const peers = sections.filter(item => item.section_type === section.section_type);
  const index = peers.findIndex(item => item.section_key === section.section_key);
  if (section.section_type === "categories" && index === 0) return "categories";
  if (section.section_type === "brands" && index === 0) return "brands";
  if (section.section_type === "products" && index === 0) return "best-sellers";
  if (section.section_type === "products" && index === 1) return "sru-specials";
  return `section-${section.section_key}`;
}

export function storefrontSectionTargets(sections: StorefrontSection[], template: StorefrontTemplate) {
  const targets = sections.filter(section => section.is_enabled).map(section => ({
    href: `/#section-${section.section_key}`, label: section.title || section.section_type,
  }));
  if (template === "current" || template === "marketplace" || template === "boutique") targets.push({ href: "/#why", label: "Why choose us" });
  targets.push({ href: "/#contact", label: "Contact" });
  if (template !== "supermarket") targets.push({ href: "/#collection-special", label: "About / collection story" });
  return targets;
}

export function storefrontLinkDefinitions(company: Company, sections: StorefrontSection[]): StorefrontLinkDefinition[] {
  const home = company.storefront_content?.home || {};
  const nav = company.storefront_content?.navigation || {};
  const classic = !company.storefront_template || company.storefront_template === "current";
  const nativeCopy = classic || company.storefront_template === "marketplace" || company.storefront_template === "boutique";
  const firstProduct = sections.find(section => section.is_enabled && section.section_type === "products");
  const heroTarget = classic ? "/#collection-special" : firstProduct ? `/#section-${firstProduct.section_key}` : "/brand?category=all";
  const definitions: StorefrontLinkDefinition[] = [];
  const add = (group: string, key: string, title: string, href: string, label: string) =>
    definitions.push({ group, key, title, href, label });
  for (const [key, title, href, fallback] of [
    ["contact", "Marketplace utility contact link", "/#contact", "Contact"],
    ["shopper_account", "Shopper account", "/account", "Shopper Account"],
    ["sign_in", "Staff sign-in", "/login", "Workspace Staff Sign In"],
    ["cart", "Cart / enquiry list", "/cart", "Cart"],
  ]) add("Header", `nav.${key}`, title, href, nav[key] || fallback);
  for (const [key, title, href, label] of [
    ["hero.primary", "Hero primary button", heroTarget, nativeCopy ? home.hero_primary_action || "Shop collections" : "Shop collections"],
    ["hero.secondary", "Hero secondary button", classic ? "/#categories" : "/brand?category=all", nativeCopy ? home.hero_secondary_action || "Browse catalogue" : "Browse catalogue"],
    ["quick.categories", "Hero category panel (large link)", "/#categories", home.hero_secondary_action || "Browse categories"],
    ["quick.about", "Hero story panel (large link)", "/#collection-special", home.hero_primary_action || "Our story"],
    ["categories.more", "More categories", "/brand?category=all", home.categories_more_action || "Explore more categories"],
    ["category.card", "Category card action", "", home.category_action || "Explore category"],
    ["brand.card", "Brand card action", "", home.brand_action || "View products"],
    ["section.view_all", "Section view-all link", "/brand?category=all", "View all"],
    ["why.contact", "Why section button", company.phone ? `https://wa.me/${company.phone.replace(/\D/g, "")}` : "/#contact", home.contact_whatsapp_label || "Contact us"],
    ["contact.whatsapp", "Contact WhatsApp button", company.phone ? `https://wa.me/${company.phone.replace(/\D/g, "")}` : "/#contact", home.contact_whatsapp_label || "WhatsApp"],
    ["contact.phone", "Contact phone link", company.phone ? `tel:${company.phone.replace(/[^\d+]/g, "")}` : "/#contact", company.phone || "Phone"],
    ["contact.email", "Contact email link", company.email ? `mailto:${company.email}` : "/#contact", company.email || "Email"],
    ["catalog.explore", "Explore catalogue", "/brand?category=all", "Explore the catalogue"],
  ]) add("Homepage", key, title, href, label);
  for (const [key, label, href] of [
    ["categories", "All categories", "/brand?category=all"], ["best_sellers", nav.best_sellers || "Best sellers", "/#best-sellers"],
    ["brands", nav.brands || "Brands", "/brand?view=brands"], ["account", "Your account & orders", "/account"],
    ["contact", nav.contact || "Contact support", "/#contact"], ["policies", "Store policies", "/policies/tenant"],
    ["about", "About us", "/#collection-special"], ["privacy", "Privacy", "/policies/tenant/privacy"],
    ["terms", "Terms & conditions", "/policies/tenant/terms"],
  ]) add("Footer", `footer.${key}`, label, href, label);
  for (const section of sections) {
    const keys = section.section_type === "hero"
      ? ["hero.primary", "hero.secondary", ...(company.storefront_template === "marketplace" ? ["quick.categories", "quick.about"] : [])]
      : ["section.view_all"];
    for (const key of keys) {
      const base = definitions.find(definition => definition.key === key);
      if (!base) throw new Error(`Missing storefront link definition: ${key}`);
      const href = key === "section.view_all" && section.section_type === "brands" ? "/brand?view=brands" : base.href;
      const resolved = storefrontLink(company, key, href, base.label);
      add("Individual sections", `section.${section.section_key}.${key}`, `${section.title}: ${base.title}`, resolved.to, resolved.children);
    }
  }
  return definitions;
}
