import type { CatalogProduct, CatalogStorefrontPreviewResponse, StorefrontSection, StorefrontTemplate } from "../../types";

type SampleProduct = readonly [name: string, price: string, photo: string];

const samples: Record<StorefrontTemplate, readonly SampleProduct[]> = {
  current: [
    ["Everyday ceramic planter", "549", "photo-1490312278390-ab64016e0aa9"],
    ["Handwoven cotton cushion", "1250", "photo-1600210492486-724fe5c67fb0"],
    ["Blue pottery serving bowl", "1850", "photo-1578749556568-bc2c40e68b61"],
    ["Natural cotton table runner", "1450", "photo-1600166898405-da9535204843"],
    ["Cotton relaxed-fit shirt", "1950", "photo-1521572163474-6864f9cf17ab"],
    ["Everyday leather sling", "2890", "photo-1548036328-c9fa89d128fa"],
    ["Gold-tone statement earrings", "1890", "photo-1611652022419-a9419f74343d"],
    ["Wireless headphones", "1499", "photo-1505740420928-5e560c06d30e"],
  ],
  marketplace: [
    ["Wireless headphones", "1099", "photo-1505740420928-5e560c06d30e"],
    ["Everyday smart watch", "2499", "photo-1523275335684-37898b6baf30"],
    ["Unisex running shoes", "2299", "photo-1542291026-7eec264c27ff"],
    ["Everyday ceramic planter", "549", "photo-1490312278390-ab64016e0aa9"],
    ["Cotton casual T-shirt", "999", "photo-1521572163474-6864f9cf17ab"],
    ["Cotton cushion cover set", "699", "photo-1600210492486-724fe5c67fb0"],
    ["Portable phone charger", "799", "photo-1609091839311-d5365f9ff1c5"],
    ["Everyday shoulder bag", "1299", "photo-1548036328-c9fa89d128fa"],
  ],
  boutique: [
    ["Handwoven kurta set", "4250", "photo-1594633312681-425c7b97ccd1"],
    ["Cotton-silk saree", "3490", "photo-1610030469983-98e550d6193c"],
    ["Embroidered occasion bag", "1250", "photo-1548036328-c9fa89d128fa"],
    ["Everyday linen dress", "2990", "photo-1539109136881-3be0616acf4b"],
    ["Printed festive co-ord", "5499", "photo-1551232864-3f0890e580d9"],
    ["Statement earrings", "1890", "photo-1611652022419-a9419f74343d"],
    ["Relaxed cotton shirt", "1950", "photo-1521572163474-6864f9cf17ab"],
    ["Hand block-printed dupatta", "1499", "photo-1600166898405-da9535204843"],
  ],
  heritage: [
    ["Ajrakh block-print table runner", "2450", "photo-1600166898405-da9535204843"],
    ["Blue pottery serving bowl", "1850", "photo-1578749556568-bc2c40e68b61"],
    ["Handwoven cotton cushion", "1250", "photo-1600210492486-724fe5c67fb0"],
    ["Artisan keepsake box", "2950", "photo-1578500494198-246f612d3b3d"],
    ["Natural-dye cotton stole", "1950", "photo-1600166898405-da9535204843"],
    ["Terracotta bowl set", "790", "photo-1578749556568-bc2c40e68b61"],
    ["Brass table accent", "2290", "photo-1578500494198-246f612d3b3d"],
    ["Handwoven dhurrie rug", "5950", "photo-1600166898405-da9535204843"],
  ],
  supermarket: [
    ["Alphonso mangoes", "349", "photo-1553279768-865429fa0078"],
    ["Fresh toned milk", "29", "photo-1563636619-e9143da7973b"],
    ["Robusta bananas", "49", "photo-1571771894821-ce9b6c11b08e"],
    ["Multigrain sandwich bread", "55", "photo-1509440159596-0249088772ff"],
    ["Fresh spinach bunch", "25", "photo-1597362925123-77861d3fbac7"],
    ["Premium basmati rice", "199", "photo-1586201375761-83865001e31c"],
    ["Mango fruit juice", "110", "photo-1546173159-315724a31696"],
    ["Spiced buttermilk", "15", "photo-1550583724-b2692b85b150"],
  ],
  jewellery: [
    ["Gold floral jhumkas", "28500", "photo-1611652022419-a9419f74343d"],
    ["Temple necklace", "46800", "photo-1617038220319-276d3cfab638"],
    ["Halo stud earrings", "18250", "photo-1611591437281-460bfbe1220a"],
    ["Bridal choker set", "64900", "photo-1630019852942-f89202989a59"],
    ["Lotus pendant", "2450", "photo-1611652022419-a9419f74343d"],
    ["Pearl drop earrings", "3850", "photo-1617038220319-276d3cfab638"],
    ["Bangle pair", "39500", "photo-1611591437281-460bfbe1220a"],
    ["Statement bracelet", "32800", "photo-1630019852942-f89202989a59"],
  ],
};

export function storefrontPreviewSections(
  sections: StorefrontSection[], preview: CatalogStorefrontPreviewResponse, template: StorefrontTemplate,
  useSamples = false,
): StorefrontSection[] {
  const products = new Map(preview.catalog_products.map(product => [product.id, product]));
  const categories = new Map(preview.categories.map(category => [category.id, category]));
  const brands = new Map(preview.brands.map(brand => [brand.id, brand]));
  const sampleProducts: CatalogProduct[] = samples[template].map(([name, price, photo], index) => ({
    id: `storefront-preview-${template}-${index}`,
    portal_product_id: `storefront-preview-${template}-${index}`,
    name, description: "Sample product for design preview only.",
    image_url: `https://images.unsplash.com/${photo}?auto=format&fit=crop&w=700&q=82`,
    image_urls: "", selling_price_display: price, mrp_display: price,
    minimum_order_quantity: 1, best_seller: index < 4, sru_special: index >= 4,
    tags: ["Sample"], home_order: index, is_active: true, stock_qty: 0,
    brand_code: "preview", brand_name: "Sample collection",
    category_slug: "preview", category_title: "Sample collection", category_description: "",
  }));
  let productShelf = 0;
  return sections.map(section => {
    const selectedProducts = (section.product_ids || []).map(id => products.get(id))
      .filter((item): item is CatalogProduct => !!item);
    const offset = section.section_type === "products" ? (productShelf++ % 2) * 4 : 0;
    return {
      ...section,
      products: section.section_type === "products" && section.is_enabled && (useSamples || !section.product_ids?.length)
        ? sampleProducts.slice(offset, offset + 4) : selectedProducts,
      categories: (section.category_ids || []).map(id => categories.get(id)).filter((item): item is NonNullable<typeof item> => !!item),
      brands: (section.brand_ids || []).map(id => brands.get(id)).filter((item): item is NonNullable<typeof item> => !!item),
    };
  });
}
