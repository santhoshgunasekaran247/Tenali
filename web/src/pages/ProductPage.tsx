import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { SiteFooter } from "../components/SiteFooter";
import { api } from "../api";
import type { CatalogProduct } from "../types";
import { FALLBACK_EMAIL, FALLBACK_PHONE } from "../features/catalog/constants";
import { moneyLabel, toAssetUrl, whatsappLink } from "../features/catalog/utils";

export function ProductPage() {
  const { productId } = useParams();
  const [product, setProduct] = useState<CatalogProduct>();
  const [error, setError] = useState<string>();
  const [photoIndex, setPhotoIndex] = useState(0);

  useEffect(() => {
    if (!productId) return;
    api
      .product(productId)
      .then((r) => setProduct(r.product))
      .catch((e: Error) => setError(e.message));
  }, [productId]);

  const gallery = useMemo(() => {
    if (!product) return [];
    const photos = product.gallery || [];
    if (photos.length) return photos;
    if (product.image_url) return [product.image_url];
    return [];
  }, [product]);

  if (error) return <main className="loading">Product unavailable. {error}</main>;
  if (!product) return <main className="loading">Loading product...</main>;

  const mainPhoto = gallery[photoIndex] || product.image_url;

  return (
    <>
      <main id="product-page">
        <div className="product-detail-crumb">
          <Link to="/">Home</Link>
          <span>/</span>
          <span>{product.brand_name || "SRU"}</span>
          <span>/</span>
          <span>{product.name}</span>
        </div>
        <section className="product-detail">
          <div className="detail-gallery">
            <div className="detail-image-wrap">
              <img src={toAssetUrl(mainPhoto)} alt={product.name} />
            </div>
            {gallery.length > 1 && (
              <div className="product-thumbs">
                {gallery.map((image, index) => (
                  <button
                    className={index === photoIndex ? "product-thumb active" : "product-thumb"}
                    type="button"
                    key={`${image}-${index}`}
                    onClick={() => setPhotoIndex(index)}
                    aria-label={`View photo ${index + 1}`}
                  >
                    <img src={toAssetUrl(image)} alt={`${product.name} photo ${index + 1}`} />
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="detail-copy">
            <p className="eyebrow">
              {product.brand_name || "SRU"} · {product.category_title}
            </p>
            <h1>{product.name}</h1>
            <div className="price-block">
              <div className="mrp">
                <span>MRP</span>
                <s>{moneyLabel(product.mrp_display)}</s>
              </div>
              <div className="our-price">
                <span>Our Price</span>
                <strong>{moneyLabel(product.selling_price_display)}</strong>
              </div>
            </div>
            <p className="sample-price-note">Sample pricing shown for layout and catalogue demonstration.</p>
            <p className="detail-desc">{product.description}</p>
            <div className="bulk-pricing">
              <strong>Better pricing on bulk orders.</strong>
              <span>WhatsApp us for best price and price matching with comparable offers.</span>
            </div>
            <div className="detail-note">
              Our listed price is for individual requirements. Bulk orders will have better pricing. WhatsApp us for best quote.
            </div>
            <div className="detail-actions">
              <a
                className="btn whatsapp-btn"
                href={whatsappLink(FALLBACK_PHONE, product.name, product.brand_name || "SRU Collection")}
              >
                WhatsApp for best price
              </a>
              <a className="link" href={`mailto:${FALLBACK_EMAIL}`}>
                {FALLBACK_EMAIL}
              </a>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
