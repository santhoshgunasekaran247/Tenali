import { useState } from "react";
import { ImageOff, MessageCircle } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import type { CatalogProduct } from "../../../types";
import { moneyLabel, toAssetUrl, whatsappLink } from "../utils";
import { useAuth } from "../../auth";
import { storefrontText } from "../storefrontText";
import { api } from "../../../api";
import { useCart } from "../../cart";
import { QuantityStepper } from "../../../components/QuantityStepper";
import { cartMode, cartWords } from "../../cartMode";

type ProductCardProps = {
  product: CatalogProduct;
  phone: string;
  checkoutEnabled: boolean;
};

export function ProductCard({ product, phone, checkoutEnabled }: ProductCardProps) {
  const navigate = useNavigate();
  const cart = useCart();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const {storefront,user}=useAuth();
  const company=storefront||{company_name:user?.company_name||"Tenali",nickname:undefined};
  const copy=storefront?.storefront_content?.product||{};
  const text=(key:string,fallback:string,variables:Record<string,string|number>={})=>storefrontText(copy[key]||fallback,company,variables);
  const gallery = (product.image_urls || "")
    .split("|")
    .map((img) => img.trim())
    .filter(Boolean);
  const image = gallery[0] || product.image_url;
  const imageSrc = toAssetUrl(image);
  const [failedSrc, setFailedSrc] = useState("");
  const minimum = Math.max(1, product.minimum_order_quantity || 1);
  const mode = cartMode(checkoutEnabled, phone);
  const words = cartWords(mode);
  const listEnabled = mode !== "none";
  const maximum = 100;
  const inCart = cart.items.find(item => item.product_id === product.id && item.variant_id === null);
  const [quantity, setQuantity] = useState(String(minimum));
  const [cartDraft, setCartDraft] = useState<string | null>(null);
  const hasVariants = !!product.variants?.length;
  const changeCartQuantity = (value: string) => {
    setCartDraft(value); setError(""); setMessage("");
    const count = Number(value);
    if (!inCart || !Number.isInteger(count) || count < minimum || count > maximum) return;
    try { cart.setQuantity(inCart, count); setCartDraft(null); }
    catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
  };
  const addToCart = async () => {
    setBusy(true); setMessage(""); setError("");
    try {
      const current = (await api.product(product.id)).product;
      if (current.variants?.length) { navigate(`/products/${product.id}`); return; }
      const count = Number(quantity);
      const floor = current.minimum_order_quantity;
      if (!Number.isInteger(count) || count < floor || count > 100) throw new Error(`Choose ${floor} to 100 whole units.`);
      if (mode === "buy") {
        if (!(Number(current.selling_price_display) > 0)) throw new Error("Contact the store for a quote on this item.");
      }
      cart.add({ product_id: product.id, variant_id: null, quantity: count });
      setMessage(`${count} ${count === 1 ? "unit" : "units"} ${mode === "enquiry" ? "added to enquiry" : "added"}`);
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setBusy(false); }
  };

  return (
    <article
      className="product-card dynamic-card"
      role="link"
      tabIndex={0}
      onClick={() => navigate(`/products/${product.id}`)}
      onKeyDown={(e) => {
        if (e.key === "Enter" && e.target === e.currentTarget) navigate(`/products/${product.id}`);
      }}
    >
      <div className="product-image">
        {imageSrc && imageSrc !== failedSrc ? <img src={imageSrc} alt={product.name} loading="lazy" onError={() => setFailedSrc(imageSrc)} />
          : <span className="product-image-placeholder"><ImageOff size={32} aria-hidden="true" /><span>{imageSrc ? "Image unavailable" : "No image"}</span></span>}
        <div className="product-tags">
          {product.best_seller && <span className="badge-best">{text("best_seller_badge","Best Seller")}</span>}
          {product.sru_special && <span className="badge-special">{text("special_badge","Special")}</span>}
        </div>
        {gallery.length > 1 && <span className="photo-count">{text("photos_count","{count} photos",{count:gallery.length})}</span>}
      </div>
      <div className="product-body">
        <div className="product-type">{product.brand_name || product.category_title}</div>
        <h3 title={product.name}>{product.name}</h3>
        <div className="price-block">
          <strong className="our-price"><span className="sr-only">{text("our_price_label","Our Price")} </span>{moneyLabel(product.selling_price_display)}</strong>
          {product.mrp_display && product.mrp_display !== product.selling_price_display ? <s className="mrp"><span className="sr-only">{text("mrp_label","MRP")} </span>{moneyLabel(product.mrp_display)}</s> : null}
        </div>
        {product.description ? <p title={product.description}>{product.description}</p> : null}
        {mode === "buy" ? <small>Availability checked at checkout</small> : null}
        <div className="product-card-actions" onClick={event => event.stopPropagation()}>
        {listEnabled && !hasVariants ? inCart ? <div className="product-card-incart">
            <span>{words.inList}</span>
            <QuantityStepper label={`Quantity for ${product.name}`} value={cartDraft ?? String(inCart.quantity)} min={minimum} max={maximum}
              onChange={changeCartQuantity} onBelowMin={() => { cart.remove(inCart); setCartDraft(null); setMessage(""); }} />
          </div>
          : <QuantityStepper label={`Quantity for ${product.name}`} value={quantity} min={minimum} max={maximum} disabled={busy}
              onChange={value => { setQuantity(value); setMessage(""); setError(""); }} /> : null}
        <div className="product-card-buttons">
          {listEnabled ? hasVariants ? <button className="btn" type="button" onClick={() => navigate(`/products/${product.id}`)}>Choose options</button>
            : inCart ? <Link className="btn light" to="/cart">{mode === "enquiry" ? "View list" : "View cart"}</Link>
            : <button className={mode === "enquiry" ? "btn enquiry-add" : "btn"} type="button" disabled={busy} onClick={() => void addToCart()}>{busy ? "Adding..." : mode === "enquiry" ? text("add_to_enquiry", words.add) : text("add_to_cart", words.add)}</button> : null}
          {phone?<a
            className={mode === "enquiry" ? "btn whatsapp-btn whatsapp-icon-only" : "btn whatsapp-btn"}
            href={whatsappLink(phone, product.name, product.brand_name || company.nickname || company.company_name, text("whatsapp_message","Hello, I am interested in {product_name} from {brand_name}. Please share pricing, availability and bulk options."))}
            title={text("whatsapp_enquiry","WhatsApp enquiry")}
            onClick={(e) => e.stopPropagation()}
          >
            <MessageCircle size={16} aria-hidden="true" /><span className="whatsapp-btn-label">{text("whatsapp_enquiry","WhatsApp enquiry")}</span>
          </a>:null}
        </div>
        </div>
        {message ? <p className="cart-feedback" role="status" onClick={event => event.stopPropagation()}>{message}. <Link to="/cart">{words.view}</Link></p> : null}
        {error ? <p className="ops-error" role="alert">{error}</p> : null}
      </div>
    </article>
  );
}
