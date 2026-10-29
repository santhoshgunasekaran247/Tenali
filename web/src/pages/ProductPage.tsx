import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ImageOff } from "lucide-react";
import { SiteFooter } from "../components/SiteFooter";
import { api } from "../api";
import { useAuth } from "../features/auth";
import type { CatalogProduct, Company } from "../types";
import { FALLBACK_EMAIL, FALLBACK_PHONE } from "../features/catalog/constants";
import { moneyLabel, toAssetUrl, whatsappLink } from "../features/catalog/utils";
import { storefrontText } from "../features/catalog/storefrontText";
import { accountRequest } from "../features/shop";
import { useCart } from "../features/cart";

export function ProductPage() {
  const {storefront}=useAuth();
  const cart = useCart();
  const [search] = useSearchParams();
  const { productId } = useParams();
  const [product, setProduct] = useState<CatalogProduct>();
  const [company,setCompany]=useState<Company>();
  const [error, setError] = useState<string>();
  const [photoIndex, setPhotoIndex] = useState(0);
  const [variantId, setVariantId] = useState(search.get("variant") || "");
  const [quantity, setQuantity] = useState("1");
  const [cartMessage, setCartMessage] = useState("");
  const [cartError, setCartError] = useState("");
  const [checkoutEnabled, setCheckoutEnabled] = useState(false);
  const [checkoutError, setCheckoutError] = useState("");

  useEffect(() => {
    if (!productId) return;
    let active = true;
    setProduct(undefined); setError(undefined); setVariantId(search.get("variant") || "");
    api
      .product(productId)
      .then((r) => {if (active) {setProduct(r.product);setCompany(r.company);setQuantity(String(r.product.minimum_order_quantity));setCartMessage("");setCartError("");}})
      .catch((e: Error) => {if (active) setError(e.message);});
    return () => {active = false;};
  }, [productId]);
  useEffect(() => {
    accountRequest<{enabled:boolean}>("/availability").then(result=>setCheckoutEnabled(result.enabled))
      .catch(failure=>setCheckoutError(String(failure)));
  }, []);

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
  const minimum = product.minimum_order_quantity;
  const stock = variant ? variant.stock_qty : product.stock_qty;
  const canPurchase = Number(price) > 0 && Number(stock) >= minimum;
  const addToCart = () => {
    setCartError(""); setCartMessage("");
    try {
      const count = Number(quantity);
      if (!Number.isInteger(count) || count < minimum || count > 100) throw new Error(`Choose ${minimum} to 100 whole units.`);
      if (count > Number(stock)) throw new Error("Not enough stock for this quantity. Choose fewer units or contact the store.");
      const existing = cart.items.find(item => item.product_id === product.id && item.variant_id === (variantId || null));
      if (count + (existing?.quantity || 0) > Number(stock)) throw new Error("Your cart already contains this item. Reduce the quantity or update it in your cart.");
      cart.add({ product_id: product.id, variant_id: variantId || null, quantity: count });
      setCartMessage(`${count} units added to your cart.`);
    } catch (failure) { setCartError(String(failure)); }
  };

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
            {product.variants?.length?<label className="catalog-variant-select">{text("variant_label","Size / Colour")}<select value={variantId} onChange={event=>{setVariantId(event.target.value);setCartMessage("");setCartError("");}}><option value="">{text("base_product","Base product")}</option>{product.variants.map(item=><option key={item.id} value={item.id}>{item.variant_name}{item.size||item.colour?` - ${[item.size,item.colour].filter(Boolean).join(' / ')}`:''}</option>)}</select></label>:null}
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
              {checkoutEnabled ? <div className="product-cart-controls">
                <p>Minimum order: <strong>{minimum} units</strong>{product.variants?.length ? " per size / colour" : ""}</p>
                <label>Quantity<input type="number" min={minimum} max={100} step={1} value={quantity} onChange={event => { setQuantity(event.target.value); setCartMessage(""); }} /></label>
                {product.variants?.length && !variantId ? <p>{text("checkout_variant_required","Select a size / colour to add to your cart.")}</p>
                  : canPurchase ? <button className="btn" type="button" onClick={addToCart}>{text("add_to_cart","Add to Cart")}</button>
                    : <p>{Number(price) > 0 ? "Not enough stock for the minimum order. Contact the store." : "Contact the store for a quote on this item."}</p>}
                <Link className="btn light" to="/cart">View cart</Link>
                {cartMessage ? <p role="status">{cartMessage} <Link to="/cart">Review cart &amp; checkout</Link></p> : null}
                {cartError ? <p role="alert" className="ops-error">{cartError}</p> : null}
              </div> : null}
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
            <div className="product-purchase-help">
              {checkoutEnabled?<p>{text("online_purchase_help","Add products to your cart, change quantities and pay for them together. Sign in at checkout; delivery charges are shown before payment.")}</p>:null}
              {company?.phone?<p>{text("whatsapp_purchase_help","Use WhatsApp for bulk pricing, customisation or availability questions. An enquiry does not place an order or take payment.")}</p>:null}
            </div>
            {checkoutError?<p role="alert" className="ops-error">Online checkout unavailable: {checkoutError}. You can still enquire with the store.</p>:null}
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
