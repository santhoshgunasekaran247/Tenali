import { FloatingAlert } from "../components/Notifications";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../features/auth";
import { cartItemKey, useCart } from "../features/cart";
import { accountRequest, rupees } from "../features/shop";
import type { CatalogProduct } from "../types";
import { Package, Trash2 } from "lucide-react";
import { toAssetUrl } from "../features/catalog/utils";

export function CartPage() {
  const { storefront, loading } = useAuth();
  const cart = useCart();
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const [products, setProducts] = useState<Record<string, CatalogProduct>>({});
  const [failures, setFailures] = useState<Record<string, string>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [ready, setReady] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [shipping, setShipping] = useState(0);
  const [error, setError] = useState("");
  const productIds = [...new Set(cart.items.map(item => item.product_id))].sort().join(",");
  useEffect(() => {
    if (!storefront) return;
    let active = true;
    setReady(false); setError("");
    void Promise.all([
      Promise.all(productIds.split(",").filter(Boolean).map(async id => {
        try { return { id, product: (await api.product(id)).product, error: "" }; }
        catch (failure) { return { id, product: undefined, error: String(failure) }; }
      })),
      accountRequest<{ enabled: boolean; shipping_paise: number | null }>("/availability"),
    ]).then(([results, availability]) => {
      if (!active) return;
      setProducts(Object.fromEntries(results.flatMap(result => result.product ? [[result.id, result.product]] : [])));
      setFailures(Object.fromEntries(results.filter(result => result.error).map(result => [result.id, result.error])));
      setEnabled(availability.enabled); setShipping(availability.shipping_paise || 0); setReady(true);
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
    const stock = variant ? variant.stock_qty : product?.stock_qty;
    const unavailable = !product || (item.variant_id ? !variant : !!product.variants?.length);
    const problem = unavailable ? failures[item.product_id] || "This product or size / colour is no longer available. Remove it and choose again."
      : !Number.isFinite(unit) || unit <= 0 ? "Contact the store for a quote; this item cannot be paid online."
      : !Number.isInteger(quantity) || quantity < minimum || quantity > 100 ? `Choose ${minimum} to 100 whole units.`
      : Number(stock) < quantity ? "There is not enough stock for this quantity. Reduce it or contact the store." : "";
    return { item, product, variant, unit, quantity, minimum, problem };
  });
  const subtotal = rows.reduce((total, row) => total + (Number.isFinite(row.unit) && Number.isFinite(row.quantity) && row.quantity > 0 ? Math.round(row.unit * 100) * row.quantity : 0), 0);
  const checkout = (event: FormEvent) => {
    event.preventDefault();
    if (!ready || !enabled || rows.some(row => row.problem)) { setError("Resolve the cart messages before checkout."); return; }
    navigate(search.get("pickup") ? `/checkout?pickup=${encodeURIComponent(search.get("pickup")!)}` : "/checkout");
  };
  if (loading) return <main className="loading">Loading store...</main>;
  if (!storefront) return <main className="loading">Open a workspace storefront to view its cart.</main>;
  return <main className="shop-account-page shopping-page"><header className="shop-account-heading"><Link to="/">Continue shopping</Link><h1>Your Cart</h1><p>{storefront.company_name} · {cart.items.length} {cart.items.length === 1 ? "item" : "items"}</p></header>
    <div className="shop-account-content">
      {error ? <FloatingAlert>{error}</FloatingAlert> : null}
      {!cart.items.length ? <section className="ops-card"><h2>Your cart is empty</h2><p>Add products, choose quantities and pay for them together.</p><Link className="btn" to="/">Browse products</Link></section>
        : !ready ? <p role="status">Checking current products and prices...</p> : <form className="cart-layout" onSubmit={checkout}>
          <div className="cart-items">{rows.map(({ item, product, variant, unit, quantity, minimum, problem }) => <article className="ops-card cart-item" key={cartItemKey(item)}>
            <Link className="cart-item-image" to={`/products/${item.product_id}`} aria-label={`View ${product?.name || "product"}`}>{product?.image_url ? <img src={toAssetUrl(product.image_url)} alt="" /> : <Package size={28} aria-hidden="true" />}</Link>
            <div className="cart-item-details"><h2><Link to={`/products/${item.product_id}`}>{product?.name || "Unavailable product"}</Link></h2>{variant ? <p>{variant.variant_name}</p> : null}{Number.isFinite(unit) && unit > 0 ? <p>{rupees(Math.round(unit * 100))} each</p> : null}<small>Minimum: {minimum} {minimum === 1 ? "unit" : "units"}{product?.variants?.length ? " per size / colour" : ""}</small>
            <button type="button" className="cart-remove" aria-label={`Remove ${product?.name || "unavailable product"}${variant ? ` - ${variant.variant_name}` : ""}`} onClick={() => cart.remove(item)}><Trash2 size={14} aria-hidden="true" />Remove</button></div>
            <div className="cart-item-quantity"><label>Quantity<input aria-label={`Quantity for ${product?.name || "unavailable product"}${variant ? ` - ${variant.variant_name}` : ""}`} type="number" required min={minimum} max={100} step={1} value={drafts[cartItemKey(item)] ?? item.quantity} onChange={event => {
              const value = event.target.value; setDrafts(previous => ({ ...previous, [cartItemKey(item)]: value }));
              if (Number.isInteger(Number(value)) && Number(value) >= minimum && Number(value) <= 100) cart.setQuantity(item, Number(value));
            }} /></label>
            {quantity > 0 && Number.isFinite(unit) && unit > 0 ? <strong>{rupees(Math.round(unit * 100) * quantity)}</strong> : null}</div>
            {problem ? <p className="ops-error" role="alert">{problem}</p> : null}
          </article>)}</div>
          <section className="ops-card cart-summary purchase-summary"><h2>Order summary</h2><dl className="order-totals"><div><dt>Subtotal</dt><dd>{rupees(subtotal)}</dd></div><div><dt>Estimated delivery</dt><dd>{shipping ? rupees(shipping) : "Free"}</dd></div><div className="order-total"><dt>Estimated total</dt><dd>{rupees(subtotal + shipping)}</dd></div></dl><p className="purchase-fine-print">Prices and stock are confirmed at checkout. Items in your cart are not reserved.</p>
            {!enabled ? <p role="alert">This store is not taking online payments right now. You can keep your cart and contact the store on WhatsApp.</p> : null}
            <button className="btn" disabled={!enabled || rows.some(row => !!row.problem)}>Continue to checkout</button><p className="purchase-fine-print">Sign in at checkout to place your order.</p>
          </section>
        </form>}
    </div>
  </main>;
}
