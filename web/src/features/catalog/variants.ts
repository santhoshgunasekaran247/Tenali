export type VariantSource = {
  id?: string | null;
  variant_name?: string | null;
  size?: string | null;
  colour?: string | null;
  attributes?: Record<string, unknown> | null;
  stock_qty?: number | string | null;
};

export type VariantOption = { id: string; label: string; values: Record<string, string>; stock: number | null };
export type VariantDimension = { key: string; values: string[] };
/** Either value groups (Size, Colour, ...) that identify every option, or one row of named options. */
export type VariantLayout = { kind: "dimensions"; dimensions: VariantDimension[] } | { kind: "names" };

export function variantGallery(parentGallery: string[], variantImage?: string | null): string[] {
  return variantImage ? [variantImage, ...parentGallery.filter(image => image !== variantImage)] : parentGallery;
}

const clean = (value: unknown) => value == null ? "" : String(value).trim();

function valuesOf(source: VariantSource): Record<string, string> {
  const values: Record<string, string> = {};
  if (clean(source.size)) values.size = clean(source.size);
  if (clean(source.colour)) values.colour = clean(source.colour);
  for (const [key, value] of Object.entries(source.attributes || {})) {
    if (clean(key) && clean(value) && !(key in values)) values[key] = clean(value);
  }
  return values;
}

/** The parent product is the first option (id ""), followed by its active variants. */
export function variantOptions(parent: VariantSource & { name: string }, variants: VariantSource[], parentLabel = parent.name): VariantOption[] {
  return [
    { id: "", label: parentLabel, values: valuesOf(parent), stock: null },
    ...variants.filter(variant => variant.id).map(variant => ({
      id: String(variant.id),
      label: clean(variant.variant_name) || [variant.size, variant.colour].map(clean).filter(Boolean).join(" / ") || "Option",
      values: valuesOf(variant),
      stock: variant.stock_qty == null ? null : Number(variant.stock_qty),
    })),
  ];
}

/** "Brass Lotus Diya - 3.5 inch" shows as "3.5 inch" next to the product title; other labels stay as they are. */
export function shortVariantLabel(label: string, productName: string): string {
  const name = clean(productName);
  if (!name || !label.toLowerCase().startsWith(name.toLowerCase())) return label;
  const rest = label.slice(name.length).replace(/^[\s\-\u2013\u2014:/|,()]+/, "").replace(/\)$/, "").trim();
  return rest || label;
}

export function variantLayout(options: VariantOption[]): VariantLayout {
  const keys = [...new Set(options.flatMap(option => Object.keys(option.values)))];
  const dimensions = keys
    .filter(key => options.every(option => option.values[key]))
    .map(key => ({ key, values: [...new Set(options.map(option => option.values[key]))] }))
    .filter(dimension => dimension.values.length > 1);
  const signature = (option: VariantOption) => JSON.stringify(dimensions.map(dimension => option.values[dimension.key]));
  // Value groups only work when every option, the parent included, has a distinct combination of values.
  if (dimensions.length && new Set(options.map(signature)).size === options.length) return { kind: "dimensions", dimensions };
  return { kind: "names" };
}

/** Option for a clicked value: it must have that value and should keep as many of the current choices as possible. */
export function pickVariant(options: VariantOption[], current: VariantOption | undefined, dimensions: VariantDimension[], key: string, value: string): VariantOption | undefined {
  const candidates = options.filter(option => option.values[key] === value);
  const score = (option: VariantOption) => dimensions.filter(dimension => dimension.key !== key && current && option.values[dimension.key] === current.values[dimension.key]).length * 2
    + (option.stock == null || option.stock > 0 ? 1 : 0);
  return candidates.reduce<VariantOption | undefined>((best, option) => !best || score(option) > score(best) ? option : best, undefined);
}
