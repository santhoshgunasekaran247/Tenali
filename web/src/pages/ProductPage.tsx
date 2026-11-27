import { FloatingAlert } from "../components/Notifications";
import { BulkPricingNote } from "../components/BulkPricingNote";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ImageOff, ListPlus, MessageCircle, ShoppingCart } from "lucide-react";
import { SiteFooter } from "../components/SiteFooter";
import { api } from "../api";
import { useAuth } from "../features/auth";
import type { CatalogProduct, Company } from "../types";
import { FALLBACK_EMAIL, FALLBACK_PHONE } from "../features/catalog/constants";
import { moneyLabel, toAssetUrl, whatsappLink } from "../features/catalog/utils";
import { NearbyStores } from "../components/NearbyStores";
import { storefrontText } from "../features/catalog/storefrontText";
import { useCheckoutAvailability } from "../features/useCheckoutAvailability";
import { cartMode, cartWords } from "../features/cartMode";
import { useCart } from "../features/cart";
import { QuantityStepper } from "../components/QuantityStepper";
import { storefrontDisplay } from "../features/catalog/storefrontDisplay";
import { pickVariant, shortVariantLabel, variantGallery, variantLayout, variantOptions, type VariantOption } from "../features/catalog/variants";

export function ProductPage() {
  const {storefront}=useAuth();
  const cart = useCart();
  const [search, setSearch] = useSearchParams();
  const { productId } = useParams();
  const [product, setProduct] = useState<CatalogProduct>();
  const [company,setCompany]=useState<Company>();
  const [error, setError] = useState<string>();
  const [photoIndex, setPhotoIndex] = useState(0);
  const [variantId, setVariantId] = useState(search.get("variant") || "");
  const [quantity, setQuantity] = useState("1");
  const [cartMessage, setCartMessage] = useState("");
  const [cartError, setCartError] = useState("");

  useEffect(() => {
    if (!productId) return;
    let active = true;
    setProduct(undefined); setError(undefined); setVariantId(search.get("variant") || ""); setPhotoIndex(0);
    api
      .product(productId)
      .then((r) => {if (active) {setProduct(r.product);setCompany(r.company);setQuantity(String(r.product.minimum_order_quantity));setCartMessage("");setCartError("");}})
      .catch((e: Error) => {if (active) setError(e.message);});
    return () => {active = false;};
  }, [productId]);
  const { availability, error: checkoutError } = useCheckoutAvailability(storefront?.id);
  const checkoutEnabled = !!availability?.enabled;

  const gallery = useMemo(() => {
    if (!product) return [];
    const photos = product.gallery || [];
    const parentGallery = photos.length ? photos : product.image_url ? [product.image_url] : [];
    return variantGallery(parentGallery, product.variants?.find(item => item.id === variantId)?.image_url);
  }, [product, variantId]);

  const displayCompany=company||storefront;
  const display=storefrontDisplay(displayCompany);
  const template=displayCompany?.storefront_template||"current";
  const whatsappPhone=display.whatsapp_enquiry_enabled?company?.phone:undefined;
  const mode = availability || checkoutError ? cartMode(checkoutEnabled, whatsappPhone) : null;
  const words = cartWords(mode);
  const productCopy=displayCompany?.storefront_content?.product||{};
  const text=(key:string,fallback:string,variables:Record<string,string|number>={})=>storefrontText(productCopy[key]||fallback,displayCompany||{company_name:"Tenali"},variables);
  if (error) return <main className="loading">{text("product_unavailable","Product unavailable.")} {error}</main>;
  if (!product) return <main className="loading">{text("product_loading","Loading product...")}</main>;

  const mainPhoto = gallery[photoIndex] || product.image_url;
  const variant = product.variants?.find(item=>item.id===variantId);
  const options = product.variants?.length ? variantOptions(product, product.variants, [product.size, product.colour].filter(Boolean).join(" / ") || text("parent_variant_label","Standard")) : [];
  const layout = variantLayout(options);
  const selectedOption = options.find(option => option.id === (variant?.id || ""));
  const chooseVariant = (id: string) => {
    setVariantId(id); setPhotoIndex(0); setCartMessage(""); setCartError("");
    const next = new URLSearchParams(search);
    if (id) next.set("variant", id); else next.delete("variant");
    setSearch(next, { replace: true });
  };
  const dimensionLabel = (key: string) => key === "size" ? text("size_label","Size") : key === "colour" ? text("colour_label","Colour") : key;
  const optionChip = (option: VariantOption | undefined, label: string, pressed: boolean, key: string) => {
    return <button key={key} type="button" className="variant-chip" aria-pressed={pressed}
      disabled={!option}
      onClick={() => { if (option && !pressed) chooseVariant(option.id); }}>{label}</button>;
  };
  const details = {...product,...variant,attributes:{...product.attributes,...variant?.attributes}};
  const mrp = variant ? variant.mrp_display : product.mrp_display;
  const price = variant ? variant.selling_price_display : product.selling_price_display;
  const minimum = product.minimum_order_quantity;
  const canPurchase = Number(price) > 0;
  const inCart = cart.items.find(item => item.product_id === product.id && item.variant_id === (variantId || null))?.quantity || 0;
  const specs = [[text("item_name_label","Item name"),details.item_name],[text("size_label","Size"),details.size],[text("colour_label","Colour"),details.colour],[text("weight_label","Weight (kg)"),details.weight],[text("height_label","Height (cm)"),details.height],[text("width_label","Width (cm)"),details.width],[text("length_label","Length (cm)"),details.length],...Object.entries(details.attributes||{})].filter(([,value])=>value!=null&&value!=="");
  const enquiryLink = whatsappPhone ? whatsappLink(whatsappPhone, `${product.name}${variant?` - ${variant.variant_name}`:""}`, product.brand_name || company?.nickname || company?.company_name || "", text("whatsapp_message","Hello, I am interested in {product_name} from {brand_name}. Please share pricing, availability and bulk options.")) : "";
  const enquiring = mode === "enquiry";
  const needsVariant = !enquiring && !!product.variants?.length && !variantId;
  const canAdd = enquiring || canPurchase;
  const addToCart = () => {
    setCartError(""); setCartMessage("");
    try {
      const count = Number(quantity);
      if (!Number.isInteger(count) || count < minimum || count > 100) throw new Error(`Choose ${minimum} to 100 whole units.`);
      cart.add({ product_id: product.id, variant_id: variantId || null, quantity: count });
      setCartMessage(`${count} ${count === 1 ? "unit" : "units"} ${words.added}.`);
    } catch (failure) { setCartError(String(failure)); }
  };
  return (
    <>
      <main id="product-page" className={`storefront-product-page storefront-commerce-page storefront-product-page--${template}`}>
        <div className="product-detail-crumb">
          <Link to="/">{text("home_breadcrumb","Home")}</Link>
          <span>/</span>
          <span>{product.brand_name || text("fallback_brand","{nickname}")}</span>
          <span>/</span>
          <span>{product.name}</span>
        </div>
        <section className={`product-detail product-detail--${template}`}>
          <div className="detail-gallery">
            <div className="detail-image-wrap" style={{ backgroundColor: product.image_background || "#ffffff" }}>
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
            {template === "boutique" ? <header className="product-theme-title product-theme-title--boutique">
              <p className="eyebrow">{product.brand_name || text("fallback_brand","{nickname}")}</p><h1>{product.name}</h1>
              <span>{product.category_title}</span>
            </header> : template === "heritage" ? <header className="product-theme-title product-theme-title--heritage">
              <span className="heritage-catalog-rule" aria-hidden="true" /><p className="eyebrow">{product.category_title}</p>
              <h1>{product.name}</h1><p>{product.brand_name || text("fallback_brand","{nickname}")}</p>
            </header> : template === "supermarket" ? <header className="product-theme-title product-theme-title--supermarket">
              <span>{product.category_title}</span><h1>{product.name}</h1>
              <p>{product.brand_name || text("fallback_brand","{nickname}")}</p>
            </header> : template === "jewellery" ? <header className="product-theme-title product-theme-title--jewellery">
              <p className="eyebrow">{product.brand_name || text("fallback_brand","{nickname}")}</p>
              <span className="jewellery-divider" aria-hidden="true" /><h1>{product.name}</h1>
              <span className="jewellery-product-collection">{product.category_title}</span>
            </header> : template === "marketplace" || template === "category_first" ? <header className="product-theme-title product-theme-title--marketplace">
              <p className="eyebrow">{product.brand_name || text("fallback_brand","{nickname}")}</p>
              <h1>{product.name}</h1><span>{product.category_title}</span>
            </header> : <>
              <p className="eyebrow">{product.brand_name || text("fallback_brand","{nickname}")} · {product.category_title}</p>
              <h1>{product.name}</h1>
            </>}
            {options.length?<div className="variant-options" role="group" aria-label={text("variant_label","Size / Colour")}>
              {layout.kind === "dimensions" ? layout.dimensions.map(dimension => <div className="variant-option-row" key={dimension.key}>
                <span className="variant-option-label">{dimensionLabel(dimension.key)}: <strong>{selectedOption?.values[dimension.key]}</strong></span>
                <div className="variant-chips">{dimension.values.map(value => optionChip(
                  pickVariant(options, selectedOption, layout.dimensions, dimension.key, value), value,
                  selectedOption?.values[dimension.key] === value, value))}</div>
              </div>) : <div className="variant-option-row">
                <span className="variant-option-label">{text("variant_label","Size / Colour")}: <strong>{selectedOption ? shortVariantLabel(selectedOption.label, product.name) : ""}</strong></span>
                <div className="variant-chips">{options.map(option => optionChip(option, shortVariantLabel(option.label, product.name), option.id === (variant?.id || ""), option.id || "parent"))}</div>
              </div>}
            </div>:null}
            <div className="price-block detail-price">
              <div className="our-price">
                <span>{text("our_price_label","Our Price")}</span>
                <strong>{moneyLabel(price)||text("request_quote","Request a quote")}</strong>
              </div>
              {moneyLabel(mrp)?<div className="mrp">
                <span>{text("mrp_label","MRP")}</span>
                <s>{moneyLabel(mrp)}</s>
              </div>:null}
              {details.discount_percent!=null&&Number(details.discount_percent)>0?<span className="detail-discount">{Number(details.discount_percent)}{text("discount_suffix","% off MRP")}</span>:null}
              <span className="detail-stock">{canPurchase ? mode === "buy" ? "Availability checked at checkout" : "Contact store for availability" : text("on_request","On request")}</span>
            </div>
            {display.show_bulk_pricing ? <BulkPricingNote heading={text("bulk_heading","Better pricing on bulk orders.")} description={text("bulk_description","WhatsApp us for best price and price matching with comparable offers.")} /> : null}
            <div className="detail-actions">
              {mode === "buy" || mode === "enquiry" ? <div className={`product-cart-controls${enquiring ? " is-enquiry" : ""}`}>
                <div className="product-cart-row">
                  <QuantityStepper label="Quantity" value={quantity} min={minimum} max={100}
                    onChange={value => { setQuantity(value); setCartMessage(""); }} />
                  {needsVariant || !canAdd ? null : enquiring
                    ? <button className="btn enquiry-add" type="button" onClick={addToCart}><ListPlus size={16} aria-hidden="true" />{text("add_to_enquiry", words.add)}</button>
                    : <button className="btn" type="button" onClick={addToCart}><ShoppingCart size={16} aria-hidden="true" />{text("add_to_cart", words.add)}</button>}
                  {whatsappPhone?<a className="btn whatsapp-btn detail-whatsapp" href={enquiryLink} title={text("whatsapp_action","WhatsApp for best price")} aria-label={text("whatsapp_action","WhatsApp for best price")}>
                    <MessageCircle size={16} aria-hidden="true" /><span>{enquiring ? text("whatsapp_ask_now","Ask now") : text("whatsapp_short","WhatsApp")}</span>
                  </a>:null}
                </div>
                <p className="product-cart-minimum">
                  {needsVariant ? <strong>{text("checkout_variant_required","Select a size / colour to add to your cart.")} </strong>
                    : !canAdd ? <strong>Contact the store for a quote on this item. </strong> : null}
                  {enquiring ? <>{text("enquiry_hint","Collect products and quantities, then send them in one WhatsApp message. No payment is taken.")} </> : null}
                  Min. {minimum} {minimum === 1 ? "unit" : "units"}{product.variants?.length ? " per size / colour" : ""}
                  {inCart ? <> · {words.inList}: <strong>{inCart}</strong></> : null} · <Link to="/cart">{words.view}</Link>
                </p>
                {cartMessage ? <p className="cart-feedback" role="status">{cartMessage} <Link to="/cart">{enquiring ? "Send the list on WhatsApp" : "Review cart"}</Link></p> : null}
                {cartError ? <FloatingAlert>{cartError}</FloatingAlert> : null}
              </div> : null}
            </div>
            {checkoutError?<p role="alert" className="ops-error">Online checkout unavailable: {checkoutError}.{whatsappPhone ? " You can still enquire with the store." : ""}</p>:null}
            {(variant?.description||product.description)?<p className="detail-desc">{variant?.description||product.description}</p>:null}
            {specs.length?<details className="detail-more" open>
              <summary>{text("details_heading","Product details")}</summary>
              <dl className="inventory-specs">{specs.map(([label,value])=><div key={String(label)}><dt>{label}</dt><dd>{String(value)}</dd></div>)}</dl>
            </details>:null}
            {product.id?<details className="detail-more" open>
              <summary>{text("pickup_heading","Pick up at a nearby store")}</summary>
              <NearbyStores productId={product.id} variantId={variantId||null} productName={`${product.name}${variant?` - ${variant.variant_name}`:''}`} quantity={Math.max(1,Number(quantity)||1)} checkoutEnabled={checkoutEnabled} whatsappEnabled={display.whatsapp_enquiry_enabled}/>
            </details>:null}
            <details className="detail-more" open>
              <summary>{text("help_heading","Pricing, delivery & help")}</summary>
              <p>{text("price_note","Our listed price is for individual requirements. Bulk orders will have better pricing. WhatsApp us for best quote.")}</p>
              {checkoutEnabled?<p>{text("online_purchase_help","Add products to your cart, change quantities and pay for them together. Sign in at checkout; delivery charges are shown before payment.")}</p>
                :enquiring?<p>{text("enquiry_list_help","Add products to your enquiry list with the quantities you need, then send the whole list to the store in one WhatsApp message. The store replies with price and availability.")}</p>:null}
              {whatsappPhone?<p>{text("whatsapp_purchase_help","Use WhatsApp for bulk pricing, customisation or availability questions. An enquiry does not place an order or take payment.")}</p>:null}
              {company?.email?<p><a className="link" href={`mailto:${company.email}`}>{company.email}</a></p>:null}
            </details>
          </div>
        </section>
      </main>
      <SiteFooter company={company} />
    </>
  );
}
