import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ImageOff } from "lucide-react";
import { SiteFooter } from "../components/SiteFooter";
import { api } from "../api";
import { useAuth } from "../features/auth";
import type { CatalogProduct, Company } from "../types";
import { FALLBACK_EMAIL, FALLBACK_PHONE } from "../features/catalog/constants";
import { moneyLabel, toAssetUrl, whatsappLink } from "../features/catalog/utils";
import { storefrontText } from "../features/catalog/storefrontText";

export function ProductPage() {
  const {storefront}=useAuth();
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

  const displayCompany=company||storefront;
  const productCopy=displayCompany?.storefront_content?.product||{};
  const text=(key:string,fallback:string,variables:Record<string,string|number>={})=>storefrontText(productCopy[key]||fallback,displayCompany||{company_name:"Tenali"},variables);
  if (error) return <main className="loading">{text("product_unavailable","Product unavailable.")} {error}</main>;
  if (!product) return <main className="loading">{text("product_loading","Loading product...")}</main>;

  const mainPhoto = gallery[photoIndex] || product.image_url;
  const variant = product.variants?.find(item=>item.id===variantId);
  const details = {...product,...variant,attributes:{...product.attributes,...variant?.attributes}};
  const mrp = variant ? variant.mrp_display : product.mrp_display;
  const price = variant ? variant.selling_price_display : product.selling_price_display;

  return (
    <>
      <main id="product-page">
        <div className="product-detail-crumb">
          <Link to="/">{text("home_breadcrumb","Home")}</Link>
          <span>/</span>
          <span>{product.brand_name || text("fallback_brand","{nickname}")}</span>
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
                    aria-label={text("view_photo","View photo {number}",{number:index+1})}
                  >
                    <img src={toAssetUrl(image)} alt={`${product.name} photo ${index + 1}`} />
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="detail-copy">
            <p className="eyebrow">
              {product.brand_name || text("fallback_brand","{nickname}")} · {product.category_title}
            </p>
            <h1>{product.name}</h1>
            {product.variants?.length?<label className="catalog-variant-select">{text("variant_label","Size / Colour")}<select value={variantId} onChange={event=>setVariantId(event.target.value)}><option value="">{text("base_product","Base product")}</option>{product.variants.map(item=><option key={item.id} value={item.id}>{item.variant_name}{item.size||item.colour?` - ${[item.size,item.colour].filter(Boolean).join(' / ')}`:''}</option>)}</select></label>:null}
            <div className="price-block">
              <div className="mrp">
                <span>{text("mrp_label","MRP")}</span>
                <s>{moneyLabel(mrp)||"-"}</s>
              </div>
              <div className="our-price">
                <span>{text("our_price_label","Our Price")}</span>
                <strong>{moneyLabel(price)||text("request_quote","Request a quote")}</strong>
              </div>
            </div>
            {details.discount_percent!=null?<p>{Number(details.discount_percent)}{text("discount_suffix","% off MRP")}</p>:null}
            <p className="detail-desc">{variant?.description||product.description}</p>
            <dl className="inventory-specs">{[[text("item_name_label","Item name"),details.item_name],[text("size_label","Size"),details.size],[text("colour_label","Colour"),details.colour],[text("weight_label","Weight (kg)"),details.weight],[text("height_label","Height (cm)"),details.height],[text("width_label","Width (cm)"),details.width],[text("length_label","Length (cm)"),details.length],...Object.entries(details.attributes||{})].filter(([,value])=>value!=null&&value!=='').map(([label,value])=><div key={String(label)}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
            <div className="bulk-pricing">
              <strong>{text("bulk_heading","Better pricing on bulk orders.")}</strong>
              <span>{text("bulk_description","WhatsApp us for best price and price matching with comparable offers.")}</span>
            </div>
            <div className="detail-note">
              {text("price_note","Our listed price is for individual requirements. Bulk orders will have better pricing. WhatsApp us for best quote.")}
            </div>
            <div className="detail-actions">
              {company?.phone?<a
                className="btn whatsapp-btn"
                href={whatsappLink(company.phone, `${product.name}${variant?` - ${variant.variant_name}`:''}`, product.brand_name || company.nickname || company.company_name, text("whatsapp_message","Hello, I am interested in {product_name} from {brand_name}. Please share pricing, availability and bulk options."))}
              >
                {text("whatsapp_action","WhatsApp for best price")}
              </a>:null}
              {company?.email?<a className="link" href={`mailto:${company.email}`}>
                {company.email}
              </a>:null}
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
