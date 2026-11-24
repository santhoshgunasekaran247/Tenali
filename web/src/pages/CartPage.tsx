import { FloatingAlert } from "../components/Notifications";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../features/auth";
import { cartItemKey, useCart } from "../features/cart";
import { rupees } from "../features/shop";
import type { CatalogProduct } from "../types";
import { MessageCircle, Trash2 } from "lucide-react";
import { useCartMode } from "../features/useCheckoutAvailability";
import { cartWords, enquiryMessage, enquiryWhatsappLink } from "../features/cartMode";
import { ProductImageLink, productImage, productPagePath } from "../components/OrderItems";
import { QuantityStepper } from "../components/QuantityStepper";
import { SiteFooter } from "../components/SiteFooter";

export function CartPage() {
  const { storefront, loading } = useAuth();
  const cart = useCart();
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const [products, setProducts] = useState<Record<string, CatalogProduct>>({});
  const [failures, setFailures] = useState<Record<string, string>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [ready, setReady] = useState(false);
  const { mode, phone, availability } = useCartMode();
  const enabled = !!availability?.enabled;
  const shipping = availability?.shipping_paise || 0;
  const enquiring = mode === "enquiry";
  const words = cartWords(mode);
  const [error, setError] = useState("");
  const productIds = [...new Set(cart.items.map(item => item.product_id))].sort().join(",");
  useEffect(() => {
    if (!storefront) return;
    let active = true;
    setReady(false); setError("");
    void Promise.all(productIds.split(",").filter(Boolean).map(async id => {
      try { return { id, product: (await api.product(id)).product, error: "" }; }
      catch (failure) { return { id, product: undefined, error: String(failure) }; }
    })).then(results => {
      if (!active) return;
      setProducts(Object.fromEntries(results.flatMap(result => result.product ? [[result.id, result.product]] : [])));
      setFailures(Object.fromEntries(results.filter(result => result.error).map(result => [result.id, result.error])));
      setReady(true);
    }).catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [storefront?.id, productIds]);
  const rows = cart.items.map(item => {
    const product = products[item.product_id];
    const variant = product?.variants?.find(entry => entry.id === item.variant_id);
    const price = variant ? variant.selling_price_display : product?.selling_price_display;
    const unit = Number(price);
    const quantity = Number(drafts[cartItemKey(item)] ?? item.quantity);
    const minimum = product?.minimum_order_quantity || 1;
    const unavailable = !product || (item.variant_id ? !variant : !enquiring && !!product.variants?.length);
    const problem = unavailable ? failures[item.product_id] || "This product or size / colour is no longer available. Remove it and choose again."
      : !Number.isInteger(quantity) || quantity < minimum || quantity > 100 ? `Choose ${minimum} to 100 whole units.`
      // Enquiries may include items priced on request.
      : enquiring ? ""
      : !Number.isFinite(unit) || unit <= 0 ? "Contact the store for a quote; this item cannot be paid online." : "";
    return { item, product, variant, unit, quantity, minimum, problem };
  });
  const units = rows.reduce((total, row) => total + (Number.isFinite(row.quantity) ? row.quantity : 0), 0);
  const whatsappHref = enquiring && phone ? enquiryWhatsappLink(phone, enquiryMessage(storefront?.company_name || "", rows.map(row => ({
    name: row.product?.name || "Product", option: row.variant?.variant_name, quantity: row.quantity,
    price: row.variant ? row.variant.selling_price_display : row.product?.selling_price_display,
  })))) : "";
  const subtotal = rows.reduce((total, row) => total + (Number.isFinite(row.unit) && Number.isFinite(row.quantity) && row.quantity > 0 ? Math.round(row.unit * 100) * row.quantity : 0), 0);
  const checkout = (event: FormEvent) => {
    event.preventDefault();
    if (!ready || !enabled || rows.some(row => row.problem)) { setError("Resolve the cart messages before checkout."); return; }
    navigate(search.get("pickup") ? `/checkout?pickup=${encodeURIComponent(search.get("pickup")!)}` : "/checkout");
  };
  const template = storefront?.storefront_template || "current";
  if (loading) return <main className="loading">Loading store...</main>;
  if (!storefront) return <main className="loading">Open a workspace storefront to view its cart.</main>;
  return <><main className={`shop-account-page shopping-page storefront-commerce-page storefront-order-page storefront-cart-page--${template}`}><header className={`shop-account-heading storefront-order-heading storefront-order-heading--${template}`}><Link to="/">Continue shopping</Link><h1>{words.title}</h1><p>{storefront.company_name} · {cart.items.length} {cart.items.length === 1 ? "item" : "items"}{enquiring ? " · Enquiry, not an order" : ""}</p>{!enquiring ? <p>Availability is checked for your chosen fulfilment method at checkout.</p> : null}</header>
    <div className="shop-account-content">
      {error ? <FloatingAlert>{error}</FloatingAlert> : null}
      {!cart.items.length ? <section className="ops-card"><h2>Your {enquiring ? "enquiry list" : "cart"} is empty</h2><p>{enquiring ? "Add products and quantities, then send the whole list to the store in one WhatsApp message." : "Add products, choose quantities and pay for them together."}</p><Link className="btn" to="/">Browse products</Link></section>
        : !ready || !mode ? <p role="status">Checking current products and prices...</p> : <form className="cart-layout" onSubmit={checkout}>
          <div className="cart-items">{rows.map(({ item, product, variant, unit, quantity, minimum, problem }) => <article className="ops-card cart-item" key={cartItemKey(item)}>
            <ProductImageLink className="cart-item-image" item={item} name={product?.name || "Unavailable product"} imageUrl={productImage(product, item.variant_id)} />
            <div className="cart-item-details"><h2><Link to={productPagePath(item)}>{product?.name || "Unavailable product"}</Link></h2>{variant ? <p>{variant.variant_name}</p> : null}{Number.isFinite(unit) && unit > 0 ? <p>{rupees(Math.round(unit * 100))} each</p> : null}<small>Minimum: {minimum} {minimum === 1 ? "unit" : "units"}{product?.variants?.length ? " per size / colour" : ""}</small>
            <button type="button" className="cart-remove" aria-label={`Remove ${product?.name || "unavailable product"}${variant ? ` - ${variant.variant_name}` : ""}`} onClick={() => cart.remove(item)}><Trash2 size={14} aria-hidden="true" />Remove</button></div>
            <div className="cart-item-quantity"><QuantityStepper label={`Quantity for ${product?.name || "unavailable product"}${variant ? ` - ${variant.variant_name}` : ""}`} min={minimum} max={100} value={drafts[cartItemKey(item)] ?? String(item.quantity)} onChange={value => {
              setDrafts(previous => ({ ...previous, [cartItemKey(item)]: value }));
              if (Number.isInteger(Number(value)) && Number(value) >= minimum && Number(value) <= 100) cart.setQuantity(item, Number(value));
            }} />
            {quantity > 0 && Number.isFinite(unit) && unit > 0 ? <strong>{rupees(Math.round(unit * 100) * quantity)}</strong> : null}</div>
            {problem ? <p className="ops-error" role="alert">{problem}</p> : null}
          </article>)}</div>
          {enquiring ? <section className="ops-card cart-summary purchase-summary enquiry-summary"><h2>Enquiry summary</h2><dl className="order-totals"><div><dt>Products</dt><dd>{rows.length}</dd></div><div><dt>Total units</dt><dd>{units}</dd></div>{subtotal ? <div className="order-total"><dt>Listed value</dt><dd>{rupees(subtotal)}</dd></div> : null}</dl>
            <p className="purchase-fine-print">The store replies on WhatsApp with its best price, availability and delivery. Sending this list does not place an order or take payment.</p>
            {rows.some(row => !!row.problem) ? <button className="btn whatsapp-btn enquiry-send" type="button" disabled><MessageCircle size={16} aria-hidden="true" />Send enquiry on WhatsApp</button>
              : <a className="btn whatsapp-btn enquiry-send" href={whatsappHref} target="_blank" rel="noopener noreferrer"><MessageCircle size={16} aria-hidden="true" />Send enquiry on WhatsApp</a>}
            <button type="button" className="cart-clear" onClick={() => { if (window.confirm("Remove every product from your enquiry list?")) cart.removePurchased(cart.items); }}>Clear list</button>
          </section> : <section className="ops-card cart-summary purchase-summary"><h2>Order summary</h2><dl className="order-totals"><div><dt>Subtotal</dt><dd>{rupees(subtotal)}</dd></div><div><dt>Estimated delivery</dt><dd>{shipping ? rupees(shipping) : "Free"}</dd></div><div className="order-total"><dt>Estimated total</dt><dd>{rupees(subtotal + shipping)}</dd></div></dl><p className="purchase-fine-print">Prices and stock are confirmed at checkout. Items in your cart are not reserved.</p>
            {!enabled ? <p role="alert">This store is not taking online payments right now. Please contact the store.</p> : null}
            <button className="btn" disabled={!enabled || rows.some(row => !!row.problem)}>Continue to checkout</button><p className="purchase-fine-print">Sign in at checkout to place your order.</p>
          </section>}
        </form>}
    </div>
  </main><SiteFooter /></>;
}
