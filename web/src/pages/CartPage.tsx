import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../features/auth";
import { cartItemKey, useCart } from "../features/cart";
import { accountRequest, rupees } from "../features/shop";
import type { CatalogProduct } from "../types";

export function CartPage() {
  const { storefront, loading } = useAuth();
  const cart = useCart();
  const navigate = useNavigate();
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
  const subtotal = rows.reduce((total, row) => total + (Number.isFinite(row.unit) ? Math.round(row.unit * 100) * row.quantity : 0), 0);
  const checkout = (event: FormEvent) => {
    event.preventDefault();
    if (!ready || !enabled || rows.some(row => row.problem)) { setError("Resolve the cart messages before checkout."); return; }
    navigate("/checkout");
  };
  if (loading) return <main className="loading">Loading store...</main>;
  if (!storefront) return <main className="loading">Open a workspace storefront to view its cart.</main>;
  return <main className="shop-account-page"><header className="shop-account-heading"><Link to="/">Continue shopping</Link><h1>Your Cart</h1><p>{storefront.company_name} only · Products from other workspaces stay in their own carts.</p></header>
    <div className="shop-account-content">
      {error ? <p className="ops-error" role="alert">{error}</p> : null}
      {!cart.items.length ? <section className="ops-card"><h2>Your cart is empty</h2><p>Add products, choose quantities and pay for them together.</p><Link className="btn" to="/">Browse products</Link></section>
        : !ready ? <p role="status">Checking current products and prices...</p> : <form onSubmit={checkout}>
          <div className="cart-items">{rows.map(({ item, product, variant, unit, quantity, minimum, problem }) => <article className="ops-card cart-item" key={cartItemKey(item)}>
            <div><h2><Link to={`/products/${item.product_id}`}>{product?.name || "Unavailable product"}</Link></h2>{variant ? <p>{variant.variant_name}</p> : null}<p>Minimum order: {minimum} units{product?.variants?.length ? " per size / colour" : ""}</p>{Number.isFinite(unit) && unit > 0 ? <p>{rupees(Math.round(unit * 100))} each</p> : null}</div>
            <label>Quantity for {product?.name || "unavailable product"}{variant ? ` - ${variant.variant_name}` : ""}<input type="number" required min={minimum} max={100} step={1} value={drafts[cartItemKey(item)] ?? item.quantity} onChange={event => {
              const value = event.target.value; setDrafts(previous => ({ ...previous, [cartItemKey(item)]: value }));
              if (Number.isInteger(Number(value)) && Number(value) >= minimum && Number(value) <= 100) cart.setQuantity(item, Number(value));
            }} /></label>
            {quantity > 0 && Number.isFinite(unit) && unit > 0 ? <strong>{rupees(Math.round(unit * 100) * quantity)}</strong> : null}
            <button type="button" className="btn light" onClick={() => cart.remove(item)}>Remove {product?.name || "unavailable product"}{variant ? ` - ${variant.variant_name}` : ""}</button>
            {problem ? <p className="ops-error" role="alert">{problem}</p> : null}
          </article>)}</div>
          <section className="ops-card cart-summary"><h2>Estimated total</h2><p>Items: {rupees(subtotal)}</p><p>Delivery for the whole order: {rupees(shipping)}</p><p><strong>Total: {rupees(subtotal + shipping)}</strong></p><p>Final prices, minimum quantities and available stock are checked again before payment. Adding to cart does not reserve stock.</p>
            {!enabled ? <p role="alert">This store is not taking online payments right now. You can keep your cart and contact the store on WhatsApp.</p> : null}
            <button className="btn" disabled={!enabled || rows.some(row => !!row.problem)}>Continue to checkout</button><p>You will sign in to a shopper account for this store before paying.</p>
          </section>
        </form>}
    </div>
  </main>;
}
