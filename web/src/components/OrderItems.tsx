import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Package } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../features/auth";
import { toAssetUrl } from "../features/catalog/utils";
import { rupees, type ShopItem } from "../features/shop";
import type { CatalogProduct } from "../types";

type ProductReference = { product_id: string; variant_id: string | null };

export function productPagePath(item: ProductReference): string {
  return `/products/${encodeURIComponent(item.product_id)}${item.variant_id ? `?variant=${encodeURIComponent(item.variant_id)}` : ""}`;
}

export function productImage(product?: CatalogProduct, variantId?: string | null): string {
  return product?.variants?.find(variant => variant.id === variantId)?.image_url || product?.gallery?.[0] ||
    product?.image_urls?.split("|").map(image => image.trim()).find(Boolean) || product?.image_url || "";
}

export function ProductImageLink({ item, name, imageUrl, className = "order-item-image" }: {
  item: ProductReference; name: string; imageUrl?: string; className?: string;
}) {
  const { storefront, user } = useAuth();
  const companyId = storefront?.id || user?.company_id;
  const [photo, setPhoto] = useState({ url: "", error: "", key: "" });
  const key = `${companyId}:${item.product_id}:${item.variant_id || ""}`;
  useEffect(() => {
    if (imageUrl !== undefined || !companyId) return;
    let active = true;
    void api.product(item.product_id).then(result => {
      if (active) setPhoto({ url: productImage(result.product, item.variant_id), error: "", key });
    }).catch(failure => {
      if (active) setPhoto({ url: "", error: failure instanceof Error ? failure.message : String(failure), key });
    });
    return () => { active = false; };
  }, [key, imageUrl, companyId, item.product_id, item.variant_id]);
  const url = imageUrl ?? (photo.key === key ? photo.url : "");
  const src = toAssetUrl(url);
  const [failedSrc, setFailedSrc] = useState("");
  const error = photo.key === key ? photo.error : "";
  const unavailable = !!error || (!!src && failedSrc === src);
  return <Link className={className} to={productPagePath(item)} aria-label={`View ${name}`} title={error ? `Image unavailable: ${error}` : `View ${name}`}>
    {src && failedSrc !== src ? <img src={src} alt={name} loading="lazy" decoding="async" onError={() => setFailedSrc(src)} />
      : <span className="product-image-placeholder"><Package size={24} aria-hidden="true" /><span>{unavailable ? "Image unavailable" : "No image"}</span></span>}
  </Link>;
}

export function OrderItems({ items }: { items: ShopItem[] }) {
  return <ul className="order-product-items">{items.map(item => <li key={`${item.product_id}:${item.variant_id}`}>
    <ProductImageLink item={item} name={item.name} />
    <div className="order-product-description"><Link to={productPagePath(item)}>{item.name}</Link><span>Qty {item.quantity} · {rupees(item.unit_paise)} each</span></div>
    <strong className="order-product-total">{rupees(item.unit_paise * item.quantity)}</strong>
  </li>)}</ul>;
}
