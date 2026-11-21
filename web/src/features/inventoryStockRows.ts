import type { InventoryProduct } from "../types";

export function inventoryStockRows(product: InventoryProduct) {
  return [
    ...product.store_stocks.map(store => ({ key: `${product.id}:${store.store_id}`, store, name: "Base product" })),
    ...product.variants.flatMap(variant => variant.store_stocks.map(store => ({
      key: `${variant.id}:${store.store_id}`, store, name: variant.variant_name,
    }))),
  ];
}
