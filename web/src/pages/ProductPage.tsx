import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ImageOff } from "lucide-react";
import { SiteFooter } from "../components/SiteFooter";
import { api } from "../api";
import type { CatalogProduct, Company } from "../types";
import { FALLBACK_EMAIL, FALLBACK_PHONE } from "../features/catalog/constants";
import { moneyLabel, toAssetUrl, whatsappLink } from "../features/catalog/utils";

export function ProductPage() {
  const { productId } = useParams();
  const [product, setProduct] = useState<CatalogProduct>();
  const [company,setCompany]=useState<Company>();
  const [error, setError] = useState<string>();
  const [photoIndex, setPhotoIndex] = useState(0);
  const [variantId, setVariantId] = useState("");

  useEffect(() => {
    if (!productId) return;
    api
      .product(productId)
      .then((r) => {setProduct(r.product);setCompany(r.company);})
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
  const variant = product.variants?.find(item=>item.id===variantId);
  const details = {...product,...variant,attributes:{...product.attributes,...variant?.attributes}};
  const mrp = variant ? variant.mrp_display : product.mrp_display;
  const price = variant ? variant.selling_price_display : product.selling_price_display;

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
              {mainPhoto?<img src={toAssetUrl(mainPhoto)} alt={product.name} />:<ImageOff size={48} aria-label="No product image"/>}
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
            {product.variants?.length?<label className="catalog-variant-select">Size / Colour<select value={variantId} onChange={event=>setVariantId(event.target.value)}><option value="">Base product</option>{product.variants.map(item=><option key={item.id} value={item.id}>{item.variant_name}{item.size||item.colour?` - ${[item.size,item.colour].filter(Boolean).join(' / ')}`:''}</option>)}</select></label>:null}
            <div className="price-block">
              <div className="mrp">
                <span>MRP</span>
                <s>{moneyLabel(mrp)||"-"}</s>
              </div>
              <div className="our-price">
                <span>Our Price</span>
                <strong>{moneyLabel(price)||"Request a quote"}</strong>
              </div>
            </div>
            {details.discount_percent!=null?<p>{Number(details.discount_percent)}% off MRP</p>:null}
            <p className="detail-desc">{variant?.description||product.description}</p>
            <dl className="inventory-specs">{[['Item name',details.item_name],['Size',details.size],['Colour',details.colour],['Weight (kg)',details.weight],['Height (cm)',details.height],['Width (cm)',details.width],['Length (cm)',details.length],...Object.entries(details.attributes||{})].filter(([,value])=>value!=null&&value!=='').map(([label,value])=><div key={String(label)}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
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
                href={whatsappLink(company?.phone||FALLBACK_PHONE, `${product.name}${variant?` - ${variant.variant_name}`:''}`, product.brand_name || "SRU Collection")}
              >
                WhatsApp for best price
              </a>
              <a className="link" href={`mailto:${company?.email||FALLBACK_EMAIL}`}>
                {company?.email||FALLBACK_EMAIL}
              </a>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
