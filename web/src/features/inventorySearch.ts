import type { InventoryProduct } from "../types";

export function matchesInventorySearch(product: InventoryProduct, search: string): boolean {
  const terms = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const fields = [
    product.name, product.item_name, product.sku, product.portal_product_id,
    product.brand_name, product.category_name,
    ...product.variants.flatMap(variant => [variant.variant_name, variant.sku, variant.size, variant.colour]),
  ].filter(Boolean).join(" ").toLowerCase();
  return terms.every(term => fields.includes(term));
}
