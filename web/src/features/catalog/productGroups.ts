import type { CatalogProduct } from "../../types";

/** Groups products by a label (brand or category), keeping the catalogue order of first appearance. */
export function groupProducts(products: CatalogProduct[], keyOf: (product: CatalogProduct) => string) {
  const groups = new Map<string, CatalogProduct[]>();
  for (const product of products) {
    const name = keyOf(product);
    groups.set(name, [...(groups.get(name) || []), product]);
  }
  return [...groups].map(([name, items]) => ({ name, products: items }));
}
