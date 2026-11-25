import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { api } from "../src/api";
import { NotificationProvider } from "../src/components/Notifications";
import { StorefrontDesignPage } from "../src/pages/StorefrontDesignPage";
import { classicSections } from "../src/features/catalog/classicStorefront";
import { STOREFRONT_THEME_PALETTES } from "../src/features/siteTheme";
import { tenantBase } from "../src/features/tenantTransport";

// Dev-only, opt-in browser fixture. Saves never reach the tenant's API.
export async function mountTenantAudit(template) {
  const seed = await api.home();
  const clone = value => structuredClone(value);
  const photo = (width, height, colour) => {
    const canvas = document.createElement("canvas");
    canvas.width = width; canvas.height = height;
    const context = canvas.getContext("2d");
    context.fillStyle = colour; context.fillRect(0, 0, width, height);
    context.fillStyle = "#ffffff"; context.font = "24px sans-serif";
    context.fillText(`${width} x ${height}`, 12, 36);
    return canvas.toDataURL("image/png");
  };
  const photos = [photo(400, 400, "#537d70"), photo(200, 600, "#8c6171"), photo(600, 200, "#816a46")];
  const categories = photos.map((image_url, index) => ({
    id: `audit-category-${index}`, category_slug: `audit-category-${index}`,
    category_title: `Collection ${index + 1}`, category_description: `Selected collection ${index + 1}`, image_url,
  }));
  const brands = photos.map((_, index) => ({ id: `audit-brand-${index}`, code: `audit-brand-${index}`,
    name: `Maker ${index + 1}`, description: `Independent maker ${index + 1}` }));
  const products = Array.from({ length: 8 }, (_, index) => ({
    id: `audit-product-${index}`, portal_product_id: `audit-product-${index}`,
    name: `Tenant ${template} item ${index + 1}`, description: "Tenant audit product",
    image_url: photos[index % photos.length], image_urls: "", selling_price_display: "450", mrp_display: "600",
    minimum_order_quantity: 1, variants: [], best_seller: index < 4, sru_special: index >= 4,
    category_slug: categories[index % categories.length].category_slug, category_title: categories[index % categories.length].category_title,
    brand_code: brands[index % brands.length].code, brand_name: brands[index % brands.length].name,
    is_active: true, stock_qty: 10,
  }));
  const state = {
    company: { ...clone(seed.company), company_name: `${template} audit store`, nickname: `${template} audit`,
      phone: "919999999999", email: "tenant-audit@example.invalid", logo_url: photos[0],
      storefront_template: template, site_theme: clone(STOREFRONT_THEME_PALETTES[template]),
      invoice_settings: {}, storefront_enabled: true, features: { storefront: { platform_allowed: true } } },
    categories, brands, products, photos, writes: [], sections: [],
  };
  const home = () => ({
    company: clone(state.company), categories, brands, catalog_products: products,
    best_sellers: products.slice(0, 4), sru_specials: products.slice(4),
    sections: state.sections.filter(section => section.is_enabled).map(section => ({
      ...clone(section),
      products: (section.product_ids || []).map(id => products.find(item => item.id === id)).filter(Boolean),
      categories: (section.category_ids || []).map(id => categories.find(item => item.id === id)).filter(Boolean),
      brands: (section.brand_ids || []).map(id => brands.find(item => item.id === id)).filter(Boolean),
    })),
    classic_sections_configured: state.sections.length > 0,
  });
  state.sections = classicSections(home());
  Object.assign(api, {
    company: async () => clone(state.company),
    storefrontSections: async () => clone(state.sections),
    storefrontPreview: async () => home(),
    inventoryProducts: async () => ({ items: products.map(item => ({ ...item, catalog_visible: true })) }),
    inventoryMasterEntries: async kind => ({ items: (kind === "categories" ? categories.map(item => ({ ...item, name: item.category_title })) : brands)
      .map(item => ({ ...item, is_active: true })) }),
    updateCompany: async patch => {
      state.company = { ...state.company, ...clone(patch) };
      state.writes.push({ company: clone(patch) });
      return clone(state.company);
    },
    saveStorefrontSections: async sections => {
      state.sections = sections.map(({ products, categories, brands, ...section }) => clone(section));
      state.writes.push({ sections: clone(state.sections) });
      return { sections: clone(state.sections) };
    },
  });
  window.__tenaliAudit = { state, home, snapshot: () => clone({ ...state, home: home() }) };
  document.getElementById("root").style.display = "none";
  const container = document.createElement("div");
  container.id = "tenant-audit-root";
  document.body.append(container);
  const root = createRoot(container);
  const render = () => root.render(<BrowserRouter basename={tenantBase() || undefined}>
    <NotificationProvider><StorefrontDesignPage /></NotificationProvider>
  </BrowserRouter>);
  window.__tenaliAudit.remount = () => {
    root.render(null);
    window.setTimeout(render, 0);
  };
  render();
  return { template, categories: categories.length, brands: brands.length, products: products.length };
}
